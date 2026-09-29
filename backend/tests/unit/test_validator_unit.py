"""Unit tests for validator corner cases."""

import pytest
import sqlglot.expressions as exp

from app.config import get_settings
from app.core.schema import SchemaModel, TableModel
from app.core.validator import validate
from app.errors import ValidationError


@pytest.fixture
def dummy_schema() -> SchemaModel:
    return SchemaModel(
        tables=[
            TableModel(name="users", columns=[]),
        ]
    )


def test_validator_semicolon_only(dummy_schema: SchemaModel) -> None:
    settings = get_settings()
    with pytest.raises(
        ValidationError,
        match=r"Empty SQL statement|Query must contain exactly one SQL statement",
    ):
        validate(";", schema=dummy_schema, settings=settings)


def test_validator_semicolon_ast_node(
    dummy_schema: SchemaModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()

    def _mock_parse(*_args: object, **_kwargs: object) -> list[exp.Expression]:
        return [exp.Semicolon()]

    monkeypatch.setattr("sqlglot.parse", _mock_parse)
    with pytest.raises(ValidationError, match="Empty SQL statement"):
        validate(";", schema=dummy_schema, settings=settings)


def test_validator_variable_reference(dummy_schema: SchemaModel) -> None:
    settings = get_settings()
    with pytest.raises(ValidationError, match="Forbidden SQL construct: Parameter"):
        validate("SELECT @my_var FROM users", schema=dummy_schema, settings=settings)


def test_validator_var_with_at_symbol(
    dummy_schema: SchemaModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    select_ast = exp.Select().select(exp.Var(this="@session_var")).from_("users")

    def _mock_parse(*_args: object, **_kwargs: object) -> list[exp.Expression]:
        return [select_ast]

    monkeypatch.setattr("sqlglot.parse", _mock_parse)
    with pytest.raises(
        ValidationError,
        match="Forbidden variable assignment or reference: @session_var",
    ):
        validate("SELECT 1 FROM users", schema=dummy_schema, settings=settings)


def test_validator_anonymous_denied_function(dummy_schema: SchemaModel) -> None:
    settings = get_settings()
    with pytest.raises(ValidationError, match="Function 'SLEEP' is forbidden"):
        validate("SELECT SLEEP(1) FROM users", schema=dummy_schema, settings=settings)


def test_validator_non_literal_limit(dummy_schema: SchemaModel) -> None:
    settings = get_settings()
    # Non-literal limit expression
    res = validate("SELECT * FROM users LIMIT (2 + 2)", schema=dummy_schema, settings=settings)
    assert f"LIMIT {settings.MAX_ROWS + 1}" in res.sql
