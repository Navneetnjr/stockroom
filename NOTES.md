# Stockroom — design notes

Design decisions, trade-offs, known limits, and what I would improve with more time.

## Architecture

```
client ──HTTP──▶ api (Flask + gunicorn) ──SQL──▶ PostgreSQL
                   │  ▲                             ▲
                   │  └── cache, rate limits ──▶ Redis ◀── queue ──┐
                   └── enqueue job ─────────────▶                  │
                 worker (Celery) ── CSV import, webhook delivery ──┘── SQL ──▶ PostgreSQL
                 beat (Celery)   ── schedules stock reconciliation
                 worker ── signed POST ──▶ tenant's webhook URL
```

One codebase and one image; `api`, `worker` and `beat` differ only in their start command.
Layers: `app/api` (HTTP, thin) → `app/services` (business rules, transactions, Celery tasks)
→ `app/models` (SQLAlchemy). Business rules that need no database (state machine, pricing,
cursor encoding, backoff) are plain functions with unit tests.

## Data model

- **Multi-tenancy:** every tenant-owned table has `tenant_id` (a mixin). The tenant always comes
  from the verified JWT, never from the request body, and every service query filters by it.
  Another tenant's records answer **404, not 403**, so their existence is not revealed.
  Cross-tenant attempts are tested for products, orders, imports, users and idempotency keys.
- **Money:** `Numeric(12, 2)` in the database, `Decimal` in Python, and strings (`"499.00"`) in
  JSON, so no value ever passes through a float.
- **Stock ledger:** `stock_movements` is append-only (an ORM listener rejects updates and
  deletes). The ledger is the source of truth; `products.stock_on_hand` is a denormalised copy,
  updated in the same transaction as every movement, so reads don't have to sum the ledger.
  A `CHECK (stock_on_hand >= 0)` is a last line of defence against overselling.
  The reconciliation job verifies the copy against the ledger.
- **Soft delete** for products (`deleted_at`), so old orders keep their product. SKUs are unique
  per tenant only among non-deleted products (partial unique index).
- **Order lines copy the unit price** at order time, so later price changes don't rewrite history.
- **Emails are unique across tenants**, so login needs only email and password.
- **Migrations:** Alembic only, no `create_all`. Constraint names follow a naming convention so
  migrations can address them. Migration `aed0fa2909db` is the required **data migration**: it
  lowercases existing user emails (stopping with a clear error if that would create duplicates)
  and then adds a CHECK constraint. It has its own test.

## Concurrency and data integrity

- **Pessimistic locking:** placing an order runs `SELECT … FOR UPDATE` on the product rows,
  validates stock, and inserts the order, its lines and its stock movements in **one
  transaction**. Parallel orders for the same product queue on the row lock.
- **Lock ordering:** rows are always locked in ascending id order, so two orders that share
  products cannot deadlock.
- **Why not optimistic locking:** stock is a hot spot (popular products get many concurrent
  orders), so optimistic locking would mostly produce retries. Row locks are simple and
  correct; the cost is that orders for the same product are serialised.
- **Proof:** `tests/test_concurrency.py` fires 10 parallel orders at a product with 5 in stock.
  Exactly 5 succeed, 5 get 409, the final stock is 0 and the ledger sums to 0.
- **Stock is taken when the order is placed** (status `draft`), i.e. a reservation; cancelling
  from `draft` or `confirmed` writes `order_cancelled` movements that return it.

## API decisions

- **Idempotency-Key** (all POSTs that create something, except register/login): the key is
  claimed with an `INSERT` (unique per tenant) **before** the work runs, so two concurrent
  identical requests can't both run. The response of a successful request is stored and
  replayed with `Idempotent-Replayed: true`; the same key with a different body (SHA-256 of
  method, path and body) gives 422. Failed requests release the key, since they changed nothing.
  Keys expire after 24 hours.
- **Cursor pagination** for orders: the cursor is base64 JSON of `(created_at, id)` of the last
  row, and the query is `WHERE (created_at, id) < (…)` in newest-first order. It is O(page size)
  however deep you page, and new orders never shift pages. The cursor is not signed: tampering
  can only move within the caller's own tenant.
- **State machine:** a single `ALLOWED_TRANSITIONS` table; invalid moves are 409 with
  `type: /problems/invalid-transition`. The order row is locked during a transition.
- **Errors:** RFC 9457 problem details for everything, including 404/405, validation errors (422,
  with per-field `errors`), 401 token problems, 429 rate limits and unexpected crashes (500
  without internal details; the traceback goes to the logs).
- **Auth:** JWT (HS256, 8 h) carrying user id, tenant id and role. Passwords are hashed with
  scrypt. Roles: `admin` manages users, products, imports and webhooks; `staff` reads products
  and handles orders.
- **OpenAPI:** generated by flask-smorest from the schemas and docstrings.

## Background jobs

- **Celery with Redis.** `task_acks_late` means a task interrupted by a crashing worker is
  delivered again, so **every job is idempotent**:
  - CSV import upserts by SKU and *sets* stock levels, so re-running a file changes nothing;
    a finished job is skipped.
  - A webhook delivery that is already delivered or dead is skipped.
  - Reconciliation only reads.
- **CSV import:** the file is validated (UTF-8, required columns, max rows) before the 202, and
  stored in the database because the API and the worker run on different machines. Rows are
  committed one by one, so one bad row doesn't block the others; failures are listed per row.
