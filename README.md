# Stockroom

Multi-tenant inventory and order management REST API built with Flask, PostgreSQL, Redis and
Celery. Each tenant (shop) manages its own products, stock and orders. The API prevents
overselling under concurrent load, imports products from CSV in the background, sends signed
webhooks on order events, and ships with CI/CD.

Design decisions, trade-offs and known limits are in **[NOTES.md](NOTES.md)**.

## Features

- Products with soft delete, and an **append-only stock ledger** (current stock is derived)
- Orders placed in one transaction with row locks: **no overselling** (proven by a concurrency test)
- Order state machine: `draft → confirmed → shipped → delivered`, `cancelled` before shipping
- `Idempotency-Key` on POST endpoints, cursor pagination, RFC 9457 error responses
- JWT login with `admin` and `staff` roles; every query scoped to the caller's tenant
- Redis cache for product reads, Redis-backed rate limiting per tenant and endpoint
- Celery jobs: CSV import (202 + job id), signed webhooks with retries and a dead-letter table,
  scheduled stock reconciliation
- JSON logs with request id, tenant, user and latency; slow query log; `/healthz` and `/readyz`
- OpenAPI spec generated from the code at `/openapi.json`, Swagger UI at `/docs`

## Quick start (Docker)

Requires Docker with Compose v2.

```bash
docker compose up --build
```

| Service | What it is                                   | Address on your machine |
|---------|----------------------------------------------|-------------------------|
| api     | Flask app (runs migrations, then gunicorn)   | http://localhost:8000   |
| worker  | Celery worker: CSV imports, webhooks         | –                       |
| beat    | Celery beat: schedules stock reconciliation  | –                       |
| db      | PostgreSQL 16                                | localhost:5433          |
| redis   | Redis 7 (cache, rate limits, job queue)      | localhost:6379          |

Then open http://localhost:8000/docs. Stop with `Ctrl+C` or `docker compose down`
(add `-v` to also delete the database data).

## Local development (without Docker)

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/) and a PostgreSQL 14+ server.

```bash
uv sync                          # install dependencies
cp .env.example .env             # then edit DATABASE_URL, TEST_DATABASE_URL, JWT_SECRET_KEY
uv run alembic upgrade head      # create the tables
uv run flask --app app run --port 8000 --debug
```

Redis is optional locally: without `REDIS_URL` the cache is skipped, rate limits are counted in
memory and background jobs run immediately inside the request. To run real workers, set
`REDIS_URL` and start `celery -A app.worker worker --pool=solo` (`--pool=solo` on Windows).

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes | – | PostgreSQL URL, e.g. `postgresql+psycopg://user:pass@host:5432/stockroom` |
| `JWT_SECRET_KEY` | yes | – | Secret that signs login tokens (long random string) |
| `REDIS_URL` | in production | – | Redis URL for cache, rate limits and the Celery queue |
| `CACHE_TTL_SECONDS` | no | `60` | How long product reads stay cached |
| `RATE_LIMIT_DEFAULT` | no | `300 per minute` | Limit per tenant and endpoint |
| `RATE_LIMIT_AUTH` | no | `10 per minute` | Limit per IP for login and sign-up |
| `CELERY_TASK_ALWAYS_EAGER` | no | `true` without Redis | Run jobs inside the request instead of a worker |
| `WEBHOOK_MAX_ATTEMPTS` | no | `5` | Attempts before a webhook goes to the dead-letter table |
| `WEBHOOK_BACKOFF_SECONDS` | no | `2` | First retry wait; doubles each attempt |
| `WEBHOOK_TIMEOUT_SECONDS` | no | `5` | Timeout of each webhook POST |
| `RECONCILE_INTERVAL_SECONDS` | no | `900` | How often stock reconciliation runs |
| `LOG_LEVEL` | no | `INFO` | Log level |
| `SLOW_QUERY_MS` | no | `200` | Queries slower than this are logged with their SQL |
| `PASSWORD_HASH_METHOD` | no | `scrypt` | werkzeug password hashing method |
| `PORT`, `WEB_CONCURRENCY` | no | `8000`, `2` | Port and gunicorn workers inside the container |
| `TEST_DATABASE_URL` | tests only | – | Separate database for the test suite (it is wiped) |

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
`POST /users`. Staff cannot manage users or products, but can place and manage orders.

### Orders

- `POST /orders` checks stock and creates the order (status `draft`) together with its stock
  movements in one transaction. Product rows are locked (`SELECT ... FOR UPDATE`), so parallel
  orders can never oversell.
