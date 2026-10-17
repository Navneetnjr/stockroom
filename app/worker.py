"""Entry point for the background processes:

celery -A app.worker worker --loglevel=INFO     # runs tasks
celery -A app.worker beat --loglevel=INFO       # schedules the reconciliation task
"""

from celery import Celery

from app import create_app

flask_app = create_app()
celery_app: Celery = flask_app.extensions["celery"]
