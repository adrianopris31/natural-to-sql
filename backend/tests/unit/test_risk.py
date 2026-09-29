"""Tests for preview risk flags."""

from app.config import Settings
from app.core.explain import ExplainSummary
from app.core.risk import assess_risk


def _explain(**kw: object) -> ExplainSummary:
    base: dict[str, object] = {"cost": 10.0, "estimated_rows": 10}
    base.update(kw)
    return ExplainSummary(**base)  # type: ignore[arg-type]


def test_clean_query_has_no_flags() -> None:
    r = assess_risk(
        safe_sql="SELECT id FROM users LIMIT 5", explain=_explain(), settings=Settings()
    )
    assert r.level == "none" and r.flags == []


def test_blocked_delete_draft_is_high() -> None:
    r = assess_risk(
        safe_sql="SELECT id FROM users WHERE id = 5",
        explain=_explain(),
        settings=Settings(),
        rejected_attempts=[("DELETE FROM users WHERE id = 5", "Forbidden statement type")],
    )
    assert r.level == "high"
    assert r.flags[0].code == "UNSAFE_DRAFT_BLOCKED"
    assert "DELETE" in r.flags[0].message


def test_rejected_select_draft_is_medium() -> None:
    r = assess_risk(
        safe_sql="SELECT id FROM users",
        explain=_explain(),
        settings=Settings(),
        rejected_attempts=[("SELECT * FROM nope", "Table 'nope' is not in the allowed schema")],
    )
    assert r.level == "medium" and r.flags[0].code == "DRAFT_REJECTED"


def test_cartesian_join_flagged() -> None:
    for sql in (
        "SELECT a.id FROM orders a CROSS JOIN orders b",
        "SELECT a.id FROM orders a, orders b",
    ):
        r = assess_risk(safe_sql=sql, explain=_explain(), settings=Settings())
        assert any(f.code == "CARTESIAN_JOIN" for f in r.flags), sql
        assert r.level == "high"


def test_join_with_on_not_flagged() -> None:
    r = assess_risk(
        safe_sql="SELECT u.id FROM users u JOIN orders o ON o.user_id = u.id",
        explain=_explain(),
        settings=Settings(),
    )
    assert not any(f.code == "CARTESIAN_JOIN" for f in r.flags)


def test_explain_block_warning_large_result_wording_and_edit() -> None:
    r = assess_risk(
        safe_sql="SELECT id FROM events",
        explain=_explain(
            estimated_rows=50_000,
            warnings=["Full table scan on 'events' (~50,000 rows)"],
            blocked=True,
            block_reason="Estimated cost too high",
        ),
        settings=Settings(MAX_ROWS=500),
        question_write_words=["deleted"],
        user_edited=True,
        model_set_limit=False,
    )
    codes = [f.code for f in r.flags]
    assert codes == [
        "EXPLAIN_BLOCKED",
        "EXPLAIN_WARNING",
        "LARGE_RESULT",
        "WRITE_WORDING",
        "USER_EDITED",
    ]
    assert r.level == "high"
    assert r.to_dict()["flags"][0]["severity"] == "high"
