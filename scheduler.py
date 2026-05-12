import json
import logging
import os
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

LOG_FILE = os.path.join(os.path.dirname(__file__), "scheduler_log.json")

# Default: run at 02:00 every day (UTC)
DEFAULT_HOUR   = 2
DEFAULT_MINUTE = 0

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()

logging.getLogger("apscheduler").setLevel(logging.WARNING)


# ─── Log helpers ───────────────────────────────────────────────────────────────

def load_log() -> list[dict]:
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE) as f:
        return json.load(f)


def _append_log(status: str, message: str, post_count: int | None = None) -> None:
    entries = load_log()
    entries.append({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "message": message,
        "post_count": post_count,
    })
    # Keep last 30 entries
    entries = entries[-30:]
    with open(LOG_FILE, "w") as f:
        json.dump(entries, f, indent=2)


# ─── The scheduled job ─────────────────────────────────────────────────────────

def _run_scraper_job() -> None:
    """Runs silently in the background; logs result to scheduler_log.json."""
    _append_log("running", "Auto-refresh started")
    try:
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from scraper import run_scraper
        results = run_scraper()
        _append_log("success", f"Auto-refresh complete", post_count=len(results))
    except Exception as exc:
        _append_log("error", f"Auto-refresh failed: {exc}")


# ─── Scheduler lifecycle ───────────────────────────────────────────────────────

def start_scheduler(hour: int = DEFAULT_HOUR, minute: int = DEFAULT_MINUTE) -> BackgroundScheduler:
    """
    Start (or return existing) background scheduler.
    Safe to call multiple times — only one scheduler is ever created.
    """
    global _scheduler
    with _lock:
        if _scheduler is not None and _scheduler.running:
            return _scheduler

        _scheduler = BackgroundScheduler(timezone="UTC")
        _scheduler.add_job(
            _run_scraper_job,
            trigger=CronTrigger(hour=hour, minute=minute, timezone="UTC"),
            id="daily_scrape",
            replace_existing=True,
            misfire_grace_time=3600,   # allow up to 1 h late
        )
        _scheduler.start()
        return _scheduler


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def get_next_run() -> str | None:
    """Return ISO string of the next scheduled run, or None."""
    if _scheduler is None or not _scheduler.running:
        return None
    job = _scheduler.get_job("daily_scrape")
    if job and job.next_run_time:
        return job.next_run_time.isoformat(timespec="seconds")
    return None


def update_schedule(hour: int, minute: int) -> None:
    """Reschedule the daily job to a new UTC time."""
    if _scheduler is None or not _scheduler.running:
        return
    _scheduler.reschedule_job(
        "daily_scrape",
        trigger=CronTrigger(hour=hour, minute=minute, timezone="UTC"),
    )


def trigger_now() -> None:
    """Run the scraper immediately via the scheduler (non-blocking)."""
    if _scheduler and _scheduler.running:
        _scheduler.add_job(
            _run_scraper_job,
            id="manual_trigger",
            replace_existing=True,
        )