- `GET /orders` is paginated with a cursor: pass `next_cursor` from one page as `?cursor=`.
- `POST /orders/{id}/transitions` moves an order: `draft → confirmed → shipped → delivered`,
  or `cancelled` from `draft`/`confirmed` (which puts the stock back).

### Caching and rate limits (Redis)

- `GET /products` and `GET /products/{id}` are cached in Redis for `CACHE_TTL_SECONDS`
  (cache-aside). The `X-Cache` response header says `HIT` or `MISS`. Any change to a tenant's
  products or stock (including orders and cancellations) invalidates that tenant's cache.
- Requests are rate limited per tenant and per endpoint (`RATE_LIMIT_DEFAULT`); login and
  sign-up are limited per IP address (`RATE_LIMIT_AUTH`). Over the limit: `429` with
  `Retry-After`. Every response carries `X-RateLimit-Limit` / `X-RateLimit-Remaining`.

### Background jobs (Celery)

- **CSV import:** `POST /products/imports` (multipart field `file`, columns `sku,name,price[,stock]`)
  returns `202 Accepted` with a job id and a `Location` header. `GET /products/imports/{id}`
  shows the result, with one entry per failed row. Re-importing the same file changes nothing.
- **Webhooks:** set your URL with `PUT /webhooks/config`. Every order status change is POSTed
  as JSON, retried after 2 s, 4 s, 8 s, … and moved to the `webhook_dead_letters` table after
  `WEBHOOK_MAX_ATTEMPTS`. `GET /webhooks/deliveries` shows recent deliveries.
- **Reconciliation:** every `RECONCILE_INTERVAL_SECONDS`, a job checks that each product's
  `stock_on_hand` equals the sum of its stock ledger, and logs an ERROR for any drift.

**Verifying a webhook** (receiver side):

```python
message = f"{headers['X-Stockroom-Timestamp']}.{raw_body}".encode()
expected = "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
valid = hmac.compare_digest(expected, headers["X-Stockroom-Signature"])
```

Use `X-Stockroom-Event-Id` to ignore duplicates (a retried event keeps its id). The request id
of the API call that caused the event is sent as `X-Request-ID`.

### Safe retries (Idempotency-Key)

Every `POST` that creates something accepts an `Idempotency-Key` header. Sending the same
request again with the same key returns the first response (with `Idempotent-Replayed: true`)
instead of creating a duplicate. Reusing a key for a different request returns 422.

## Logs and health

- Logs are JSON lines on stdout. Every request logs `request_id`, `tenant_id`, `user_id`,
  method, path, status and `latency_ms`; queries over `SLOW_QUERY_MS` log their SQL.
- Send `X-Request-ID` to set the request id yourself; it is returned on every response, passed
  to background jobs and sent on webhooks, so one id follows a request everywhere.
- `GET /healthz`: the process is alive. `GET /readyz`: the database (and Redis, if configured)
  can be reached; 503 otherwise.

## Tests and code quality

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy                  # strict type check
uv run pytest                # unit + integration tests with coverage (needs TEST_DATABASE_URL)
uv run pre-commit install    # once: run ruff and mypy on every commit
```

Integration tests call the real API against a real PostgreSQL. Redis and Celery are replaced by
fakeredis and eager mode, so the suite needs no Redis.

## CI/CD

GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs on every push and
pull request:

1. **checks:** ruff, formatting, mypy (strict), and the tests against a PostgreSQL service with
   at least 80% coverage. Test results and a coverage summary are published on the PR.
2. **docker:** runs `docker compose up --wait`, checks `/readyz`, then builds the image. On
   `main` the image is pushed to `ghcr.io/navneetnjr/stockroom` (tags: commit sha and `latest`).

## Deployment

The app is one container image with three processes, all configured by the environment
variables above:

| Process | Command |
|---|---|
| Web | default command (`sh docker/start-api.sh`: migrations, then gunicorn on `$PORT`) |
| Worker | `celery -A app.worker worker --loglevel=INFO` |
| Scheduler | `celery -A app.worker beat --loglevel=INFO --schedule /tmp/celerybeat-schedule` |

It needs a managed PostgreSQL 14+ and Redis. Use `/healthz` as the platform's health check.
Platform-specific config and the live URL will be added once the hosting platform is chosen.

## Project layout

```
app/            Flask application
  api/          HTTP endpoints (flask-smorest blueprints)
  schemas/      request/response schemas (marshmallow)
  services/     business logic and Celery tasks
  models/       SQLAlchemy models
migrations/     Alembic migrations
tests/          pytest suite (unit, integration, concurrency)
docker/         Dockerfile and container start script
.github/        CI workflow
```
