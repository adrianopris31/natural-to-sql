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
