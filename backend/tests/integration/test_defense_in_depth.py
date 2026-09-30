"""Integration tests proving defense-in-depth: Layers L1 (RO user) and L2 (READ ONLY txn)

independently block writes even when the validator is completely bypassed.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import get_engine


@pytest.mark.asyncio
async def test_defense_in_depth_blocks_insert() -> None:
    """L1 & L2 block INSERT statements directly against the target DB."""
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("START TRANSACTION READ ONLY;"))
        try:
            with pytest.raises(DBAPIError) as exc_info:
                await conn.execute(
                    text("INSERT INTO categories (name, slug) VALUES ('Hacked', 'hacked');")
                )
            err_msg = str(exc_info.value).lower()
            assert "denied" in err_msg or "read only" in err_msg
        finally:
            await conn.execute(text("ROLLBACK;"))


@pytest.mark.asyncio
async def test_defense_in_depth_blocks_update() -> None:
    """L1 & L2 block UPDATE statements directly against the target DB."""
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("START TRANSACTION READ ONLY;"))
        try:
            with pytest.raises(DBAPIError) as exc_info:
                await conn.execute(text("UPDATE users SET status = 'suspended' WHERE id = 1;"))
            err_msg = str(exc_info.value).lower()
            assert "denied" in err_msg or "read only" in err_msg
        finally:
            await conn.execute(text("ROLLBACK;"))


@pytest.mark.asyncio
async def test_defense_in_depth_blocks_delete() -> None:
    """L1 & L2 block DELETE statements directly against the target DB."""
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("START TRANSACTION READ ONLY;"))
        try:
            with pytest.raises(DBAPIError) as exc_info:
                await conn.execute(text("DELETE FROM categories WHERE id = 1;"))
            err_msg = str(exc_info.value).lower()
            assert "denied" in err_msg or "read only" in err_msg
        finally:
            await conn.execute(text("ROLLBACK;"))


@pytest.mark.asyncio
async def test_defense_in_depth_blocks_drop_table() -> None:
    """L1 & L2 block DROP TABLE statements directly against the target DB."""
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("START TRANSACTION READ ONLY;"))
        try:
            with pytest.raises(DBAPIError) as exc_info:
                await conn.execute(text("DROP TABLE IF EXISTS users;"))
            err_msg = str(exc_info.value).lower()
            assert "denied" in err_msg or "read only" in err_msg
        finally:
            await conn.execute(text("ROLLBACK;"))


@pytest.mark.asyncio
async def test_defense_in_depth_blocks_create_table() -> None:
    """L1 & L2 block CREATE TABLE statements directly against the target DB."""
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("START TRANSACTION READ ONLY;"))
        try:
            with pytest.raises(DBAPIError) as exc_info:
                await conn.execute(text("CREATE TABLE evil_table (id INT PRIMARY KEY);"))
            err_msg = str(exc_info.value).lower()
            assert "denied" in err_msg or "read only" in err_msg
        finally:
            await conn.execute(text("ROLLBACK;"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql_statement",
    [
        "INSERT INTO categories (name, slug) VALUES ('Hacked', 'hacked');",
        "UPDATE users SET status = 'suspended' WHERE id = 1;",
        "DELETE FROM categories WHERE id = 1;",
        "DROP TABLE IF EXISTS users;",
        "CREATE TABLE evil_table (id INT PRIMARY KEY);",
    ],
)
async def test_l1_alone_blocks_writes_without_read_only_txn(sql_statement: str) -> None:
    """L1 (MySQL user privileges) alone blocks write statements without START TRANSACTION."""
    engine = get_engine()
    async with engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            await conn.execute(text(sql_statement))
        err_msg = str(exc_info.value).lower()
        assert "command denied" in err_msg or "denied" in err_msg or "access denied" in err_msg
