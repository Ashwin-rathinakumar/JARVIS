import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

load_dotenv()

JARVIS_NAME = "JARVIS"
VERSION = "0.9"

# Server Host and Port
JARVIS_HOST = os.getenv("JARVIS_HOST", "127.0.0.1")
JARVIS_PORT = int(os.getenv("JARVIS_PORT", "8000"))

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
WORKSPACE_DIR = BASE_DIR / "workspace"
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "jarvis.db")))
DOCUMENTS_DB_PATH = Path(os.getenv("DOCUMENTS_DB_PATH", str(DATA_DIR / "documents.db")))
LOG_DIR = BASE_DIR / "logs"

# Ensure essential directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Allowed paths for safe filesystem operations
_raw_allowed = os.getenv("JARVIS_ALLOWED_PATHS", "")
if _raw_allowed.strip():
    JARVIS_ALLOWED_PATHS: List[Path] = [
        Path(p.strip()).resolve() for p in _raw_allowed.split(",") if p.strip()
    ]
else:
    JARVIS_ALLOWED_PATHS: List[Path] = [BASE_DIR.resolve(), WORKSPACE_DIR.resolve()]

# Memory and Context Limits
MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "10"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))

# Optional LLM provider. Existing explicit/legacy settings remain supported.
# Unconfigured, empty, 'none', or 'disabled' leaves local commands fully available.
LLM_PROVIDER = os.getenv("JARVIS_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "none")).strip().lower()
JARVIS_LLM_BASE_URL = os.getenv("JARVIS_LLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
JARVIS_LLM_MODEL = os.getenv("JARVIS_LLM_MODEL", "nvidia/nemotron")
JARVIS_LLM_TIMEOUT = int(os.getenv("JARVIS_LLM_TIMEOUT", "45"))
JARVIS_LLM_API_KEY = os.getenv("JARVIS_LLM_API_KEY", "")
JARVIS_LLM_TEMPERATURE = float(os.getenv("JARVIS_LLM_TEMPERATURE", "0.3"))
JARVIS_LLM_MAX_TOKENS = int(os.getenv("JARVIS_LLM_MAX_TOKENS", "1024"))
JARVIS_LLM_FALLBACK = os.getenv("JARVIS_LLM_FALLBACK", "ollama").lower().strip()
JARVIS_LLM_FALLBACK_ENABLED = os.getenv("JARVIS_LLM_FALLBACK_ENABLED", "true").lower() in {"true", "1", "yes"}

LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", os.getenv("OLLAMA_URL", "http://localhost:11434"))
OLLAMA_URL = LOCAL_LLM_URL

LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"))
OLLAMA_MODEL = LOCAL_LLM_MODEL

OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "25"))
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Keyless Open-Meteo current-information provider
WEATHER_GEOCODING_URL = os.getenv(
    "WEATHER_GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1/search"
)
WEATHER_FORECAST_URL = os.getenv(
    "WEATHER_FORECAST_URL", "https://api.open-meteo.com/v1/forecast"
)
WEATHER_TIMEOUT = int(os.getenv("WEATHER_TIMEOUT", "10"))

