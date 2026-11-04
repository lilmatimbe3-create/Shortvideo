import re
import subprocess
import zipfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from app.config import FFMPEG_BIN
from app.transcriber import write_clip_srt


def slugify_filename(text: str, max_length: int = 42) -> str:
    """Converte o título do clip num nome de ficheiro seguro e legível."""
    cleaned = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    slug = re.sub(r"[-\s]+", "_", cleaned)
    return slug[:max_length].strip("_") or "clip"


def _escape_ffmpeg_subtitles_path(srt_path: Path) -> str:
    """Escapa o caminho no Windows para o filtro `subtitles=` do FFmpeg."""
    posix = srt_path.resolve().as_posix()
    # Escapar ':' da letra de unidade no Windows (C:/... -> C\:/...)
    return posix.replace(":", r"\:")


def _probe_video_specs(video_path: Path) -> tuple[int, bool]:
    """Descobre a altura do vídeo e se é vertical (9:16)."""
    try:
        cmd = [FFMPEG_BIN, "-i", str(video_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        match = re.search(r"(\d{3,4})x(\d{3,4})", res.stderr)
        if match:
            w, h = int(match.group(1)), int(match.group(2))
            return h, (h > w)
    except Exception:
        pass
    return 720, False


def _get_subtitles_filter(
    srt_path: Path, is_vertical: bool = False, video_height: int = 720
) -> str:
    """
    Gera o filtro de legendas FFmpeg com tamanho e margem vertical otimizados:
    - Garante que a legenda fica posicionada ACIMA dos controlos do leitor de vídeo (MarginV >= 70).
    - Ajusta proporções automaticamente para formato horizontal (16:9) e vertical (9:16).
    """
    escaped_srt = _escape_ffmpeg_subtitles_path(srt_path)
    if is_vertical or video_height >= 1600:
        fontsize = 44
        margin_v = 180
    elif video_height >= 1000:
        fontsize = 32
        margin_v = 90
    else:
        fontsize = 26
        margin_v = 72

    return (
        f"subtitles='{escaped_srt}':force_style="
        f"'Fontname=Arial,Bold=1,Fontsize={fontsize},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"BorderStyle=3,Outline=2.6,Shadow=1,MarginV={margin_v},Alignment=2'"
    )


def cut_video_clip(
    source_video: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
    vertical_crop: bool = False,
    burn_subtitles: bool = False,
    srt_path: Optional[Path] = None,
) -> Path:
    """
    Recorta o vídeo original entre `start_time` e `end_time` criando um ficheiro MP4 independente.
    Suporta opcionalmente formato vertical 9:16 (TikTok/Reels/Shorts) e legendas embutidas.
    """
    duration = max(0.5, float(end_time) - float(start_time))
    vf_filters: List[str] = []

    if vertical_crop:
        # Enquadramento vertical 9:16 centrado com resolução 1080x1920
        vf_filters.append(
            "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920:flags=lanczos,setsar=1"
        )

    if burn_subtitles and srt_path and srt_path.exists() and srt_path.stat().st_size > 0:
        vf_filters.append(
            _get_subtitles_filter(
                srt_path,
                is_vertical=vertical_crop,
                video_height=1920 if vertical_crop else 720,
            )
        )

    cmd = [
        FFMPEG_BIN,
        "-y",
        "-ss",
        f"{start_time:.2f}",
        "-i",
        str(source_video),
        "-t",
        f"{duration:.2f}",
    ]

    if vf_filters:
        cmd.extend(["-vf", ",".join(vf_filters)])

    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Erro ao recortar o clip ({output_path.name}): {result.stderr[-500:]}"
        )
    return output_path


def burn_subtitles_to_clip(
    input_clip_path: Path,
    srt_path: Path,
    output_path: Path,
) -> Path:
    """Queima legendas SRT sincronizadas diretamente num clip MP4 já recortado com posição e visibilidade otimizadas."""
    if not srt_path.exists() or srt_path.stat().st_size == 0:
        raise ValueError("Ficheiro de legendas SRT não encontrado ou vazio.")

    video_height, is_vertical = _probe_video_specs(input_clip_path)
    sub_filter = _get_subtitles_filter(
        srt_path, is_vertical=is_vertical, video_height=video_height
    )

    cmd = [
        FFMPEG_BIN,
        "-y",
        "-i",
        str(input_clip_path),
        "-vf",
        sub_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Erro ao embutir legendas no clip: {result.stderr[-500:]}")
    return output_path


def generate_clips_package(
    source_video: Path,
    clips_dir: Path,
    selected_clips: List[Dict[str, Any]],
    transcript_segments: List[Dict[str, Any]],
    vertical_crop: bool = False,
    burn_subtitles: bool = False,
    on_progress: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Any]:
    """
    Corta todos os clips selecionados pela IA, gera os respetivos ficheiros .srt
    e empacota a pasta final num ficheiro .zip pronto a descarregar.
    """
    clips_dir.mkdir(parents=True, exist_ok=True)
    total = max(1, len(selected_clips))
    generated_files: List[Dict[str, Any]] = []

    for i, clip in enumerate(selected_clips, start=1):
        start_time = float(clip["start"])
        end_time = float(clip["end"])
        title = clip.get("title") or f"Clip {i}"
        slug = slugify_filename(title)
        base_name = f"clip_{i:02d}_{slug}"

        mp4_filename = f"{base_name}.mp4"
        srt_filename = f"{base_name}.srt"
        mp4_path = clips_dir / mp4_filename
        srt_path = clips_dir / srt_filename

        if on_progress:
            pct = 70 + int(((i - 1) / total) * 25)
            on_progress(
                pct,
                f"A recortar clip {i}/{total}: «{title}» ({clip.get('start_formatted')} → {clip.get('end_formatted')})...",
            )

        write_clip_srt(
            segments=transcript_segments,
            clip_start=start_time,
            clip_end=end_time,
            srt_path=srt_path,
        )

        cut_video_clip(
            source_video=source_video,
            output_path=mp4_path,
            start_time=start_time,
            end_time=end_time,
            vertical_crop=vertical_crop,
            burn_subtitles=burn_subtitles,
            srt_path=srt_path,
        )

        clip_record = {
            **clip,
            "filename": mp4_filename,
            "srt_filename": srt_filename,
            "file_size_mb": round(mp4_path.stat().st_size / (1024 * 1024), 2),
            "vertical_crop": vertical_crop,
            "burn_subtitles": burn_subtitles,
        }
        generated_files.append(clip_record)

    zip_path = clips_dir.parent / "clips_prontos.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in generated_files:
            mp4_file = clips_dir / item["filename"]
            srt_file = clips_dir / item["srt_filename"]
            if mp4_file.exists():
                zf.write(mp4_file, arcname=mp4_file.name)
            if srt_file.exists():
                zf.write(srt_file, arcname=srt_file.name)

    return {
        "clips": generated_files,
        "output_folder": str(clips_dir),
        "zip_path": str(zip_path),
    }
