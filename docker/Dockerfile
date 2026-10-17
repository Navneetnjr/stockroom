FROM python:3.12-slim

# Don't write .pyc files, print logs immediately, and keep the virtualenv outside /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir uv==0.13.0

WORKDIR /app

# Install libraries first: Docker reuses this layer when only our code changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Our code, plus the migrations the API runs at start-up
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY docker/start-api.sh ./docker/start-api.sh

# Don't run as root inside the container
RUN useradd --create-home --uid 1000 stockroom
USER stockroom

EXPOSE 8000
# The API: run migrations, then gunicorn. The worker and beat containers override this.
CMD ["sh", "docker/start-api.sh"]
