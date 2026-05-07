from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import state
from config import RUN_INTERVAL_HOURS
from utils.logger import get_logger

logger = get_logger("scheduler")


def _run_job() -> None:
    logger.info("Scheduler triggered — running analysis pipeline …")
    try:
        from orchestrator import Orchestrator   # late import avoids circular init
        result = Orchestrator().run()
        state.set_result(result)
    except Exception as exc:
        logger.error(f"Scheduled run failed: {exc}", exc_info=True)


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _run_job,
        trigger=IntervalTrigger(hours=RUN_INTERVAL_HOURS),
        id="analysis_pipeline",
        name="Stock Intelligence Pipeline",
        replace_existing=True,
        max_instances=1,
    )
    logger.info(f"Scheduler set: every {RUN_INTERVAL_HOURS}h")
    return scheduler
