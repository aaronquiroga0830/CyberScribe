"""
Background scheduler: run the pipeline daily for all active missions.
Designed to run for months (e.g. 5). Start with the UI or as a separate process.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.pipeline import run_all_active_missions

logger = logging.getLogger(__name__)

# Default: run every day at 02:00 local time (configurable via env if needed)
DEFAULT_CRON = {"hour": 2, "minute": 0}


def _scheduled_job() -> None:
    logger.info("Running scheduled pipeline for all active missions at %s", datetime.utcnow().isoformat())
    try:
        results = run_all_active_missions()
        for mid, res in results.items():
            if res:
                logger.info("Mission %s: generated %s", mid, list(res.keys()))
            else:
                logger.warning("Mission %s: no output (skipped or error)", mid)
    except Exception as e:
        logger.exception("Scheduled pipeline failed: %s", e)


def start_scheduler(cron: dict | None = None) -> BackgroundScheduler:
    """
    Start background scheduler that runs pipeline daily.
    cron: e.g. {"hour": 2, "minute": 0} for 02:00. Default 02:00.
    """
    cron = cron or DEFAULT_CRON
    scheduler = BackgroundScheduler()
    scheduler.add_job(_scheduled_job, CronTrigger(**cron), id="daily_pipeline")
    scheduler.start()
    logger.info("Scheduler started; daily run at %s", cron)
    return scheduler
