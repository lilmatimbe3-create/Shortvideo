import json
import re
from typing import List, Dict, Any, Optional
import httpx

from app.config import (
    DEFAULT_LLM_PROVIDER,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)
from app.transcriber import format_timestamp


SYSTEM_PROMPT = """És um editor de vídeo especialista em conteúdo viral (TikTok, Reels, YouTube Shorts) e curadoria de podcasts, aulas e transmissões em direto.
A tua missão é analisar a transcrição completa de um vídeo (com o instante exato em segundos em que cada frase começa e termina) e selecionar os momentos mais fortes.

Procura especificamente excertos que:
1. Contenham uma ideia marcante, uma história bem contada, uma explicação brilhante ou uma resposta inesperada.
2. Façam sentido sozinhos (tenham um início forte que prenda a atenção — "hook" — e uma conclusão clara, sem cortar frases a meio).
3. Respeitem a duração alvo pedida pelo utilizador (por predefinição entre 20 e 75 segundos).

Responde APENAS com um objeto JSON válido no seguinte formato:
{
  "clips": [
    {
      "title": "Título apelativo do momento",
      "start": 12.50,
      "end": 58.20,
      "category": "Ideia Marcante | História | Resposta Inesperada | Dica Prática",
      "hook_score": 94,
      "reason": "Explicação curta de porque este momento tem força para prender a atenção.",
      "excerpt": "Resumo ou transcrição das frases incluídas neste corte."
    }
  ]
}
"""


def build_user_prompt(
    transcript_map: str,
    video_duration: float,
    max_clips: int = 5,
    min_clip_seconds: int = 15,
    max_clip_seconds: int = 75,
) -> str:
    return (
        f"Duração total do vídeo: {video_duration:.2f} segundos ({format_timestamp(video_duration)}).\n"
        f"Seleciona até {max_clips} momentos de maior impacto.\n"
        f"Cada clip deve ter entre {min_clip_seconds} e {max_clip_seconds} segundos (salvo se o vídeo original for mais curto).\n"
        f"Usa exatamente os timestamps numéricos em segundos (`start` e `end`) presentes no mapa abaixo.\n\n"
        f"=== MAPA DE TRANSCRIÇÃO DO VÍDEO ===\n"
        f"{transcript_map}"
    )


def _extract_json(raw_text: str) -> Dict[str, Any]:
    """Extrai o bloco JSON da resposta do modelo de linguagem."""
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        brace_start = cleaned.find("{")
        brace_end = cleaned.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            cleaned = cleaned[brace_start : brace_end + 1]
    return json.loads(cleaned)


def _analyze_with_gemini(prompt: str, api_key: str, model_name: str) -> Dict[str, Any]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,
            response_mime_type="application/json",
        ),
    )
    return _extract_json(response.text)


def _analyze_with_openai(prompt: str, api_key: str, model_name: str) -> Dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model_name,
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return _extract_json(response.choices[0].message.content or "{}")


def _analyze_with_ollama(prompt: str, base_url: str, model_name: str) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model_name,
        "format": "json",
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    with httpx.Client(timeout=180.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "{}")
        return _extract_json(content)


def _heuristic_highlight_selection(
    segments: List[Dict[str, Any]],
    video_duration: float,
    max_clips: int = 5,
    min_clip_seconds: int = 15,
    max_clip_seconds: int = 60,
) -> List[Dict[str, Any]]:
    """
    Seletor heurístico inteligente caso nenhuma chave de API externa esteja ativa:
    avalia densidade narrativa, palavras-chave de impacto, perguntas/respostas e pontuação
    para encontrar blocos coesos de frases completas.
    """
    if not segments:
        return []

    impact_words = {
        "segredo", "importante", "nunca", "sempre", "verdade", "história",
        "exemplo", "aconteceu", "problema", "solução", "incrível", "erro",
        "dica", "fundamental", "essencial", "futuro", "mudou", "aprender",
        "como", "porque", "porquê", "ideia", "momento", "lição", "chave",
        "sucesso", "dinheiro", "tempo", "vida", "estratégia", "resultado",
    }

    candidates = []
    n = len(segments)

    for i in range(n):
        start_time = float(segments[i]["start"])
        texts = []
        score = 0.0
        end_time = start_time

        for j in range(i, n):
            seg = segments[j]
            end_time = float(seg["end"])
            duration = end_time - start_time
            texts.append(seg["text"].strip())

            txt_lower = seg["text"].lower()
            words = re.findall(r"\w+", txt_lower)
            keyword_hits = sum(1 for w in words if w in impact_words)
            question_bonus = 3.0 if "?" in seg["text"] else 0.0
            exclamation_bonus = 2.0 if "!" in seg["text"] else 0.0
            density = len(words) / max(1.0, float(seg["end"]) - float(seg["start"]))

            score += keyword_hits * 4.0 + question_bonus + exclamation_bonus + density

            if duration >= min_clip_seconds or j == n - 1:
                if duration <= max_clip_seconds or len(texts) == 1:
                    full_text = " ".join(texts)
                    ends_cleanly = full_text.endswith((".", "!", "?"))
                    final_score = score + (5.0 if ends_cleanly else 0.0)
                    candidates.append(
                        {
                            "start": round(start_time, 2),
                            "end": round(min(video_duration, end_time), 2),
                            "score": final_score,
                            "excerpt": full_text,
                        }
                    )
                if duration >= max_clip_seconds:
                    break

    candidates.sort(key=lambda c: c["score"], reverse=True)

    selected = []
    for cand in candidates:
        if len(selected) >= max_clips:
            break
        # Evita sobreposição entre clips selecionados
        overlaps = any(
            not (cand["end"] <= s["start"] + 2.0 or cand["start"] >= s["end"] - 2.0)
            for s in selected
        )
        if not overlaps:
            selected.append(cand)

    selected.sort(key=lambda c: c["start"])

    results = []
    for idx, item in enumerate(selected, start=1):
        excerpt = item["excerpt"]
        first_Words = " ".join(excerpt.split()[:7]).strip(".,!?:;")
        hook_score = min(98, max(72, int(75 + (item["score"] % 23))))
        results.append(
            {
                "title": f"Momento #{idx}: {first_Words}...",
                "start": item["start"],
                "end": item["end"],
                "category": "Destaque Automático",
                "hook_score": hook_score,
                "reason": "Excerto autónomo selecionado pela densidade de ideias, ritmo de fala e fecho completo de raciocínio.",
                "excerpt": excerpt,
            }
        )
    return results


