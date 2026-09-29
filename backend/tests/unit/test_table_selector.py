"""Unit tests for intelligent table selector and FK graph expansion."""

from app.config import Settings
from app.core.schema import ColumnModel, SchemaModel, TableModel
from app.core.table_selector import _build_fk_adjacency, score_table, select_relevant_tables


def create_mock_schema(table_count: int = 45) -> SchemaModel:
    """Create a mock schema with specified table count and foreign key relationships."""
    tables: list[TableModel] = []

    # Create core e-commerce tables
    users = TableModel(
        name="users",
        comment="Registered accounts",
        columns=[
            ColumnModel(name="id", type="int", is_pk=True),
            ColumnModel(name="name", type="varchar(100)"),
            ColumnModel(name="email", type="varchar(150)"),
        ],
    )
    categories = TableModel(
        name="categories",
        comment="Product categories",
        columns=[
            ColumnModel(name="id", type="int", is_pk=True),
            ColumnModel(name="name", type="varchar(100)"),
        ],
    )
    products = TableModel(
        name="products",
        comment="Catalog items",
        columns=[
            ColumnModel(name="id", type="int", is_pk=True),
            ColumnModel(name="name", type="varchar(150)"),
            ColumnModel(
                name="category_id",
                type="int",
                is_fk=True,
                fk_target="categories.id",
            ),
        ],
    )
    orders = TableModel(
        name="orders",
        comment="Customer purchases",
        columns=[
            ColumnModel(name="id", type="int", is_pk=True),
            ColumnModel(
                name="user_id",
                type="int",
                is_fk=True,
                fk_target="users.id",
            ),
            ColumnModel(name="total_amount", type="decimal(10,2)"),
        ],
    )
    tables.extend([users, categories, products, orders])

    # Fill remaining tables up to table_count
    for i in range(5, table_count + 1):
        tables.append(
            TableModel(
                name=f"log_metric_{i}",
                comment=f"Unrelated logging table {i}",
                columns=[
                    ColumnModel(name="id", type="int", is_pk=True),
                    ColumnModel(name=f"data_{i}", type="varchar(50)"),
                ],
            )
        )

    return SchemaModel(tables=tables)


def test_table_selector_passthrough_when_under_limit() -> None:
    schema = create_mock_schema(table_count=10)
    settings = Settings(SCHEMA_FULL_MAX_TABLES=40)

    selected = select_relevant_tables(schema, "Show all users", settings)
    assert len(selected.tables) == 10
    assert selected == schema


def test_table_scoring() -> None:
    user_tbl = TableModel(
        name="users",
        comment="Active registered accounts",
        columns=[
            ColumnModel(name="id", type="int", is_pk=True),
            ColumnModel(name="email_address", type="varchar(150)"),
        ],
    )

    # Table name matches
    score1 = score_table(user_tbl, {"users"})
    assert score1 >= 10.0

    # Column name matches
    score2 = score_table(user_tbl, {"email_address"})
    assert score2 >= 4.0

    # No match
    score3 = score_table(user_tbl, {"inventory", "warehouses"})
    assert score3 == 0.0


def test_build_fk_adjacency() -> None:
    schema = create_mock_schema(table_count=5)
    adj = _build_fk_adjacency(schema)

    assert "users" in adj["orders"]
    assert "orders" in adj["users"]
    assert "categories" in adj["products"]
    assert "products" in adj["categories"]


def test_table_selector_fk_expansion_when_large() -> None:
    schema = create_mock_schema(table_count=50)
    settings = Settings(SCHEMA_FULL_MAX_TABLES=40)

    # Query mentions orders and total_amount, but does NOT explicitly mention 'users'
    selected = select_relevant_tables(
        schema=schema,
        question="What is the total_amount of all orders?",
        settings=settings,
        top_k=2,
    )

    selected_names = [t.name for t in selected.tables]
    # 'orders' should be selected due to score
    assert "orders" in selected_names
    # 'users' should be included due to 1-hop FK expansion from orders.user_id -> users.id
    assert "users" in selected_names
    # Total selected tables should be much smaller than 50
    assert len(selected.tables) < 15


def test_table_selector_fallback_on_unmatched_query() -> None:
    schema = create_mock_schema(table_count=45)
    settings = Settings(SCHEMA_FULL_MAX_TABLES=40)

    # Query has completely unrelated tokens
    selected = select_relevant_tables(
        schema=schema,
        question="gibberish xyz123 nonexisting",
        settings=settings,
        top_k=5,
    )
    # Falls back to selecting top_k tables + their FK neighbors without failing
    assert len(selected.tables) >= 5
    assert len(selected.tables) <= 45
