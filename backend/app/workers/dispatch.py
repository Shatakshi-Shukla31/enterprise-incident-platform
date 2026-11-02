"""Queueing helper. Background work must never make a user-facing request fail."""

import logging

from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def enqueue(task_name: str, *args: object, after_commit_of: Session | None = None) -> None:
    """Queue a task, optionally only once `after_commit_of` commits.

    Deferring to commit stops a worker from reading a row before it is visible and
    stops work being queued for a transaction that later rolls back.
    """
    if after_commit_of is None:
        _send(task_name, args)
        return

    def _on_commit(_session: Session) -> None:
        _send(task_name, args)

    event.listen(after_commit_of, "after_commit", _on_commit, once=True)


def _send(task_name: str, args: tuple) -> None:
    from app.workers.celery_app import celery_app

    full_name = f"app.workers.tasks.{task_name}"
    try:
        if celery_app.conf.task_always_eager:
            # send_task bypasses eager mode, so run the registered task directly.
            celery_app.loader.import_default_modules()
            celery_app.tasks[full_name].apply(args=args, throw=True)
        else:
            celery_app.send_task(full_name, args=args, retry=False)
    except Exception:
        # The scheduled reconciliation tasks pick up anything missed here.
        logger.exception("Could not queue task %s", task_name, extra={"task": task_name})