def find_best_moments(
    segments: List[Dict[str, Any]],
    transcript_map: str,
    video_duration: float,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    max_clips: int = 5,
    min_clip_seconds: int = 15,
    max_clip_seconds: int = 75,
) -> Dict[str, Any]:
    """
    Analisa a transcrição com um modelo de linguagem (Gemini, OpenAI ou Ollama)
    e devolve a lista validada dos melhores excertos com início e fim exatos.
    """
    chosen_provider = (provider or DEFAULT_LLM_PROVIDER or "gemini").lower()
    prompt = build_user_prompt(
        transcript_map=transcript_map,
        video_duration=video_duration,
        max_clips=max_clips,
        min_clip_seconds=min_clip_seconds,
        max_clip_seconds=max_clip_seconds,
    )

    raw_clips: List[Dict[str, Any]] = []
    used_engine = chosen_provider

    try:
        if chosen_provider == "gemini":
            key = (api_key or GEMINI_API_KEY).strip()
            if not key:
                raise ValueError("Sem chave GEMINI_API_KEY configurada.")
            parsed = _analyze_with_gemini(
                prompt, key, model_name or GEMINI_MODEL
            )
            raw_clips = parsed.get("clips", [])
        elif chosen_provider == "openai":
            key = (api_key or OPENAI_API_KEY).strip()
            if not key:
                raise ValueError("Sem chave OPENAI_API_KEY configurada.")
            parsed = _analyze_with_openai(
                prompt, key, model_name or OPENAI_MODEL
            )
            raw_clips = parsed.get("clips", [])
        elif chosen_provider == "ollama":
            parsed = _analyze_with_ollama(
                prompt, OLLAMA_BASE_URL, model_name or OLLAMA_MODEL
            )
            raw_clips = parsed.get("clips", [])
        else:
            raise ValueError(f"Modo heurístico local selecionado ({chosen_provider}).")
    except Exception as exc:
        used_engine = f"heurístico local (fallback: {exc})"
        raw_clips = _heuristic_highlight_selection(
            segments=segments,
            video_duration=video_duration,
            max_clips=max_clips,
            min_clip_seconds=min_clip_seconds,
            max_clip_seconds=max_clip_seconds,
        )

    validated_clips = []
    for idx, clip in enumerate(raw_clips[:max_clips], start=1):
        start = max(0.0, float(clip.get("start", 0.0)))
        end = min(float(video_duration), float(clip.get("end", start + 30.0)))
        if end <= start + 1.0:
            end = min(float(video_duration), start + min(30.0, float(video_duration)))

        excerpt = clip.get("excerpt") or _collect_excerpt_for_range(segments, start, end)
        validated_clips.append(
            {
                "index": idx,
                "title": clip.get("title") or f"Clip #{idx}",
                "start": round(start, 2),
                "end": round(end, 2),
                "duration": round(end - start, 2),
                "start_formatted": format_timestamp(start),
                "end_formatted": format_timestamp(end),
                "category": clip.get("category") or "Momento Forte",
                "hook_score": int(clip.get("hook_score", 88)),
                "reason": clip.get("reason")
                or "Excerto com forte capacidade de retenção e sentido completo.",
                "excerpt": excerpt,
            }
        )

    return {
        "engine": used_engine,
        "clips": validated_clips,
    }


def _collect_excerpt_for_range(
    segments: List[Dict[str, Any]], start: float, end: float
) -> str:
    matched = [
        s["text"].strip()
        for s in segments
        if float(s["end"]) > start and float(s["start"]) < end
    ]
    return " ".join(matched)
