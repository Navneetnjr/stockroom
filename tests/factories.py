"""factory_boy factories: one-line recipes for valid test data, saved straight to the database.

    make_product()                      # a product in a brand-new tenant
    make_product(stock=10)              # ... with 10 in stock, recorded in the ledger
    make_product(tenant=shop, sku="X")  # in an existing tenant

Tests call the typed make_* helpers (factory_boy's own type hints are incomplete).
They must be used inside an app context, because they use the app's database session.
"""

from decimal import Decimal
from typing import Any, cast

import factory
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import MovementReason, Product, StockMovement, Tenant, User, UserRole

PASSWORD = "password123"


class BaseFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        abstract = True
        sqlalchemy_session_factory = lambda: db.session  # noqa: E731  (the current app's session)
        sqlalchemy_session_persistence = "commit"


class TenantFactory(BaseFactory):
    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"Shop {n}")


class UserFactory(BaseFactory):
    class Meta:
        model = User
        exclude = ("tenant",)

    tenant = factory.SubFactory(TenantFactory)
    tenant_id = factory.SelfAttribute("tenant.id")
    email = factory.Sequence(lambda n: f"user{n}@shop.test")
    password_hash = factory.LazyFunction(
        lambda: generate_password_hash(PASSWORD, method="pbkdf2:sha256:1000")
    )
    role = UserRole.ADMIN


class ProductFactory(BaseFactory):
    class Meta:
        model = Product
        exclude = ("tenant",)

    tenant = factory.SubFactory(TenantFactory)
    tenant_id = factory.SelfAttribute("tenant.id")
    sku = factory.Sequence(lambda n: f"SKU-{n}")
    name = factory.Faker("word")
    price = Decimal("10.00")

    @factory.post_generation
    def stock(obj: Product, create: bool, extracted: int | None, **kwargs: Any) -> None:  # noqa: N805
        """`stock=10`: set the stock the proper way, with a ledger line."""
        if create and extracted:
            obj.stock_on_hand = extracted
            db.session.add(
                StockMovement(
                    tenant_id=obj.tenant_id,
                    product_id=obj.id,
                    quantity=extracted,
                    reason=MovementReason.INITIAL,
                )
            )
            db.session.commit()


def make_tenant(**fields: Any) -> Tenant:
    return cast(Tenant, TenantFactory(**fields))


def make_user(**fields: Any) -> User:
    return cast(User, UserFactory(**fields))


def make_product(**fields: Any) -> Product:
    return cast(Product, ProductFactory(**fields))
