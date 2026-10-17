"""Celery: runs slow work (CSV imports, webhooks, reconciliation) in a separate worker process.

The API puts a message on a queue in Redis; a worker picks it up and runs the task.
Celery beat is a scheduler that puts the reconciliation task on the queue every few minutes.
"""

from typing import Any

from celery import Celery, Task
from flask import Flask


def celery_init_app(app: Flask) -> "Celery[Any]":
    """Create the Celery app for this Flask app (pattern from the Flask documentation)."""

    class FlaskTask(Task):  # type: ignore[type-arg]
        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            # Tasks use the database, settings and logging of the Flask app
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        task_always_eager=app.config["CELERY_TASK_ALWAYS_EAGER"],
        task_eager_propagates=True,
        task_ignore_result=True,  # results are stored in our own tables
        # Acknowledge a message only after the task finished: if a worker dies mid-task the
        # message is delivered again. Our tasks are idempotent, so running twice is safe.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_hijack_root_logger=False,  # keep our JSON logging
        broker_connection_retry_on_startup=True,
        timezone="UTC",
        # Modules whose tasks the worker must know about
        imports=("app.services.imports", "app.services.webhooks", "app.services.reconciliation"),
        beat_schedule={
            "reconcile-stock": {
                "task": "stockroom.reconcile_stock",
                "schedule": float(app.config["RECONCILE_INTERVAL_SECONDS"]),
            }
        },
    )
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app
