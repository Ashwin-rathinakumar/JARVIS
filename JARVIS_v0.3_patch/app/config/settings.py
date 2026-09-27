import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

JARVIS_NAME = "JARVIS"
VERSION = "0.3"

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "jarvis.db")))
DOCUMENTS_DB_PATH = Path(os.getenv("DOCUMENTS_DB_PATH", str(DATA_DIR / "documents.db")))
LOG_DIR = BASE_DIR / "logs"

# Ensure essential directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# LLM Providers (Default to Ollama for local-first execution)
LLM_PROVIDER = os.getenv(
    "LLM_PROVIDER",
    "ollama"
).lower()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen2.5:1.5b"
)

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434"
)

OLLAMA_TIMEOUT = int(
    os.getenv("OLLAMA_TIMEOUT", "25")
)

# Editor discovery
DEFAULT_EDITOR = os.getenv("DEFAULT_EDITOR", "code")