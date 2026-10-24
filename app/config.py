import os
import shutil
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

IS_SERVERLESS = bool(
    os.getenv("VERCEL")
    or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    or os.getenv("NOW_REGION")
)

if IS_SERVERLESS:
    DATA_DIR = Path(tempfile.gettempdir()) / "shortvideo_data"
else:
    DATA_DIR = BASE_DIR / "data"

UPLOADS_DIR = DATA_DIR / "uploads"
JOBS_DIR = DATA_DIR / "jobs"

for directory in (DATA_DIR, UPLOADS_DIR, JOBS_DIR):
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def get_ffmpeg_executable() -> str:
    """Localiza o executável do FFmpeg no sistema ou recorre ao imageio-ffmpeg."""
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ""


FFMPEG_BIN = get_ffmpeg_executable()
HAS_FFMPEG = bool(FFMPEG_BIN and shutil.which(FFMPEG_BIN) or (FFMPEG_BIN and Path(FFMPEG_BIN).exists()))

# Configurações predefinidas de IA
DEFAULT_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
