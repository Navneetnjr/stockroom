"""CSV product import: accept the file now (202), process it in the background, and report
which rows failed.

File format (header row required, columns in any order):  sku,name,price[,stock]
- A new SKU creates a product; an existing SKU updates its name and price.
- `stock`, when given, sets the stock level; the difference is written to the stock ledger
  with reason "import". Left empty, the stock is not touched.

Running the same file twice changes nothing the second time, so a retried job is harmless.
"""

import csv
import io
import logging
from datetime import UTC, datetime
from typing import Any

from celery import shared_task
from flask import current_app
from kombu.exceptions import OperationalError
from marshmallow import ValidationError
from sqlalchemy.exc import IntegrityError

from app.cache import invalidate_products
from app.errors import ApiError, NotFoundError
from app.extensions import db
from app.models import ImportJob, ImportStatus, MovementReason, Product
from app.observability import bind_request_id, current_request_id
from app.schemas.products import ImportRowSchema
from app.services.products import apply_stock_change, find_product_by_sku

REQUIRED_COLUMNS = {"sku", "name", "price"}
_log = logging.getLogger("stockroom.imports")


class InvalidImportFileError(ApiError):
    status = 400
    title = "Invalid import file"
    problem_type = "/problems/invalid-import-file"


class WorkersUnavailableError(ApiError):
    status = 503
    title = "Service Unavailable"


def start_import(tenant_id: int, user_id: int, filename: str, content: bytes) -> ImportJob:
    """Check the file's shape, save it as a pending job and return the job."""
    try:
        text = content.decode("utf-8-sig")  # also strips the BOM Excel adds
    except UnicodeDecodeError as error:
        raise InvalidImportFileError("The file must be a UTF-8 encoded CSV file.") from error

    reader = csv.reader(io.StringIO(text))
    header = {column.strip().lower() for column in next(reader, [])}
    missing = REQUIRED_COLUMNS - header
    if missing:
        raise InvalidImportFileError(
            f"Missing columns: {', '.join(sorted(missing))}. Expected: sku,name,price[,stock]."
        )
    row_count = sum(1 for row in reader if any(cell.strip() for cell in row))
    max_rows = int(current_app.config["IMPORT_MAX_ROWS"])
    if row_count > max_rows:
        raise InvalidImportFileError(f"The file has {row_count} rows; the limit is {max_rows}.")

    job = ImportJob(tenant_id=tenant_id, created_by_id=user_id, filename=filename, csv_text=text)
    db.session.add(job)
    db.session.commit()
    return job


def queue_import(job: ImportJob) -> None:
    """Hand the job to a worker."""
    try:
        import_products_task.delay(job.id, request_id=current_request_id())
    except OperationalError as error:
        job.status = ImportStatus.FAILED
        job.errors = [{"row": None, "sku": None, "error": "The job could not be queued."}]
        job.finished_at = datetime.now(UTC)
        db.session.commit()
        raise WorkersUnavailableError(
            "Background workers are unavailable. Please try the import again later."
        ) from error
    db.session.refresh(job)  # without Redis the job has already run; show its real state


def get_import(tenant_id: int, job_id: int) -> ImportJob:
    job = db.session.get(ImportJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise NotFoundError(f"Import job {job_id} was not found.")
    return job


def process_import(job_id: int) -> None:
    """Import every row; a bad row is recorded and skipped, the good rows are saved."""
    job = db.session.get(ImportJob, job_id)
    if job is None or job.status in (ImportStatus.COMPLETED, ImportStatus.FAILED):
        return  # already finished: running the task again changes nothing
    tenant_id, text = job.tenant_id, job.csv_text
    job.status = ImportStatus.PROCESSING
    db.session.commit()

    errors: list[dict[str, Any]] = []
    total = succeeded = 0
    for row_number, raw in enumerate(csv.DictReader(io.StringIO(text)), start=2):  # 1 = header
        total += 1
        row = {key.strip().lower(): (value or "").strip() for key, value in raw.items() if key}
        try:
            _import_row(tenant_id, row)
            db.session.commit()  # each row is saved on its own
            succeeded += 1
        except (ValidationError, IntegrityError) as error:
            db.session.rollback()
            errors.append(
                {"row": row_number, "sku": row.get("sku") or None, "error": _describe(error)}
            )

    job.status = ImportStatus.COMPLETED
    job.total_rows, job.succeeded_rows, job.failed_rows = total, succeeded, len(errors)
    job.errors = errors
    job.finished_at = datetime.now(UTC)
    db.session.commit()
    if succeeded:
        invalidate_products(tenant_id)
    _log.info(
        "import finished",
        extra={"job_id": job_id, "succeeded_rows": succeeded, "failed_rows": len(errors)},
    )


def _import_row(tenant_id: int, row: dict[str, str]) -> None:
    data = ImportRowSchema().load({key: value for key, value in row.items() if value != ""})
    product = find_product_by_sku(tenant_id, data["sku"])
    if product is None:
        product = Product(
            tenant_id=tenant_id, sku=data["sku"], name=data["name"], price=data["price"]
        )
        db.session.add(product)
        db.session.flush()  # get product.id for a stock movement
    else:
        product.name, product.price = data["name"], data["price"]

    target = data.get("stock")
    if target is not None and target != product.stock_on_hand:
        apply_stock_change(product, target - product.stock_on_hand, MovementReason.IMPORT)


def _describe(error: ValidationError | IntegrityError) -> str:
    if isinstance(error, IntegrityError):
        return "Conflicts with another product (for example a duplicate SKU)."
    if not isinstance(error.messages, dict):
        return str(error.messages)
    # e.g. {"price": ["Not a valid number."]} -> "price: Not a valid number."
    return "; ".join(
        f"{field}: {' '.join(problems) if isinstance(problems, list) else problems}"
        for field, problems in error.messages.items()
    )


@shared_task(name="stockroom.import_products")
def import_products_task(job_id: int, request_id: str | None = None) -> None:
    """Background task: process one import job."""
    bind_request_id(request_id)
    process_import(job_id)