# Gemini Cloud Fallback
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Phase 3: Agentic Planning & Safety Limits
MAX_PLAN_STEPS = int(os.getenv("MAX_PLAN_STEPS", "6"))
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "6"))
JARVIS_AGENT_ENABLED = os.getenv("JARVIS_AGENT_ENABLED", "true").lower() in {"true", "1", "yes"}
JARVIS_AGENT_MAX_STEPS = int(os.getenv("JARVIS_AGENT_MAX_STEPS", "8"))
JARVIS_AGENT_MAX_RETRIES = int(os.getenv("JARVIS_AGENT_MAX_RETRIES", "1"))
JARVIS_AGENT_MAX_RUNTIME_SECONDS = int(os.getenv("JARVIS_AGENT_MAX_RUNTIME_SECONDS", "300"))
JARVIS_AGENT_OBSERVATION_CHARS = int(os.getenv("JARVIS_AGENT_OBSERVATION_CHARS", "6000"))
MAX_FILE_SEARCH_RESULTS = int(os.getenv("MAX_FILE_SEARCH_RESULTS", "20"))
MAX_WRITE_SIZE_KB = int(os.getenv("MAX_WRITE_SIZE_KB", "256"))
ACTION_CONFIRMATION_TTL_SECONDS = int(os.getenv("ACTION_CONFIRMATION_TTL_SECONDS", "300"))
JARVIS_DRY_RUN = os.getenv("JARVIS_DRY_RUN", "false").lower() in {"true", "1", "yes"}

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Editor discovery
DEFAULT_EDITOR = os.getenv("DEFAULT_EDITOR", "code")

# Phase 4: Voice Configuration
JARVIS_VOICE_ENABLED = os.getenv("JARVIS_VOICE_ENABLED", "true").lower() in {"true", "1", "yes"}
JARVIS_STT_PROVIDER = os.getenv("JARVIS_STT_PROVIDER", "faster_whisper").lower()
JARVIS_STT_MODEL = os.getenv("JARVIS_STT_MODEL", "base").lower()
JARVIS_STT_DEVICE = os.getenv("JARVIS_STT_DEVICE", "cpu").lower()
JARVIS_STT_LANGUAGE = os.getenv("JARVIS_STT_LANGUAGE", "en")
JARVIS_STT_BEAM_SIZE = int(os.getenv("JARVIS_STT_BEAM_SIZE", "5"))
JARVIS_STT_TEMPERATURE = float(os.getenv("JARVIS_STT_TEMPERATURE", "0.0"))
JARVIS_STT_CONDITION_ON_PREVIOUS_TEXT = os.getenv("JARVIS_STT_CONDITION_ON_PREVIOUS_TEXT", "false").lower() in {"true", "1", "yes"}
JARVIS_STT_VAD_FILTER = os.getenv("JARVIS_STT_VAD_FILTER", "true").lower() in {"true", "1", "yes"}
JARVIS_STT_VOCABULARY_CATEGORIES = os.getenv("JARVIS_STT_VOCABULARY_CATEGORIES", "general,programming,projects")
JARVIS_STT_CUSTOM_VOCABULARY = os.getenv("JARVIS_STT_CUSTOM_VOCABULARY", "")
JARVIS_STT_MAX_VOCABULARY_TERMS = int(os.getenv("JARVIS_STT_MAX_VOCABULARY_TERMS", "64"))
JARVIS_STT_MAX_HINT_CHARS = int(os.getenv("JARVIS_STT_MAX_HINT_CHARS", "1200"))
JARVIS_TTS_ENABLED = os.getenv("JARVIS_TTS_ENABLED", "true").lower() in {"true", "1", "yes"}
JARVIS_TTS_RATE = int(os.getenv("JARVIS_TTS_RATE", "180"))
JARVIS_TTS_VOLUME = float(os.getenv("JARVIS_TTS_VOLUME", "1.0"))
JARVIS_SAMPLE_RATE = int(os.getenv("JARVIS_SAMPLE_RATE", "16000"))
JARVIS_WAKE_PROVIDER = os.getenv("JARVIS_WAKE_PROVIDER", "disabled").lower()
JARVIS_WAKE_PHRASES = tuple(p.strip() for p in os.getenv("JARVIS_WAKE_PHRASES", "hey jarvis,okay jarvis,jarvis").split(",") if p.strip())
JARVIS_WAKE_WINDOW_SECONDS = float(os.getenv("JARVIS_WAKE_WINDOW_SECONDS", "2.0"))
JARVIS_FOLLOW_UP_SECONDS = float(os.getenv("JARVIS_FOLLOW_UP_SECONDS", "10.0"))
