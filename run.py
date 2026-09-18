"""
Entrypoint: build index for a mission, then run report agents (RMP + Timeline).
Usage:
  python run.py build <mission_id> [--source PATH]
  python run.py run   <mission_id> [--sequential]
  python run.py all   <mission_id> [--source PATH]
  python run.py clear-users --confirm
"""
import argparse
from pathlib import Path

from config.settings import MISSIONS_DIR
from src import auth_service
from src.index.build import build_mission_index
from src.agents.report_agents import run_all_report_agents


def main():
    parser = argparse.ArgumentParser(description="CyberScribe: index + generate reports")
    sub = parser.add_subparsers(dest="command", required=True)

    # build: ingest mission dir -> vector index
    build_p = sub.add_parser("build", help="Build vector index from mission directory")
    build_p.add_argument("mission_id", help="Mission identifier (e.g. mission_alpha)")
    build_p.add_argument("--source", type=Path, default=None, help=f"Source dir (default: {MISSIONS_DIR}/<mission_id>)")

    # run: generate reports from existing index
    run_p = sub.add_parser("run", help="Run RMP + Timeline agents (requires existing index)")
    run_p.add_argument("mission_id", help="Mission identifier")
    run_p.add_argument("--sequential", action="store_true", help="Run agents sequentially instead of parallel")

    # all: build then run
    all_p = sub.add_parser("all", help="Build index then run all report agents")
    all_p.add_argument("mission_id", help="Mission identifier")
    all_p.add_argument("--source", type=Path, default=None, help="Source dir for build step")
    all_p.add_argument("--sequential", action="store_true", help="Run agents sequentially")

    clear_p = sub.add_parser(
        "clear-users",
        help="Delete all user accounts, sessions, and mission membership",
    )
    clear_p.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Performs the deletion (missions/reports are kept).",
    )

    args = parser.parse_args()

    if args.command == "build":
        source = args.source or (MISSIONS_DIR / args.mission_id)
        build_mission_index(mission_id=args.mission_id, source_path=source)
        print(f"Index built for mission: {args.mission_id}")

    elif args.command == "run":
        run_all_report_agents(
            mission_id=args.mission_id,
            run_parallel=not args.sequential,
        )
        print(f"Reports written to output/{args.mission_id}/")

    elif args.command == "all":
        source = args.source or (MISSIONS_DIR / args.mission_id)
        build_mission_index(mission_id=args.mission_id, source_path=source)
        run_all_report_agents(
            mission_id=args.mission_id,
            run_parallel=not args.sequential,
        )
        print(f"Done. Reports in output/{args.mission_id}/")

    elif args.command == "clear-users":
        if not args.confirm:
            print("Aborted. Re-run with --confirm to delete all users and membership rows.")
            return
        deleted = auth_service.clear_all_users()
        print(f"Removed {deleted} user account(s). Use the app bootstrap to create the first admin again.")


if __name__ == "__main__":
    main()
