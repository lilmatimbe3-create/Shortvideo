import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

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

from app.config import UPLOADS_DIR, JOBS_DIR, STATIC_DIR
from app.transcriber import extract_audio, transcribe_audio, format_timestamp
from app.analyzer import find_best_moments, _collect_excerpt_for_range
from app.video_processor import generate_clips_package, cut_video_clip, slugify_filename
from app.transcriber import write_clip_srt

app = FastAPI(
    title="ShortVideo AI — Gerador Inteligente de Clips Curtos",
    description="Transforma vídeos longos (podcasts, aulas, diretos) em clips curtos prontos a publicar.",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Estado em memória com persistência em disco em data/jobs/<job_id>/status.json
JOBS_STATE: Dict[str, Dict[str, Any]] = {}


def _save_job_state(job_id: str) -> None:
    job = JOBS_STATE.get(job_id)
    if not job:
        return
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    status_file = job_dir / "status.json"
    status_file.write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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


def run_video_pipeline(
    job_id: str,
    video_path: Path,
    options: Dict[str, Any],
) -> None:
    """Executa todo o pipeline de IA em background: Áudio -> Transcrição -> LLM -> Corte de Clips."""
    job_dir = JOBS_DIR / job_id
    clips_dir = job_dir / "clips"
    audio_path = job_dir / "audio_16k.wav"

    try:
        # 1. Extração de Áudio
        _update_progress(
            job_id,
            10,
            "audio",
            "A extrair faixa de áudio do vídeo original com FFmpeg...",
        )
        extract_audio(video_path, audio_path)

        # 2. Transcrição com Timestamps
        def whisper_progress(pct: int, msg: str) -> None:
            _update_progress(job_id, pct, "transcription", msg)

        transcription = transcribe_audio(
            audio_path=audio_path,
            language=options.get("language", "pt"),
            model_size=options.get("whisper_model", "base"),
            on_progress=whisper_progress,
        )

        # Remover WAV temporário para poupar espaço em disco
        if audio_path.exists():
            audio_path.unlink(missing_ok=True)

        JOBS_STATE[job_id]["duration"] = transcription["duration"]
        JOBS_STATE[job_id]["duration_formatted"] = format_timestamp(
            transcription["duration"]
        )
        JOBS_STATE[job_id]["language"] = transcription["language"]
        JOBS_STATE[job_id]["segments"] = transcription["segments"]
        JOBS_STATE[job_id]["transcript_map"] = transcription["transcript_map"]

        # 3. Seleção dos Momentos Fortes pelo Modelo de Linguagem
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
            provider=options.get("llm_provider", "gemini"),
            api_key=options.get("api_key", ""),
            model_name=options.get("llm_model", ""),
            max_clips=int(options.get("max_clips", 5)),
            min_clip_seconds=int(options.get("min_duration", 15)),
            max_clip_seconds=int(options.get("max_duration", 75)),
        )

        JOBS_STATE[job_id]["llm_engine"] = analysis["engine"]

        # 4. Recorte do Vídeo Original e Empacotamento
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


@app.get("/", response_class=HTMLResponse)
async def index():
    index_file = STATIC_DIR / "index.html"
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.post("/api/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    language: str = Form("pt"),
    whisper_model: str = Form("base"),
    llm_provider: str = Form("gemini"),
    api_key: str = Form(""),
    llm_model: str = Form(""),
    max_clips: int = Form(5),
    min_duration: int = Form(15),
    max_duration: int = Form(75),
    vertical_crop: bool = Form(False),
    burn_subtitles: bool = Form(False),
):
    """Recebe o vídeo carregado pelo utilizador e inicia o pipeline de criação de clips."""
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    safe_ext = Path(video.filename or "video.mp4").suffix or ".mp4"
    video_path = job_dir / f"source{safe_ext}"

    with video_path.open("wb") as buffer:
        shutil.copyfileobj(video.file, buffer)

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
        "original_filename": video.filename,
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
    """Devolve o estado atual do processamento, transcrição e lista de clips gerados."""
    job = _load_job_state(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    return job


@app.get("/api/jobs/{job_id}/clips/{filename}")
async def download_single_clip(job_id: str, filename: str, download: bool = False):
    """Permite pré-visualizar no browser ou descarregar um clip ou legenda individual."""
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
    """Descarrega um ficheiro ZIP com a pasta completa de clips prontos a publicar."""
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
    """Permite ao utilizador ajustar manualmente os tempos de um corte ou criar um novo clip."""
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
