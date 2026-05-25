"""Smoke tests for backend.app.models.commerce_assets.

Verifies the four ORM classes (Product / ProductImage / ProjectProductLink /
CommerceStoryConfig) added in Wave 2 Task 1 are wired correctly:

- importable from both the dedicated module and the model barrel
- expected ``__tablename__`` values
- expected ``UniqueConstraint`` membership in ``__table_args__``
- expected SQLAlchemy column counts (excluding/including TimestampMixin)
- ``Product.images`` relationship targets ``ProductImage``
- each instance can be constructed with only the required kwargs (no DB)
"""

from __future__ import annotations

from sqlalchemy import UniqueConstraint

from app.models import (
    CommerceStoryConfig as BarrelCommerceStoryConfig,
    Product as BarrelProduct,
    ProductImage as BarrelProductImage,
    ProjectProductLink as BarrelProjectProductLink,
)
from app.models.commerce_assets import (
    CommerceStoryConfig,
    Product,
    ProductImage,
    ProjectProductLink,
)

# TimestampMixin contributes 2 columns: created_at, updated_at.
TIMESTAMP_COLS = 2


def _column_count(model_cls: type) -> int:
    """Return number of SQLAlchemy mapped columns on ``model_cls``."""
    return len(model_cls.__table__.columns)


def _has_unique_constraint(model_cls: type, name: str) -> bool:
    """Return True if ``model_cls.__table_args__`` carries the named UniqueConstraint."""
    args = getattr(model_cls, "__table_args__", ())
    return any(
        isinstance(arg, UniqueConstraint) and arg.name == name for arg in args
    )


def test_barrel_reexports_match_module() -> None:
    """The model barrel ``app.models`` must re-export the same classes."""
    assert BarrelProduct is Product
    assert BarrelProductImage is ProductImage
    assert BarrelProjectProductLink is ProjectProductLink
    assert BarrelCommerceStoryConfig is CommerceStoryConfig


def test_tablenames() -> None:
    """Each model declares the expected ``__tablename__``."""
    assert Product.__tablename__ == "products"
    assert ProductImage.__tablename__ == "product_images"
    assert ProjectProductLink.__tablename__ == "project_product_links"
    assert CommerceStoryConfig.__tablename__ == "commerce_story_configs"


def test_unique_constraints_present() -> None:
    """Each table carries the unique constraint(s) defined in the spec."""
    assert _has_unique_constraint(Product, "uq_products_name")
    assert _has_unique_constraint(
        ProductImage, "uq_product_images_quality_angle"
    )
    assert _has_unique_constraint(
        ProjectProductLink, "uq_project_product_links_scope"
    )


def test_column_counts() -> None:
    """Verify column counts match the contract (incl. TimestampMixin).

    Spec lists N declared columns; total = N + TimestampMixin (2).
    """
    # Product: 16 declared + 2 TimestampMixin = 18 total
    assert _column_count(Product) == 16 + TIMESTAMP_COLS
    # ProductImage: 9 declared + 2 TimestampMixin = 11 total
    assert _column_count(ProductImage) == 9 + TIMESTAMP_COLS
    # ProjectProductLink: 8 declared + 2 TimestampMixin = 10 total
    assert _column_count(ProjectProductLink) == 8 + TIMESTAMP_COLS
    # CommerceStoryConfig: 10 declared + 2 TimestampMixin = 12 total
    assert _column_count(CommerceStoryConfig) == 10 + TIMESTAMP_COLS


def test_product_images_relationship() -> None:
    """``Product.images`` must be a relationship mapped to ``ProductImage``."""
    rel = Product.__mapper__.relationships.get("images")
    assert rel is not None, "Product.images relationship missing"
    assert rel.mapper.class_ is ProductImage


def test_construct_instances_with_required_kwargs() -> None:
    """Each model can be instantiated with only the required kwargs (no DB)."""
    product = Product(id="p_smoke_1", name="Smoke Product")
    assert product.id == "p_smoke_1"
    assert product.name == "Smoke Product"

    image = ProductImage(product_id="p_smoke_1")
    assert image.product_id == "p_smoke_1"

    link = ProjectProductLink(project_id="proj_1", product_id="p_smoke_1")
    assert link.project_id == "proj_1"
    assert link.product_id == "p_smoke_1"

    config = CommerceStoryConfig(project_id="proj_1")
    assert config.project_id == "proj_1"
