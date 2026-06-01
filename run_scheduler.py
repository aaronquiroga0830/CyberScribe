"""
Run the daily pipeline scheduler in the background (e.g. for 5-month missions).
Start in a separate process or as a scheduled task. UI runs separately via: uvicorn server:app --host 0.0.0.0 --port 8000
"""
import logging
import sys

from src.db.models import init_db
from src.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

if __name__ == "__main__":
    import time
    init_db()
    scheduler = start_scheduler()
    print("Scheduler running. Daily pipeline at 02:00. Ctrl+C to stop.", file=sys.stderr)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        scheduler.shutdown(wait=True)
