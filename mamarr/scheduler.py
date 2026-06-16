import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from mamarr.config import settings
from mamarr.favorites import poll_all_series_favorites
from mamarr.watchlist import poll_watchlist

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    try:
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            poll_watchlist,
            "interval",
            hours=settings.watchlist_poll_hours,
            kwargs={"auto_download": True},
            next_run_time=datetime.datetime.now() + datetime.timedelta(minutes=2),
            id="watchlist_poll",
        )
        scheduler.add_job(
            poll_all_series_favorites,
            "interval",
            hours=settings.series_favorites_poll_hours,
            next_run_time=datetime.datetime.now() + datetime.timedelta(minutes=5),
            id="series_favorites_poll",
        )
        scheduler.start()
        _scheduler = scheduler
        return scheduler
    except Exception:
        return None


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
