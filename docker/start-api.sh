#!/bin/sh
# Start the API container: bring the database schema up to date, then serve requests.
# (The worker and beat containers run Celery instead and skip this script.)
set -e

alembic upgrade head

# PORT and WEB_CONCURRENCY are set by most cloud platforms; the defaults suit local use
exec gunicorn --bind "0.0.0.0:${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}" "app:create_app()"
