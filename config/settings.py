"""App settings loaded from environment."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Project root (parent of config/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ollama
# For parallel RMP + Timeline generation: set OLLAMA_NUM_PARALLEL=2 (or higher) in the
# environment *before starting* the Ollama server (e.g. Windows: System env vars, then restart Ollama).
# See README "Configuration" section.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma2:2b")
# Max seconds for a single generate call (structured edit or RAG draft). Unset = no limit.
_ollama_gen_to = os.getenv("OLLAMA_GENERATE_TIMEOUT_S", "").strip()
OLLAMA_GENERATE_TIMEOUT_S: float | None = float(_ollama_gen_to) if _ollama_gen_to else None
# Optional: use a second Ollama instance for true parallel (e.g. OLLAMA_BASE_URL_TIMELINE=http://localhost:11435)
OLLAMA_BASE_URL_RMP = os.getenv("OLLAMA_BASE_URL_RMP", "").strip() or None
OLLAMA_BASE_URL_TIMELINE = os.getenv("OLLAMA_BASE_URL_TIMELINE", "").strip() or None


def get_ollama_base_url_for_report(report_type: str) -> str:
    """Return Ollama base URL for this report type (allows separate instance per report for parallelism)."""
    if report_type == "rmp" and OLLAMA_BASE_URL_RMP:
        return OLLAMA_BASE_URL_RMP
    if report_type == "timeline" and OLLAMA_BASE_URL_TIMELINE:
        return OLLAMA_BASE_URL_TIMELINE
    return OLLAMA_BASE_URL

# Embeddings
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "sentence-transformers")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Vector store: "faiss" or "chroma"
VECTOR_STORE_TYPE = os.getenv("VECTOR_STORE_TYPE", "faiss").lower()

# Paths
DATA_DIR = PROJECT_ROOT / os.getenv("DATA_DIR", "data")
MISSIONS_DIR = DATA_DIR / "missions"
INDEX_DIR = DATA_DIR / "indexes"
OUTPUT_DIR = PROJECT_ROOT / os.getenv("OUTPUT_DIR", "output")

# Ensure dirs exist
for d in (MISSIONS_DIR, INDEX_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)
