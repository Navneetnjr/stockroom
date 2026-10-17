from typing import Any

from flask import Response, jsonify
from flask_smorest import Blueprint

from app.auth import REQUIRES_LOGIN, auth_required, current_tenant_id
from app.cache import cached_product_data
from app.errors import ProblemSchema
from app.idempotency import ACCEPTS_IDEMPOTENCY_KEY, idempotent
from app.models import Product, StockMovement, UserRole
from app.schemas.products import (
    CreateProductSchema,
    CreateStockMovementSchema,
    ProductSchema,
    StockChangeSchema,
    StockMovementSchema,
    UpdateProductSchema,
)
from app.services import products

blp = Blueprint("products", __name__, url_prefix="/products", description="Products and stock")


def _json(data: Any, from_cache: bool) -> Response:
    """Send already-serialised data; X-Cache tells whether Redis answered (HIT) or not (MISS)."""
    response = jsonify(data)
    response.headers["X-Cache"] = "HIT" if from_cache else "MISS"
    return response


@blp.route("", methods=["GET"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required()
@blp.response(200, ProductSchema(many=True))
def list_products() -> Response:
    """List products

    All products of your shop that are not deleted. Served from the Redis cache when possible.
    """
    tenant_id = current_tenant_id()
    data, from_cache = cached_product_data(
        tenant_id, "list", lambda: ProductSchema(many=True).dump(products.list_products(tenant_id))
    )
    return _json(data, from_cache)


@blp.route("", methods=["POST"])
@blp.doc(**REQUIRES_LOGIN, **ACCEPTS_IDEMPOTENCY_KEY)
@auth_required(UserRole.ADMIN)
@idempotent
@blp.arguments(CreateProductSchema)
@blp.response(201, ProductSchema)
@blp.alt_response(409, schema=ProblemSchema, description="SKU already used in your shop")
def create_product(data: dict[str, Any]) -> Product:
    """Create a product

    `initial_stock` (optional) is recorded as the first line in the stock ledger. **Admin only.**
    """
    return products.create_product(
        current_tenant_id(), data["sku"], data["name"], data["price"], data["initial_stock"]
    )


@blp.route("/<int:product_id>", methods=["GET"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required()
@blp.response(200, ProductSchema)
@blp.alt_response(404, schema=ProblemSchema, description="No such product in your shop")
def get_product(product_id: int) -> Response:
    """Get a product

    Served from the Redis cache when possible.
    """
    tenant_id = current_tenant_id()
    data, from_cache = cached_product_data(
        tenant_id,
        f"product:{product_id}",
        lambda: ProductSchema().dump(products.get_product(tenant_id, product_id)),
    )
    return _json(data, from_cache)


@blp.route("/<int:product_id>", methods=["PATCH"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required(UserRole.ADMIN)
@blp.arguments(UpdateProductSchema)
@blp.response(200, ProductSchema)
@blp.alt_response(404, schema=ProblemSchema, description="No such product in your shop")
@blp.alt_response(409, schema=ProblemSchema, description="SKU already used in your shop")
def update_product(changes: dict[str, Any], product_id: int) -> Product:
    """Update a product

    Change the SKU, name or price. Stock is changed only through stock movements. **Admin only.**
    """
    return products.update_product(current_tenant_id(), product_id, changes)


@blp.route("/<int:product_id>", methods=["DELETE"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required(UserRole.ADMIN)
@blp.response(204)
@blp.alt_response(404, schema=ProblemSchema, description="No such product in your shop")
def delete_product(product_id: int) -> None:
    """Delete a product

    Soft delete: the product disappears from lists, but old orders keep it. **Admin only.**
    """
    products.delete_product(current_tenant_id(), product_id)


@blp.route("/<int:product_id>/stock-movements", methods=["GET"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required()
@blp.response(200, StockMovementSchema(many=True))
@blp.alt_response(404, schema=ProblemSchema, description="No such product in your shop")
def list_stock_movements(product_id: int) -> list[StockMovement]:
    """Stock history of a product

    Every line of the stock ledger for this product, oldest first.
    """
    return products.list_stock_movements(current_tenant_id(), product_id)


@blp.route("/<int:product_id>/stock-movements", methods=["POST"])
@blp.doc(**REQUIRES_LOGIN, **ACCEPTS_IDEMPOTENCY_KEY)
@auth_required(UserRole.ADMIN)
@idempotent
@blp.arguments(CreateStockMovementSchema)
@blp.response(201, StockChangeSchema)
@blp.alt_response(404, schema=ProblemSchema, description="No such product in your shop")
@blp.alt_response(409, schema=ProblemSchema, description="Not enough stock to remove")
def add_stock_movement(data: dict[str, Any], product_id: int) -> dict[str, Any]:
    """Add or remove stock

    Positive quantity adds stock (e.g. a delivery), negative removes it (e.g. damaged items).
    **Admin only.**
    """
    movement, product = products.record_stock_movement(
        current_tenant_id(), product_id, data["quantity"], data["reason"]
    )
    return {"movement": movement, "product": product}
