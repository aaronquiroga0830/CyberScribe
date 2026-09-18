"""Mark stuck llm_benchmark pipeline jobs failed before a clean benchmark run."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB = PROJECT_ROOT / "data" / "agentic_rag.db"
MISSION = "llm_benchmark"


def main() -> int:
    if not DB.is_file():
        print(f"No database at {DB}")
        return 1
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            """
            UPDATE pipeline_jobs
            SET status = 'failed',
                error_message = 'superseded: benchmark cleanup before canonical run',
                finished_at = ?
            WHERE mission_id = ? AND status = 'running'
            """,
            (now, MISSION),
        )
        conn.commit()
        n = cur.rowcount
    print(f"Marked {n} running job(s) failed for mission {MISSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
