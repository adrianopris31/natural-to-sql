"""Parametrized security tests for attacks rejection and safe queries."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import Settings
from app.core.schema import ColumnModel, SchemaModel, TableModel
from app.core.validator import SafeSQL, validate
from app.errors import ValidationError

TESTS_DIR = Path(__file__).parent


def _build_test_schema() -> SchemaModel:
    """Build mock schema matching ecommerce tables."""
    return SchemaModel(
        tables=[
            TableModel(
                name="users",
                columns=[
                    ColumnModel(name="id", type="int", is_pk=True),
                    ColumnModel(name="name", type="varchar(100)"),
                    ColumnModel(name="email", type="varchar(150)"),
                    ColumnModel(name="status", type="enum('active','inactive','suspended')"),
                    ColumnModel(name="city", type="varchar(100)"),
                    ColumnModel(name="country", type="varchar(100)"),
                    ColumnModel(name="created_at", type="timestamp"),
                ],
            ),
            TableModel(
                name="categories",
                columns=[
                    ColumnModel(name="id", type="int", is_pk=True),
                    ColumnModel(name="name", type="varchar(100)"),
                    ColumnModel(name="slug", type="varchar(100)"),
                    ColumnModel(name="description", type="varchar(255)"),
                    ColumnModel(name="created_at", type="timestamp"),
                ],
            ),
            TableModel(
                name="products",
                columns=[
                    ColumnModel(name="id", type="int", is_pk=True),
                    ColumnModel(
                        name="category_id",
                        type="int",
                        is_fk=True,
                        fk_target="categories.id",
                    ),
                    ColumnModel(name="name", type="varchar(150)"),
                    ColumnModel(name="sku", type="varchar(50)"),
                    ColumnModel(name="price", type="decimal(10,2)"),
                    ColumnModel(name="cost", type="decimal(10,2)"),
                    ColumnModel(name="stock_quantity", type="int"),
                    ColumnModel(name="status", type="enum('active','discontinued','out_of_stock')"),
                    ColumnModel(name="created_at", type="timestamp"),
                ],
            ),
            TableModel(
                name="orders",
                columns=[
                    ColumnModel(name="id", type="int", is_pk=True),
                    ColumnModel(name="user_id", type="int", is_fk=True, fk_target="users.id"),
                    ColumnModel(name="status", type="enum('completed','shipped','cancelled')"),
                    ColumnModel(name="total_amount", type="decimal(10,2)"),
                    ColumnModel(name="shipping_address", type="varchar(255)"),
                    ColumnModel(name="created_at", type="timestamp"),
                ],
            ),
            TableModel(
                name="order_items",
                columns=[
                    ColumnModel(name="id", type="int", is_pk=True),
                    ColumnModel(name="order_id", type="int", is_fk=True, fk_target="orders.id"),
                    ColumnModel(name="product_id", type="int", is_fk=True, fk_target="products.id"),
                    ColumnModel(name="quantity", type="int"),
                    ColumnModel(name="unit_price", type="decimal(10,2)"),
                    ColumnModel(name="total_price", type="decimal(10,2)"),
                ],
            ),
            TableModel(
                name="payments",
                columns=[
                    ColumnModel(name="id", type="int", is_pk=True),
                    ColumnModel(name="order_id", type="int", is_fk=True, fk_target="orders.id"),
                    ColumnModel(name="payment_method", type="enum('credit_card','paypal')"),
                    ColumnModel(name="status", type="enum('completed','refunded')"),
                    ColumnModel(name="amount", type="decimal(10,2)"),
                    ColumnModel(name="transaction_id", type="varchar(100)"),
                    ColumnModel(name="created_at", type="timestamp"),
                ],
            ),
        ]
    )


def _load_attacks() -> list[dict[str, str]]:
    with (TESTS_DIR / "attacks.yaml").open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return list(data["attacks"])


def _load_safe_queries() -> list[dict[str, str]]:
    with (TESTS_DIR / "safe.yaml").open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return list(data["safe_queries"])


ATTACK_CASES = _load_attacks()
SAFE_CASES = _load_safe_queries()


def test_attacks_corpus_size() -> None:
    """Ensure at least 60 attack cases exist."""
    assert len(ATTACK_CASES) >= 60


def test_safe_corpus_size() -> None:
    """Ensure at least 40 safe cases exist."""
    assert len(SAFE_CASES) >= 40


@pytest.mark.parametrize("case", ATTACK_CASES, ids=lambda c: str(c["name"]))
def test_all_attacks_rejected(case: dict[str, str]) -> None:
    """100% of attack queries must be rejected with ValidationError."""
    schema = _build_test_schema()
    settings = Settings()

    with pytest.raises(ValidationError):
        validate(case["sql"], schema=schema, settings=settings)


@pytest.mark.parametrize("case", SAFE_CASES, ids=lambda c: str(c["name"]))
def test_all_safe_queries_pass(case: dict[str, str]) -> None:
    """100% of safe queries must pass validation, re-render, and enforce LIMIT."""
    schema = _build_test_schema()
    settings = Settings(MAX_ROWS=500)

    safe_sql = validate(case["sql"], schema=schema, settings=settings)
    assert isinstance(safe_sql, SafeSQL)
    assert isinstance(safe_sql.sql, str)
    assert safe_sql.sql.strip().startswith(("SELECT", "WITH"))
    # Re-rendered SQL should not retain comments
    assert "/*" not in safe_sql.sql
    assert "--" not in safe_sql.sql
    assert "#" not in safe_sql.sql
    # Enforces limit
    assert "LIMIT" in safe_sql.sql


def test_safesql_cannot_be_instantiated_directly() -> None:
    """SafeSQL cannot be forged without validator token."""
    with pytest.raises(
        ValueError,
        match=r"can only be constructed by app\.core\.validator\.validate",
    ):
        SafeSQL(sql="SELECT 1", original_sql="SELECT 1", _token=object())


def test_deny_tables_enforced() -> None:
    """Queries on tables listed in DENY_TABLES are rejected."""
    schema = _build_test_schema()
    settings = Settings(DENY_TABLES=["payments"])
    with pytest.raises(ValidationError, match="denied by configuration"):
        validate("SELECT * FROM payments", schema=schema, settings=settings)


def test_deny_columns_enforced() -> None:
    """Queries accessing columns in DENY_COLUMNS are rejected."""
    schema = _build_test_schema()
    settings = Settings(DENY_COLUMNS=["email"])
    with pytest.raises(ValidationError, match="denied by configuration"):
        validate("SELECT id, email FROM users", schema=schema, settings=settings)
