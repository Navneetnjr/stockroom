# Stockroom

Multi-tenant inventory and order management REST API built with Flask, PostgreSQL and Redis.

## Requirements

- Docker Desktop (running)
- Python 3.12+ and [uv](https://docs.astral.sh/uv/) for local development

## Run with Docker

```bash
docker compose up --build
```

This starts three containers:

| Service | What it is            | Address on your laptop   |
|---------|-----------------------|--------------------------|
| api     | The Flask app         | http://localhost:8000    |
| db      | PostgreSQL 16         | localhost:5433           |
| redis   | Redis 7               | localhost:6379           |

Check it is alive: http://localhost:8000/healthz

Stop everything with `Ctrl+C`, or `docker compose down` (add `-v` to also delete the database data).

## Run locally without Docker

```bash
uv sync
uv run flask --app app run --port 8000 --debug
```

## Checks and tests

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy                  # strict type check
uv run pytest                # tests with coverage report
```

Install the Git hook once so these checks run on every commit:

```bash
uv run pre-commit install
```
