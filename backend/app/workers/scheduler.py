"""Scheduled jobs without Celery beat, for single-process hosting on a small server.

A free host sleeps when idle, so an hourly timer might never fire. Every job therefore also
runs soon after start-up, and the SLA check catches up on whatever passed during the sleep.
"""

import logging
import threading
import time

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

FIRST_RUN_DELAY = 60.0
TICK_SECONDS = 5.0


def run_due(next_run: dict[str, float], now: float) -> None:
    for name, entry in celery_app.conf.beat_schedule.items():
        if now < next_run[name]:
            continue
        next_run[name] = now + entry["schedule"]
        try:
            celery_app.tasks[entry["task"]].apply(throw=True)
        except Exception:
            logger.exception("Scheduled job failed", extra={"task": name})


def _loop(stop: threading.Event) -> None:
    celery_app.loader.import_default_modules()
    first_run = time.monotonic() + FIRST_RUN_DELAY
    next_run = dict.fromkeys(celery_app.conf.beat_schedule, first_run)
    while not stop.wait(TICK_SECONDS):
        run_due(next_run, time.monotonic())


def start(stop: threading.Event) -> None:
    threading.Thread(target=_loop, args=(stop,), name="scheduler", daemon=True).start()
