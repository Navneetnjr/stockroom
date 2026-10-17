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
- Redis is optional for local development: without `REDIS_URL` the cache is skipped and limits
  are counted in memory.

### Background jobs (Celery)

Two extra processes run alongside the API (both started by `docker compose up`):

```bash
celery -A app.worker worker --loglevel=INFO   # runs jobs
celery -A app.worker beat --loglevel=INFO     # schedules the reconciliation job
```

- **CSV import:** `POST /products/imports` (multipart field `file`, columns `sku,name,price[,stock]`)
  returns `202 Accepted` with a job id and a `Location` header. `GET /products/imports/{id}`
  shows the result, with one entry per failed row. Re-importing the same file changes nothing.
- **Webhooks:** set your URL with `PUT /webhooks/config`. Every order status change is POSTed
  as JSON, retried after 2 s, 4 s, 8 s, … and moved to the `webhook_dead_letters` table after
  `WEBHOOK_MAX_ATTEMPTS`. `GET /webhooks/deliveries` shows recent deliveries.
- **Reconciliation:** every `RECONCILE_INTERVAL_SECONDS`, a job checks that each product's
  `stock_on_hand` equals the sum of its stock ledger, and logs an ERROR for any drift.
- Without Redis (local development), jobs run immediately inside the request instead.

**Verifying a webhook** (receiver side):

```python
expected = (
    "sha256="
    + hmac.new(
        secret.encode(), f"{headers['X-Stockroom-Timestamp']}.{raw_body}".encode(), hashlib.sha256
    ).hexdigest()
)
valid = hmac.compare_digest(expected, headers["X-Stockroom-Signature"])
```

Use `X-Stockroom-Event-Id` to ignore duplicates (a retried event keeps its id). The request id
of the API call that caused the event is sent as `X-Request-ID`.

### Safe retries (Idempotency-Key)

Every `POST` that creates something accepts an `Idempotency-Key` header. Sending the same
request again with the same key returns the first response (with `Idempotent-Replayed: true`)
instead of creating a duplicate. Reusing a key for a different request returns 422.

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
