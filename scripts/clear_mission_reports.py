"""
One-off script to reset a mission's report content to document templates.
Use to fix crashes caused by corrupted or oversized report data.
Usage (from project root): python scripts/clear_mission_reports.py [mission_id]
Default mission_id is 'test1'.
"""
import sys
from pathlib import Path

# Ensure project root is on path
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from src.mission_service import reset_mission_reports_to_templates

if __name__ == "__main__":
    mission_id = (sys.argv[1] if len(sys.argv) > 1 else "test1").strip()
    reset_mission_reports_to_templates(mission_id)
    print(f"Reset report content to templates for mission: {mission_id}")
