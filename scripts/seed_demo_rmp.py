#!/usr/bin/env python3
"""
Load demo RMP content from data/eval/rmp_gold/seed_rmp.html into a product mission
for presentation screenshots. Does NOT modify llm_benchmark.

Usage (from project root, venv active):
  python scripts/seed_demo_rmp.py
  python scripts/seed_demo_rmp.py --mission-id test1
  python scripts/seed_demo_rmp.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SEED_RMP_PATH = PROJECT_ROOT / "data" / "eval" / "rmp_gold" / "seed_rmp.html"
BENCHMARK_MISSION_IDS = frozenset({"llm_benchmark", "llm_benchmark_inc"})


def _default_demo_mission_id() -> str | None:
    from src.mission_service import list_missions

    for m in list_missions():
        mid = (m.get("id") or "").strip()
        if mid in BENCHMARK_MISSION_IDS:
            continue
        src = (m.get("source_path") or "").replace("\\", "/").lower()
        if "sample_mission" in src:
            return mid
    for m in list_missions():
        mid = (m.get("id") or "").strip()
        if mid not in BENCHMARK_MISSION_IDS:
            return mid
    return None


def seed_demo_rmp(mission_id: str, *, dry_run: bool = False) -> Path:
    from src.mission_service import get_mission
    from src.report_service import reject_all_edits, save_user_edit

    if mission_id in BENCHMARK_MISSION_IDS:
        raise SystemExit(
            f"Refusing to seed benchmark mission {mission_id!r}. "
            "Use a product/demo mission (e.g. test1)."
        )

    mission = get_mission(mission_id)
    if not mission:
        raise SystemExit(f"Mission not found: {mission_id}")

    if not SEED_RMP_PATH.is_file():
        raise SystemExit(f"Seed RMP not found: {SEED_RMP_PATH}")

    html = SEED_RMP_PATH.read_text(encoding="utf-8").strip()
    if not html:
        raise SystemExit(f"Seed RMP is empty: {SEED_RMP_PATH}")

    print(f"Mission: {mission_id} ({mission.get('name')})")
    print(f"Source:  {SEED_RMP_PATH} ({len(html)} chars)")

    if dry_run:
        print("Dry run — no database changes.")
        return SEED_RMP_PATH

    try:
        reject_all_edits(mission_id, "rmp")
    except Exception as ex:
        print(f"warning: reject_all_edits: {ex}")

    out = Path(mission["output_path"])
    docx_path = save_user_edit(mission_id, "rmp", html, out)
    print(f"Seeded RMP current_content and wrote {docx_path}")
    print(f"Open: #/mission/{mission_id}/rmp")
    return docx_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo RMP from seed_rmp.html")
    parser.add_argument(
        "--mission-id",
        help="Mission id to seed (default: first non-benchmark mission using sample_mission source)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print target only")
    args = parser.parse_args()

    mid = args.mission_id or _default_demo_mission_id()
    if not mid:
        raise SystemExit("No suitable mission found. Create one or pass --mission-id.")

    seed_demo_rmp(mid, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
