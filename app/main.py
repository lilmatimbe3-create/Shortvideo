import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
    HTTPException,
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import UPLOADS_DIR, JOBS_DIR, STATIC_DIR, IS_SERVERLESS, HAS_FFMPEG
from app.transcriber import (
    extract_audio,
    transcribe_audio,
    format_timestamp,
    format_srt_timestamp,
    TranscriptSegment,
    build_transcript_map,
    write_clip_srt,
)
from app.analyzer import find_best_moments, _collect_excerpt_for_range
from app.video_processor import generate_clips_package, cut_video_clip, slugify_filename

app = FastAPI(
    title="ShortVideo AI — Gerador Inteligente de Clips Curtos",
    description="Transforma vídeos longos (podcasts, aulas, diretos) em clips curtos prontos a publicar.",
    version="1.1.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

JOBS_STATE: Dict[str, Dict[str, Any]] = {}


def _save_job_state(job_id: str) -> None:
    job = JOBS_STATE.get(job_id)
    if not job:
        return
    try:
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        status_file = job_dir / "status.json"
        status_file.write_text(
            json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _load_job_state(job_id: str) -> Optional[Dict[str, Any]]:
    if job_id in JOBS_STATE:
        return JOBS_STATE[job_id]
    status_file = JOBS_DIR / job_id / "status.json"
    if status_file.exists():
        data = json.loads(status_file.read_text(encoding="utf-8"))
        JOBS_STATE[job_id] = data
        return data
    return None


def _update_progress(job_id: str, progress: int, step: str, message: str) -> None:
    if job_id in JOBS_STATE:
        JOBS_STATE[job_id]["progress"] = progress
        JOBS_STATE[job_id]["step"] = step
        JOBS_STATE[job_id]["message"] = message
        _save_job_state(job_id)


def _build_srt_string(
    segments: List[Dict[str, Any]], clip_start: float, clip_end: float
) -> str:
    blocks = []
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
        blocks.append(
            f"{counter}\n"
            f"{format_srt_timestamp(rel_start)} --> {format_srt_timestamp(rel_end)}\n"
            f"{seg['text'].strip()}\n"
        )
        counter += 1
    return "\n".join(blocks)


@app.get("/", response_class=HTMLResponse)
async def index():
    index_file = STATIC_DIR / "index.html"
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/api/environment")
async def get_environment():
    return {
        "is_serverless": IS_SERVERLESS,
        "has_ffmpeg": HAS_FFMPEG,
    }


class LightAnalyzeRequest(BaseModel):
    filename: str = "video.mp4"
    duration: float
    segments: List[Dict[str, Any]] = []
    llm_provider: str = "local"
    api_key: str = ""
    llm_model: str = ""
    max_clips: int = 5
    min_duration: int = 15
    max_duration: int = 75
    vertical_crop: bool = False
    burn_subtitles: bool = False


@app.post("/api/analyze-light")
async def analyze_light(req: LightAnalyzeRequest):
    """
    Endpoint leve compatível com Vercel Serverless (sem limite de tamanho de vídeo):
    recebe o mapa de segmentos extraído no browser, executa o modelo de linguagem (IA)
    e devolve os momentos selecionados com tempos de corte exatos e legendas SRT.
    """
    duration = max(1.0, float(req.duration))
    segments_dicts = req.segments

    if not segments_dicts:
        step = 15.0
        t = 0.0
        idx = 1
        while t < duration:
            end_t = min(duration, t + step)
            segments_dicts.append(
                {
                    "id": idx,
                    "start": round(t, 2),
                    "end": round(end_t, 2),
                    "text": f"Excerto de fala #{idx} ({format_timestamp(t)} → {format_timestamp(end_t)}).",
                }
            )
            idx += 1
            t = end_t

    seg_objs = [
        TranscriptSegment(
            id=int(s.get("id", i)),
            start=round(float(s["start"]), 2),
            end=round(float(s["end"]), 2),
            text=str(s.get("text", "")),
        )
        for i, s in enumerate(segments_dicts, start=1)
    ]
    transcript_map = build_transcript_map(seg_objs)

    analysis = find_best_moments(
        segments=segments_dicts,
        transcript_map=transcript_map,
        video_duration=duration,
        provider=req.llm_provider,
        api_key=req.api_key,
        model_name=req.llm_model,
        max_clips=req.max_clips,
        min_clip_seconds=req.min_duration,
        max_clip_seconds=req.max_duration,
    )

    clips_out = []
    for i, clip in enumerate(analysis["clips"], start=1):
        slug = slugify_filename(clip.get("title") or f"clip_{i}")
        base_name = f"clip_{i:02d}_{slug}"
        srt_content = _build_srt_string(segments_dicts, clip["start"], clip["end"])
        clips_out.append(
            {
                **clip,
                "filename": f"{base_name}.mp4",
                "srt_filename": f"{base_name}.srt",
                "srt_content": srt_content,
                "vertical_crop": req.vertical_crop,
                "burn_subtitles": req.burn_subtitles,
            }
        )

    return {
        "job_id": "browser_" + uuid.uuid4().hex[:8],
        "original_filename": req.filename,
        "duration": round(duration, 2),
        "duration_formatted": format_timestamp(duration),
        "llm_engine": analysis["engine"],
        "segments": segments_dicts,
        "transcript_map": transcript_map,
        "clips": clips_out,
        "browser_mode": True,
    }


def run_video_pipeline(
    job_id: str,
    video_path: Path,
    options: Dict[str, Any],
) -> None:
    """Executa todo o pipeline de IA em background no servidor local: Áudio -> Transcrição -> LLM -> Corte de Clips."""
    job_dir = JOBS_DIR / job_id
    clips_dir = job_dir / "clips"
    audio_path = job_dir / "audio_16k.wav"

    try:
        _update_progress(
            job_id,
            10,
            "audio",
            "A extrair faixa de áudio do vídeo original com FFmpeg...",
        )
        extract_audio(video_path, audio_path)

        def whisper_progress(pct: int, msg: str) -> None:
            _update_progress(job_id, pct, "transcription", msg)

        transcription = transcribe_audio(
            audio_path=audio_path,
            language=options.get("language", "pt"),
            model_size=options.get("whisper_model", "base"),
            on_progress=whisper_progress,
        )

        if audio_path.exists():
            audio_path.unlink(missing_ok=True)

        JOBS_STATE[job_id]["duration"] = transcription["duration"]
        JOBS_STATE[job_id]["duration_formatted"] = format_timestamp(
            transcription["duration"]
        )
        JOBS_STATE[job_id]["language"] = transcription["language"]
        JOBS_STATE[job_id]["segments"] = transcription["segments"]
        JOBS_STATE[job_id]["transcript_map"] = transcription["transcript_map"]

        _update_progress(
            job_id,
            60,
            "analysis",
            "O modelo de linguagem está a ler o mapa do vídeo e a selecionar os excertos mais fortes...",
        )
        analysis = find_best_moments(
            segments=transcription["segments"],
            transcript_map=transcription["transcript_map"],
            video_duration=transcription["duration"],
            provider=options.get("llm_provider", "local"),
            api_key=options.get("api_key", ""),
            model_name=options.get("llm_model", ""),
            max_clips=int(options.get("max_clips", 5)),
            min_clip_seconds=int(options.get("min_duration", 15)),
            max_clip_seconds=int(options.get("max_duration", 75)),
        )

        JOBS_STATE[job_id]["llm_engine"] = analysis["engine"]

        def cutting_progress(pct: int, msg: str) -> None:
            _update_progress(job_id, pct, "cutting", msg)

        package = generate_clips_package(
            source_video=video_path,
            clips_dir=clips_dir,
            selected_clips=analysis["clips"],
            transcript_segments=transcription["segments"],
            vertical_crop=bool(options.get("vertical_crop", False)),
            burn_subtitles=bool(options.get("burn_subtitles", False)),
            on_progress=cutting_progress,
        )

        JOBS_STATE[job_id]["clips"] = package["clips"]
        JOBS_STATE[job_id]["output_folder"] = package["output_folder"]
        JOBS_STATE[job_id]["status"] = "completed"
        _update_progress(
            job_id,
            100,
            "completed",
            f"Concluído! {len(package['clips'])} clips prontos a descarregar e publicar.",
        )

    except Exception as exc:
        JOBS_STATE[job_id]["status"] = "failed"
        _update_progress(
            job_id,
            100,
            "error",
            f"Ocorreu um erro durante o processamento: {exc}",
        )


@app.post("/api/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    video: Optional[UploadFile] = File(None),
    local_video_path: str = Form(""),
    language: str = Form("pt"),
    whisper_model: str = Form("base"),
    llm_provider: str = Form("local"),
    api_key: str = Form(""),
    llm_model: str = Form(""),
    max_clips: int = Form(5),
    min_duration: int = Form(15),
    max_duration: int = Form(75),
    vertical_crop: bool = Form(False),
    burn_subtitles: bool = Form(False),
):
    """Recebe o vídeo carregado pelo utilizador (ou caminho local) e inicia o pipeline de criação de clips."""
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    original_filename = "video.mp4"
    clean_local = local_video_path.strip().strip('"').strip("'")

    if video and video.filename:
        original_filename = video.filename
        safe_ext = Path(video.filename).suffix or ".mp4"
        video_path = job_dir / f"source{safe_ext}"
        with video_path.open("wb") as buffer:
            while True:
                chunk = await video.read(4 * 1024 * 1024)
                if not chunk:
                    break
                buffer.write(chunk)
    elif clean_local:
        src_path = Path(clean_local)
        if not src_path.exists() or not src_path.is_file():
            raise HTTPException(
                status_code=400,
                detail=f"O ficheiro indicado não existe: {clean_local}",
            )
        original_filename = src_path.name
        safe_ext = src_path.suffix or ".mp4"
        video_path = job_dir / f"source{safe_ext}"
        shutil.copy2(src_path, video_path)
    else:
        raise HTTPException(
            status_code=400,
            detail="Nenhum ficheiro de vídeo foi recebido. Selecione um vídeo ou indique o caminho local.",
        )

    options = {
        "language": language,
        "whisper_model": whisper_model,
        "llm_provider": llm_provider,
        "api_key": api_key,
        "llm_model": llm_model,
        "max_clips": max_clips,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "vertical_crop": vertical_crop,
        "burn_subtitles": burn_subtitles,
    }

    JOBS_STATE[job_id] = {
        "job_id": job_id,
        "original_filename": original_filename,
        "created_at": datetime.now().isoformat(),
        "status": "processing",
        "step": "upload",
        "progress": 5,
        "message": "Vídeo recebido. A iniciar processamento...",
        "options": {k: v for k, v in options.items() if k != "api_key"},
        "clips": [],
        "segments": [],
        "transcript_map": "",
    }
    _save_job_state(job_id)

    background_tasks.add_task(run_video_pipeline, job_id, video_path, options)
    return {"job_id": job_id, "status": "processing"}


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = _load_job_state(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    return job


@app.get("/api/jobs/{job_id}/clips/{filename}")
async def download_single_clip(job_id: str, filename: str, download: bool = False):
    clip_path = JOBS_DIR / job_id / "clips" / filename
    if not clip_path.exists():
        raise HTTPException(status_code=404, detail="Ficheiro de clip não encontrado.")

    media_type = "video/mp4" if filename.endswith(".mp4") else "text/plain; charset=utf-8"
    if download:
        return FileResponse(
            str(clip_path), media_type=media_type, filename=filename
        )
    return FileResponse(str(clip_path), media_type=media_type)


@app.get("/api/jobs/{job_id}/download-all")
async def download_all_clips(job_id: str):
    zip_path = JOBS_DIR / job_id / "clips_prontos.zip"
    if not zip_path.exists():
        raise HTTPException(
            status_code=404, detail="Pacote ZIP de clips ainda não disponível."
        )
    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"clips_{job_id}.zip",
    )


class CustomCutRequest(BaseModel):
    title: str
    start: float
    end: float
    vertical_crop: bool = False
    burn_subtitles: bool = False


@app.post("/api/jobs/{job_id}/custom-cut")
async def create_custom_cut(job_id: str, req: CustomCutRequest):
    job = _load_job_state(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")

    job_dir = JOBS_DIR / job_id
    source_candidates = list(job_dir.glob("source.*"))
    if not source_candidates:
        raise HTTPException(status_code=404, detail="Vídeo original não encontrado.")

    source_video = source_candidates[0]
    clips_dir = job_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    next_index = len(job.get("clips", [])) + 1
    slug = slugify_filename(req.title)
    base_name = f"clip_{next_index:02d}_{slug}"
    mp4_filename = f"{base_name}.mp4"
    srt_filename = f"{base_name}.srt"
    mp4_path = clips_dir / mp4_filename
    srt_path = clips_dir / srt_filename

    segments = job.get("segments", [])
    write_clip_srt(segments, req.start, req.end, srt_path)

    cut_video_clip(
        source_video=source_video,
        output_path=mp4_path,
        start_time=req.start,
        end_time=req.end,
        vertical_crop=req.vertical_crop,
        burn_subtitles=req.burn_subtitles,
        srt_path=srt_path,
    )

    new_clip = {
        "index": next_index,
        "title": req.title,
        "start": round(req.start, 2),
        "end": round(req.end, 2),
        "duration": round(req.end - req.start, 2),
        "start_formatted": format_timestamp(req.start),
        "end_formatted": format_timestamp(req.end),
        "category": "Corte Personalizado",
        "hook_score": 95,
        "reason": "Momento definido ou ajustado pelo utilizador a partir do mapa de transcrição.",
        "excerpt": _collect_excerpt_for_range(segments, req.start, req.end),
        "filename": mp4_filename,
        "srt_filename": srt_filename,
        "file_size_mb": round(mp4_path.stat().st_size / (1024 * 1024), 2),
        "vertical_crop": req.vertical_crop,
        "burn_subtitles": req.burn_subtitles,
    }

    job.setdefault("clips", []).append(new_clip)
    _save_job_state(job_id)
    return new_clip
