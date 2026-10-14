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
uv run alembic upgrade head
uv run flask --app app run --port 8000 --debug
```

## API documentation

Generated automatically from the code:

- Interactive docs (Swagger UI): http://localhost:8000/docs
- OpenAPI spec (JSON): http://localhost:8000/openapi.json

Every error response uses the RFC 9457 "problem details" format
(`application/problem+json`) with `type`, `title`, `status`, `detail` and `instance`.

### Trying it on /docs

1. `POST /auth/register` with a shop name, email and password. You get back an `access_token`.
2. Click **Authorize** (top right) and paste the token.
3. Call any protected endpoint, e.g. `GET /auth/me`.

Roles: the user who registers a shop is an **admin**. Admins can add **staff** users with
`POST /users`. Staff cannot manage users.

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
