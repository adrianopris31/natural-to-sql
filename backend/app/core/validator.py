"""SQL Safety Validator implementing Layers L4 through L10 per PLAN.md §3."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp

from app.errors import ValidationError

if TYPE_CHECKING:
    from app.config import Settings
    from app.core.schema import SchemaModel

_VALIDATOR_TOKEN = object()

SYSTEM_SCHEMAS = {
    "mysql",
    "information_schema",
    "performance_schema",
    "sys",
}

DENIED_FUNCTIONS = {
    "SLEEP",
    "BENCHMARK",
    "LOAD_FILE",
    "GET_LOCK",
    "RELEASE_LOCK",
    "IS_FREE_LOCK",
    "RELEASE_ALL_LOCKS",
    "MASTER_POS_WAIT",
    "SOURCE_POS_WAIT",
    "SYS_EXEC",
    "SYS_EVAL",
}

# Standard safe functions that sqlglot may parse as exp.Anonymous in MySQL
ALLOWED_ANONYMOUS_FUNCTIONS = {
    "NOW",
    "CURRENT_TIMESTAMP",
    "CURRENT_DATE",
    "CURDATE",
    "CURTIME",
    "CURRENT_TIME",
    "UTC_TIMESTAMP",
    "UTC_DATE",
    "UTC_TIME",
    "LAST_DAY",
    "MAKEDATE",
    "MAKETIME",
    "SEC_TO_TIME",
    "TIME_TO_SEC",
    "DATEDIFF",
    "DATE_ADD",
    "DATE_SUB",
    "VERSION",
    "DATABASE",
    "USER",
    "CURRENT_USER",
}

FORBIDDEN_AST_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
    exp.Set,
    exp.Use,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.LoadData,
    exp.Grant,
    exp.Revoke,
    exp.Lock,
    exp.Into,
    exp.Parameter,
    exp.SessionParameter,
    exp.SetItem,
    exp.PropertyEQ,
    exp.Kill,
)


@dataclass(frozen=True)
class SafeSQL:
    """Safe SQL container produced exclusively by validator.validate."""

    sql: str
    original_sql: str
    _token: object = field(default=_VALIDATOR_TOKEN, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _VALIDATOR_TOKEN:
            raise ValueError(
                "SafeSQL instances can only be constructed by app.core.validator.validate"
            )


def validate(sql: str, schema: SchemaModel, settings: Settings) -> SafeSQL:
    """Validate query against security layers L4-L10 and return SafeSQL."""
    if not sql or not sql.strip():
        raise ValidationError("Empty query provided")

    # Reject null bytes
    if "\x00" in sql:
        raise ValidationError("Null bytes are not allowed in SQL")

    # Reject MySQL executable comments (/*! ... */)
    if re.search(r"/\*!", sql):
        raise ValidationError("Executable comments (/*! ... */) are not allowed")

    # L4: Parse with sqlglot for MySQL dialect
    try:
        parsed_stmts = sqlglot.parse(sql, read="mysql")
    except Exception as exc:
        raise ValidationError(f"SQL syntax error: {exc}") from exc

    # Filter out empty statements
    stmts = [s for s in parsed_stmts if s is not None]
    if len(stmts) != 1:
        raise ValidationError("Query must contain exactly one SQL statement")

    ast = stmts[0]
    if isinstance(ast, exp.Semicolon) or ast is None:
        raise ValidationError("Empty SQL statement")

    # L5: Statement type: root must be Select, Union, Intersect, or Except
    valid_roots = (exp.Select, exp.Union, exp.Intersect, exp.Except)
    if not isinstance(ast, valid_roots):
        raise ValidationError(
            f"Forbidden statement type: expected SELECT, got {type(ast).__name__}"
        )

    # L6: AST walk to reject any forbidden nodes or variables
    for node in ast.walk():
        if isinstance(node, FORBIDDEN_AST_NODES):
            raise ValidationError(f"Forbidden SQL construct: {type(node).__name__}")
        if isinstance(node, exp.Var) and node.name.startswith("@"):
            raise ValidationError(f"Forbidden variable assignment or reference: {node.name}")

    # L7: Function denylist and anonymous function verification
    configured_allowed = {f.upper() for f in settings.ALLOWED_FUNCTIONS}
    allowed_anonymous = ALLOWED_ANONYMOUS_FUNCTIONS | configured_allowed

    for node in ast.walk():
        if isinstance(node, exp.Func):
            func_name = (node.name or type(node).__name__).upper()
            if func_name in DENIED_FUNCTIONS:
                raise ValidationError(f"Function '{func_name}' is forbidden")

        if isinstance(node, exp.Anonymous):
            func_name = node.name.upper()
            if func_name in DENIED_FUNCTIONS:
                raise ValidationError(f"Function '{func_name}' is forbidden")
            if func_name not in allowed_anonymous:
                raise ValidationError(f"Unrecognized or forbidden function: '{node.name}'")

    # L8: Table allowlist and schema restriction
    allowed_tables = {t.name.lower() for t in schema.tables}
    deny_tables = {t.lower() for t in settings.DENY_TABLES}
    deny_columns = {c.lower() for c in settings.DENY_COLUMNS}

    # CTE names are considered valid tables in their query scope
    cte_names = {cte.alias_or_name.lower() for cte in ast.find_all(exp.CTE)}

    for tbl in ast.find_all(exp.Table):
        # Reject system schemas
        if tbl.db and tbl.db.lower() in SYSTEM_SCHEMAS:
            raise ValidationError(f"Access to system schema '{tbl.db}' is forbidden")

        tbl_name = tbl.name.lower()
        if tbl_name in cte_names:
            continue

        if tbl_name in deny_tables:
            raise ValidationError(f"Access to table '{tbl.name}' is denied by configuration")

        if tbl_name not in allowed_tables:
            raise ValidationError(f"Table '{tbl.name}' is not in the allowed schema")

    # Column denylist check
    if deny_columns:
        for col in ast.find_all(exp.Column):
            if col.name.lower() in deny_columns:
                raise ValidationError(f"Column '{col.name}' is denied by configuration")

    # L9: Row cap on outer query (+1 allows executor to detect truncation)
    limit = ast.args.get("limit")
    fetch_cap = settings.MAX_ROWS + 1
    if limit is None:
        ast.set("limit", exp.Limit(expression=exp.Literal.number(fetch_cap)))
    else:
        expr = limit.expression
        if isinstance(expr, exp.Literal) and expr.is_int:
            if int(expr.this) > settings.MAX_ROWS:
                ast.set("limit", exp.Limit(expression=exp.Literal.number(fetch_cap)))
        else:
            ast.set("limit", exp.Limit(expression=exp.Literal.number(fetch_cap)))

    # L10: Strip all comments from AST before re-rendering
    for node in ast.walk():
        node.comments = None

    re_rendered = ast.sql(dialect="mysql")
    return SafeSQL(sql=re_rendered, original_sql=sql)
