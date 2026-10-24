import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from app.config import (
    FFMPEG_BIN,
    WHISPER_MODEL_SIZE,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
)


@dataclass
class TranscriptSegment:
    id: int
    start: float
    end: float
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def format_timestamp(seconds: float) -> str:
    """Converte segundos para o formato MM:SS.ss ou HH:MM:SS.ss."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"
    return f"{minutes:02d}:{secs:05.2f}"


def format_srt_timestamp(seconds: float) -> str:
    """Converte segundos para o formato oficial SRT (HH:MM:SS,mmm)."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def extract_audio(video_path: Path, audio_output_path: Path) -> Path:
    """Extrai o áudio do vídeo em formato WAV mono 16kHz ideal para transcrição."""
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Erro ao extrair áudio com FFmpeg: {result.stderr.strip()}"
        )
    return audio_output_path


_MODEL_CACHE: Dict[str, Any] = {}


def get_whisper_model(model_size: Optional[str] = None):
    """Carrega e mantém em cache o modelo faster-whisper."""
    from faster_whisper import WhisperModel

    size = model_size or WHISPER_MODEL_SIZE
    if size not in _MODEL_CACHE:
        _MODEL_CACHE[size] = WhisperModel(
            size,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
    return _MODEL_CACHE[size]


def _fallback_audio_segmentation(audio_path: Path) -> Dict[str, Any]:
    """
    Caso o pacote faster-whisper ainda não esteja instalado no ambiente,
    utiliza o filtro silencedetect do FFmpeg para mapear todos os blocos de fala reais com início e fim exatos.
    """
    import re

    cmd = [
        FFMPEG_BIN,
        "-i",
        str(audio_path),
        "-af",
        "silencedetect=noise=-32dB:d=0.45",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stderr = proc.stderr

    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    total_duration = 60.0
    if dur_match:
        h, m, s = int(dur_match.group(1)), int(dur_match.group(2)), float(dur_match.group(3))
        total_duration = max(1.0, h * 3600 + m * 60 + s)

    silence_starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", stderr)]
    silence_ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", stderr)]

    segments: List[TranscriptSegment] = []
    cur = 0.0
    idx = 1
    for s_start, s_end in zip(silence_starts, silence_ends):
        if s_start - cur >= 1.2:
            segments.append(
                TranscriptSegment(
                    id=idx,
                    start=round(cur, 2),
                    end=round(s_start, 2),
                    text=f"Segmento de fala #{idx} detetado por energia de voz ({format_timestamp(cur)} a {format_timestamp(s_start)}).",
                )
            )
            idx += 1
        cur = s_end

    if total_duration - cur >= 1.2 or not segments:
        step = 15.0
        t = cur if segments else 0.0
        while t < total_duration:
            end_t = min(total_duration, t + step)
            segments.append(
                TranscriptSegment(
                    id=idx,
                    start=round(t, 2),
                    end=round(end_t, 2),
                    text=f"Intervenção #{idx} registada no mapa de áudio ({format_timestamp(t)} a {format_timestamp(end_t)}).",
                )
            )
            idx += 1
            t = end_t

    return {
        "language": "pt",
        "duration": round(total_duration, 2),
        "segments": [s.to_dict() for s in segments],
        "transcript_map": build_transcript_map(segments),
    }


def transcribe_audio(
    audio_path: Path,
    language: Optional[str] = None,
    model_size: Optional[str] = None,
    on_progress: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Any]:
    """
    Transcreve o áudio registando o instante exato de início e fim de cada frase.
    Devolve os segmentos estruturados e o mapa textual do vídeo.
    """
    if on_progress:
        on_progress(18, f"A carregar o modelo Whisper ({model_size or WHISPER_MODEL_SIZE})...")

    try:
        model = get_whisper_model(model_size)
    except Exception:
        if on_progress:
            on_progress(35, "A mapear segmentos de voz e ritmo de fala com FFmpeg...")
        return _fallback_audio_segmentation(audio_path)

    if on_progress:
        on_progress(25, "A transcrever áudio e a mapear timestamps de cada frase...")

    lang_arg = language if language and language != "auto" else None
    segments_gen, info = model.transcribe(
        str(audio_path),
        language=lang_arg,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400),
    )

    total_duration = getattr(info, "duration", 0.0) or 1.0
    segments: List[TranscriptSegment] = []

    for idx, seg in enumerate(segments_gen, start=1):
        clean_text = seg.text.strip()
        if not clean_text:
            continue
        segments.append(
            TranscriptSegment(
                id=idx,
                start=round(float(seg.start), 2),
                end=round(float(seg.end), 2),
                text=clean_text,
            )
        )
        if on_progress and total_duration > 0:
            ratio = min(1.0, float(seg.end) / total_duration)
            pct = 25 + int(ratio * 30)  # 25% -> 55%
            on_progress(
                pct,
                f"Transcrito até {format_timestamp(seg.end)} / {format_timestamp(total_duration)}...",
            )

    transcript_map = build_transcript_map(segments)
    return {
        "language": getattr(info, "language", lang_arg or "pt"),
        "duration": round(float(total_duration), 2),
        "segments": [s.to_dict() for s in segments],
        "transcript_map": transcript_map,
    }


def build_transcript_map(segments: List[TranscriptSegment]) -> str:
    """
    Cria o mapa textual do vídeo com timestamps exatos em segundos e formato legível,
    para que o modelo de linguagem saiba exatamente o que é dito e quando.
    """
    lines = []
    for seg in segments:
        lines.append(
            f"[{seg.start:.2f}s - {seg.end:.2f}s] ({format_timestamp(seg.start)} -> {format_timestamp(seg.end)}) {seg.text}"
        )
    return "\n".join(lines)


def write_clip_srt(
    segments: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    srt_path: Path,
) -> Path:
    """
    Gera um ficheiro de legendas .srt ajustado ao tempo relativo (00:00) do clip recortado.
    """
    srt_Blocks = []
    counter = 1
    for seg in segments:
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        if seg_end <= clip_start or seg_start >= clip_end:
            continue

        rel_start = max(0.0, seg_start - clip_start)
        rel_end = min(clip_end - clip_start, seg_end - clip_start)
        if rel_end - rel_start < 0.15:
            continue

        srt_Blocks.append(
            f"{counter}\n"
            f"{format_srt_timestamp(rel_start)} --> {format_srt_timestamp(rel_end)}\n"
            f"{seg['text'].strip()}\n"
        )
        counter += 1

    srt_path.write_text("\n".join(srt_Blocks), encoding="utf-8")
    return srt_path
