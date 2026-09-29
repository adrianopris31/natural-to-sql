"""Risk flags shown on the preview so potentially dangerous queries stand out before running.

Flags are advisory (the hard stops are the validator and the EXPLAIN gate); `high`
flags make the UI require an explicit "Run anyway" confirmation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import sqlglot
from sqlglot import exp

if TYPE_CHECKING:
    from app.config import Settings
    from app.core.explain import ExplainSummary

Severity = Literal["high", "medium", "info"]
_ORDER: dict[str, int] = {"info": 0, "medium": 1, "high": 2}


@dataclass
class RiskFlag:
    code: str
    severity: Severity
    message: str


@dataclass
class RiskReport:
    level: Literal["none", "info", "medium", "high"] = "none"
    flags: list[RiskFlag] = field(default_factory=list)

    def add(self, code: str, severity: Severity, message: str) -> None:
        self.flags.append(RiskFlag(code=code, severity=severity, message=message))
        if self.level == "none" or _ORDER[severity] > _ORDER[self.level]:
            self.level = severity

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "flags": [asdict(f) for f in self.flags]}


def _statement_kind(raw_sql: str) -> str | None:
    """Best-effort statement type of a rejected draft (e.g. 'DELETE'), for the flag text."""
    try:
        parsed = sqlglot.parse_one(raw_sql, read="mysql")
    except Exception:
        first = raw_sql.strip().split(None, 1)
        return first[0].upper() if first else None
    if parsed is None:
        return None
    return type(parsed).__name__.upper()


def _cartesian_joins(sql: str) -> list[str]:
    """Tables joined without ON/USING (accidental cross joins)."""
    try:
        ast = sqlglot.parse_one(sql, read="mysql")
    except Exception:
        return []
    names: list[str] = []
    for join in ast.find_all(exp.Join):
        if join.args.get("on") is None and not join.args.get("using"):
            target = join.this
            names.append(target.alias_or_name if isinstance(target, exp.Expression) else "?")
    return names


def assess_risk(
    *,
    safe_sql: str,
    explain: ExplainSummary,
    settings: Settings,
    rejected_attempts: list[tuple[str, str]] | None = None,
    question_write_words: list[str] | None = None,
    user_edited: bool = False,
    model_set_limit: bool = True,
) -> RiskReport:
    """Build the risk report for one query.

    rejected_attempts: (raw_sql, reason) for drafts of this query the validator rejected.
    """
    report = RiskReport()

    for raw_sql, reason in rejected_attempts or []:
        kind = _statement_kind(raw_sql)
        if kind and kind not in {"SELECT", "UNION", "INTERSECT", "EXCEPT"}:
            report.add(
                "UNSAFE_DRAFT_BLOCKED",
                "high",
                f"The model first generated a {kind} statement; it was blocked "
                f"({reason}) and rewritten as a read-only query. Check it still matches "
                "what you asked.",
            )
        else:
            report.add(
                "DRAFT_REJECTED",
                "medium",
                f"An earlier draft was rejected ({reason}) and repaired.",
            )

    for table in _cartesian_joins(safe_sql):
        report.add(
            "CARTESIAN_JOIN",
            "high",
            f"'{table}' is joined without an ON condition (cross join): every row is paired "
            "with every row, which can be huge and is usually a mistake.",
        )

    if explain.blocked:
        report.add("EXPLAIN_BLOCKED", "high", explain.block_reason or "Blocked by EXPLAIN")
    for warning in explain.warnings:
        report.add("EXPLAIN_WARNING", "medium", warning)

    if not model_set_limit and explain.estimated_rows > settings.MAX_ROWS:
        report.add(
            "LARGE_RESULT",
            "medium",
            f"May return ~{explain.estimated_rows:,} rows; only the first "
            f"{settings.MAX_ROWS} will be shown.",
        )

    if question_write_words:
        report.add(
            "WRITE_WORDING",
            "medium",
            f"Your question mentions {', '.join(repr(w) for w in question_write_words)}. "
            "This app only reads data; this query will not change anything.",
        )

    if user_edited:
        report.add("USER_EDITED", "info", "You edited this SQL; it was re-validated.")

    return report
