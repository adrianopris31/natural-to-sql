"""Unit tests for EXPLAIN plan summarization and the cost gate (pure, no DB)."""

from typing import Any

import pytest

from app.config import Settings
from app.core.explain import explain, summarize_explain

# Captured from MySQL 9.0 (dev DB): indexed join with GROUP BY + ORDER BY
INDEXED_JOIN: dict[str, Any] = {
    "query_block": {
        "select_id": 1,
        "cost_info": {"query_cost": "1101.25"},
        "ordering_operation": {
            "using_temporary_table": True,
            "using_filesort": True,
            "grouping_operation": {
                "nested_loop": [
                    {
                        "table": {
                            "table_name": "u",
                            "access_type": "index",
                            "key": "PRIMARY",
                            "rows_examined_per_scan": 500,
                            "rows_produced_per_join": 500,
                        }
                    },
                    {
                        "table": {
                            "table_name": "o",
                            "access_type": "ref",
                            "key": "idx_orders_user",
                            "rows_examined_per_scan": 6,
                            "rows_produced_per_join": 3000,
                        }
                    },
                ]
            },
        },
    }
}

# Captured from MySQL 9.0: accidental cross join of a 3000-row table with itself
CROSS_JOIN: dict[str, Any] = {
    "query_block": {
        "select_id": 1,
        "cost_info": {"query_cost": "900307.00"},
        "nested_loop": [
            {
                "table": {
                    "table_name": "a",
                    "access_type": "index",
                    "rows_examined_per_scan": 3000,
                    "rows_produced_per_join": 3000,
                }
            },
            {
                "table": {
                    "table_name": "b",
                    "access_type": "index",
                    "rows_examined_per_scan": 3000,
                    "rows_produced_per_join": 9000000,
                }
            },
        ],
    }
}

FULL_SCAN: dict[str, Any] = {
    "query_block": {
        "cost_info": {"query_cost": "25000.00"},
        "table": {
            "table_name": "events",
            "access_type": "ALL",
            "key": None,
            "rows_examined_per_scan": 250000,
            "rows_produced_per_join": 250000,
        },
    }
}


def test_indexed_join_is_allowed_without_warnings() -> None:
    s = summarize_explain(INDEXED_JOIN, Settings())
    assert s.cost == pytest.approx(1101.25)
    assert [t.table for t in s.tables] == ["u", "o"]
    assert s.tables[1].key == "idx_orders_user"
    assert s.estimated_rows == 3000
    assert s.warnings == []  # filesort only warned above EXPLAIN_WARN_ROWS
    assert not s.blocked


def test_cross_join_blocked_by_row_estimate() -> None:
    s = summarize_explain(CROSS_JOIN, Settings(EXPLAIN_MAX_ROWS=1_000_000))
    assert s.estimated_rows == 9_000_000
    assert s.blocked
    assert s.block_reason is not None and "intermediate rows" in s.block_reason


def test_blocked_by_cost() -> None:
    s = summarize_explain(CROSS_JOIN, Settings(EXPLAIN_MAX_COST=1000.0))
    assert s.blocked
    assert s.block_reason is not None and "cost" in s.block_reason


def test_full_scan_warning() -> None:
    s = summarize_explain(FULL_SCAN, Settings(EXPLAIN_WARN_ROWS=100_000))
    assert any("Full table scan on 'events'" in w for w in s.warnings)
    assert not s.blocked


def test_summary_is_json_serializable() -> None:
    import json

    d = summarize_explain(INDEXED_JOIN, Settings()).to_dict()
    assert json.loads(json.dumps(d))["tables"][0]["table"] == "u"


@pytest.mark.asyncio
async def test_explain_rejects_raw_strings() -> None:
    with pytest.raises(TypeError):
        await explain("SELECT 1", engine=None, settings=Settings())  # type: ignore[arg-type]
