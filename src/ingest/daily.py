"""
Daily ingestion entrypoint.

During mission phases, new documents are added daily. Options:
  A) Rebuild the mission index from mission_dir (simple; FAISS).
  B) Incremental add: load only new/changed files, merge into existing index (Chroma supports this natively).

Call this from a scheduler (cron, Task Scheduler) or from the UI "Sync" action.
Run from project root: python -m src.ingest.daily <mission_id>
"""
from pathlib import Path
from datetime import datetime
from typing import Optional

from config.settings import MISSIONS_DIR
from src.index.build import build_mission_index


def run_daily_ingestion(mission_id: str, mission_dir: Optional[Path] = None) -> str:
    """
    Ingest current state of mission dir and (re)build vector index.
    Returns a status message. For FAISS we rebuild; for Chroma you can switch to add_documents only.
    """
    mission_dir = mission_dir or MISSIONS_DIR / mission_id
    if not mission_dir.is_dir():
        return f"Mission dir not found: {mission_dir}"

    build_mission_index(mission_id=mission_id, source_path=mission_dir)
    return f"Daily ingestion completed for mission {mission_id} at {datetime.utcnow().isoformat()}Z"
