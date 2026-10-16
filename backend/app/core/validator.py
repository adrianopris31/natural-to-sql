"""SQL Safety Validator implementing Layers L4 through L10 defense-in-depth security."""

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
    # No default: callers must present the module-private token explicitly.
    _token: object = field(repr=False, compare=False)

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
        if isinstance(node, exp.Anonymous):
            func_name = node.name.upper()
            if func_name in DENIED_FUNCTIONS:
                raise ValidationError(f"Function '{func_name}' is forbidden")
            if func_name not in allowed_anonymous:
                raise ValidationError(f"Unrecognized or forbidden function: '{node.name}'")
        elif isinstance(node, exp.Func):
            # Typed sqlglot function: check its SQL name, not its first argument's name
            func_name = node.sql_name().upper()
            if func_name in DENIED_FUNCTIONS:
                raise ValidationError(f"Function '{func_name}' is forbidden")

    # L8: Table allowlist and schema restriction
    allowed_tables = {t.name.lower() for t in schema.tables}
    deny_tables = {t.lower() for t in settings.DENY_TABLES}
    deny_columns = {c.lower() for c in settings.DENY_COLUMNS}

    cte_ref_ids = _cte_reference_ids(ast)
    target_db = (schema.database or "").lower()
    real_tables: list[str] = []

    for tbl in ast.find_all(exp.Table):
        # Reject system schemas
        if tbl.db and tbl.db.lower() in SYSTEM_SCHEMAS:
            raise ValidationError(f"Access to system schema '{tbl.db}' is forbidden")

        # Only the configured target database may be referenced
        if tbl.catalog or (tbl.db and tbl.db.lower() != target_db):
            raise ValidationError(
                f"Cross-database reference '{tbl.sql(dialect='mysql')}' is not allowed"
            )

        if id(tbl) in cte_ref_ids:
            continue

        tbl_name = tbl.name.lower()
        if tbl_name in deny_tables:
            raise ValidationError(f"Access to table '{tbl.name}' is denied by configuration")

        if tbl_name not in allowed_tables:
            raise ValidationError(f"Table '{tbl.name}' is not in the allowed schema")
        real_tables.append(tbl_name)

    # CTE names must not shadow real or denied tables (avoids ambiguous resolution)
    for cte in ast.find_all(exp.CTE):
        cte_name = cte.alias_or_name.lower()
        if cte_name in allowed_tables or cte_name in deny_tables:
            raise ValidationError(
                f"CTE name '{cte.alias_or_name}' shadows a real table; use a different name"
            )

    # Column denylist check
    if deny_columns:
        for col in ast.find_all(exp.Column):
            if col.name.lower() in deny_columns:
                raise ValidationError(f"Column '{col.name}' is denied by configuration")

    # SELECT * / t.* would expose columns removed by DENY_COLUMNS
    restricted = {t.name.lower() for t in schema.tables if t.has_restricted_columns}
    restricted_in_query = sorted(restricted.intersection(real_tables))
    if restricted_in_query and _has_projection_star(ast):
        raise ValidationError(
            "SELECT * is not allowed on table(s) "
            f"{', '.join(restricted_in_query)} because they contain restricted columns; "
            "list the needed columns explicitly"
        )

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
    return SafeSQL(sql=re_rendered, original_sql=sql, _token=_VALIDATOR_TOKEN)


def _has_projection_star(ast: exp.Expression) -> bool:
    """True if any SELECT projects `*` or `t.*` (COUNT(*) and similar are fine)."""
    for star in ast.find_all(exp.Star):
        parent = star.parent
        if isinstance(parent, exp.Select):
            return True
        if isinstance(parent, exp.Column) and isinstance(parent.parent, exp.Select):
            return True
    return False


def _cte_reference_ids(ast: exp.Expression) -> set[int]:
    """Return ids of exp.Table nodes that refer to a CTE rather than a real table.

    A CTE is visible to later CTEs in the same WITH and to the query body. Its own
    body only sees itself under WITH RECURSIVE; otherwise MySQL resolves a same-named
    reference inside it to the base table, so that reference is *not* a CTE ref.
    """
    cte_refs: set[int] = set()
    for with_node in ast.find_all(exp.With):
        recursive = bool(with_node.args.get("recursive"))
        owner = with_node.parent
        visible: set[str] = set()
        for cte in with_node.expressions:
            name = cte.alias_or_name.lower()
            body_visible = visible | {name} if recursive else set(visible)
            for tbl in cte.this.find_all(exp.Table):
                if not tbl.db and not tbl.catalog and tbl.name.lower() in body_visible:
                    cte_refs.add(id(tbl))
            visible.add(name)
        if owner is None:
            continue
        for tbl in owner.find_all(exp.Table):
            if _is_within(tbl, with_node):
                continue
            if not tbl.db and not tbl.catalog and tbl.name.lower() in visible:
                cte_refs.add(id(tbl))
    return cte_refs


def _is_within(node: exp.Expression, ancestor: exp.Expression) -> bool:
    current = node.parent
    while current is not None:
        if current is ancestor:
            return True
        current = current.parent
    return False