- **Webhooks (outbox style):** the delivery row is written in the same transaction as the order
  change, so an event can't be lost even if the queue is briefly down. Bodies are signed with
  HMAC-SHA256 over `<timestamp>.<body>` (the timestamp lets receivers reject replays). Retries
  use exponential backoff (2 s, 4 s, 8 s, …), scheduled as new tasks with a countdown; after
  `WEBHOOK_MAX_ATTEMPTS` the event is copied to `webhook_dead_letters`. Every attempt of an
  event has the same `X-Stockroom-Event-Id`, so receivers can deduplicate.
- **Reconciliation:** compares `stock_on_hand` with `SUM(stock_movements.quantity)` for every
  product and logs an ERROR per drift. In production, a log-based alert on that message is the
  alerting channel.

## Caching and rate limiting

- **Cache-aside** for product list and detail (TTL 60 s). Each key contains a **per-tenant
  version number**; any committed change to the tenant's products or stock increments it. Old
  entries are never read again. A reader that loaded data just before a write can only store
  it under the old version, so **stale data is never served after a write**. Trade-off: the
  invalidation is coarse; one change invalidates all of that tenant's cached product reads.
- **Rate limiting:** Flask-Limiter with Redis storage, a fixed window, counted per tenant **and**
  per endpoint; login and sign-up are counted per IP to slow down password guessing.
- **Both fail open:** if Redis is down, reads go to the database and requests are not blocked.
  An outage of a cache must not take down the API; `/readyz` still reports Redis as down.

## Observability

- JSON logs on stdout: one line per request with `request_id`, `tenant_id`, `user_id`, method,
  path, status and `latency_ms`. Context variables keep concurrent requests apart.
- **Request id / correlation id:** accepted from `X-Request-ID` if it is short and plain
  (to prevent log injection), otherwise generated; returned on every response, passed to Celery
  tasks as an argument, and sent on webhooks as `X-Request-ID`.
- **Slow query log:** SQLAlchemy cursor events time every query; those over `SLOW_QUERY_MS`
  (200 ms) are logged with SQL and parameters, with password values redacted.

## Indexes

Besides primary keys and foreign-key indexes:

| Index | Why |
|---|---|
| `uq_products_tenant_id_sku_active` — unique `(tenant_id, sku) WHERE deleted_at IS NULL` | Enforces "one active product per SKU per tenant" while letting a deleted product's SKU be reused; also serves SKU lookups during CSV import |
| `ix_orders_tenant_id_created_at_id` — `(tenant_id, created_at, id)` | Serves the order list: `WHERE tenant_id = ? AND (created_at, id) < (?, ?) ORDER BY created_at DESC, id DESC LIMIT n` becomes a backward index range scan with no sort, so every page costs the same however deep you go |
| `uq_idempotency_keys_tenant_id_key` — unique `(tenant_id, key)` | Fast key lookup, and the unique constraint is what makes claiming a key race-safe |
| `uq_webhook_deliveries_event_id` — unique `event_id` | Guarantees each event id is unique, which receivers rely on for deduplication |
| `ix_stock_movements_product_id` | Ledger sums per product (reconciliation) and a product's stock history |
| `ix_order_lines_order_id` | Loading an order's lines (one `IN` query per page via `selectinload`) |

Known redundancy: the single-column `tenant_id` index from the mixin is covered by the
composite indexes on `products`, `orders` and `idempotency_keys`; I would drop those.

## Testing

- 141 tests, ~99.9% coverage (CI requires ≥ 80%). Unit tests for business rules, integration
  tests that call the real API against PostgreSQL, a concurrency test, and a migration test.
- Every test starts from empty tables (`TRUNCATE` after each test); the test database is built
  by running the real migrations, down to base and up again, on every run.
- Seed data uses factory_boy factories (`tests/factories.py`) and API helpers.
- Redis is replaced by fakeredis and Celery runs in eager mode, so the suite needs neither.
- mypy runs in strict mode. flask-smorest ships without type hints, so mypy accepts its
  decorators in `app/api` and `app/errors.py` only; factory_boy gets a similar narrow exception.

## Known limits / what I would do with more time

- **Development environment:** `docker compose up` could not be run on my development laptop
  (no WSL). It is verified in CI instead, where the docker job starts the whole stack and
  checks `/readyz`. Day-to-day development used a local PostgreSQL.
- **Migrations at container start:** fine for a single instance, but several replicas would
  race. I would run them as a release / pre-deploy step instead.
- **Idempotency crash window:** if a process dies after the business commit but before the
  response is stored, the key stays "in progress" until it expires. Storing the response in the
  same transaction as the business write would close that gap. Old keys are not cleaned up yet
  (a periodic job would do it).
- **Webhooks:** deliveries left `pending` because the queue was down are not swept up again
  automatically (an outbox sweeper job would). Tenant URLs are not checked against private
  network addresses (SSRF protection). There is no endpoint to remove a webhook or rotate the
  secret other than setting it again.
- **Rate limiting** uses a fixed window, which allows short bursts at window edges; a sliding
  window would be smoother.
- **Cache invalidation is per tenant, not per product.** It is simple and correct, but busy
  tenants get fewer cache hits.
- **Tenant isolation is enforced in application code.** PostgreSQL row-level security would add
  defence in depth.
- **Auth:** no refresh tokens or token revocation, and a role change takes effect at the next
  login.
- **CSV files are stored in the database**; large files would belong in object storage.
- **Reconciliation alerts only through logs**; I would add a metric or a direct alert.
- **Not done yet:** cloud deployment (waiting on the choice of platform) and branch protection
  on `main` so that a failing CI blocks merging.
