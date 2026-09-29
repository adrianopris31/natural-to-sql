"""Unit tests for schema prompt generation and representation."""

from app.core.schema import ColumnModel, SchemaModel, TableModel


def test_column_to_prompt_str() -> None:
    pk_col = ColumnModel(name="id", type="int", is_pk=True)
    assert pk_col.to_prompt_str() == "id int [PK]"

    fk_col = ColumnModel(
        name="user_id",
        type="int",
        is_fk=True,
        fk_target="users.id",
    )
    assert fk_col.to_prompt_str() == "user_id int [FK→users.id]"

    samples_col = ColumnModel(
        name="status",
        type="enum('active','inactive')",
        sample_values=["active", "inactive"],
    )
    expected_samples = "status enum('active','inactive') [samples: 'active', 'inactive']"
    assert samples_col.to_prompt_str() == expected_samples


def test_table_to_prompt_str() -> None:
    table = TableModel(
        name="categories",
        comment="Product categories",
        columns=[
            ColumnModel(name="id", type="int", is_pk=True),
            ColumnModel(name="name", type="varchar(100)"),
        ],
    )
    expected_table = "categories(id int [PK], name varchar(100)) -- Product categories"
    assert table.to_prompt_str() == expected_table


def test_schema_to_prompt_filtering() -> None:
    users_table = TableModel(
        name="users",
        columns=[
            ColumnModel(name="id", type="int", is_pk=True),
            ColumnModel(name="email", type="varchar(150)"),
        ],
    )
    orders_table = TableModel(
        name="orders",
        columns=[
            ColumnModel(name="id", type="int", is_pk=True),
            ColumnModel(name="user_id", type="int", is_fk=True, fk_target="users.id"),
        ],
    )
    schema = SchemaModel(tables=[users_table, orders_table])

    # All tables
    prompt_all = schema.to_prompt()
    assert "users(id int [PK], email varchar(150))" in prompt_all
    assert "orders(id int [PK], user_id int [FK→users.id])" in prompt_all

    # Filtered tables
    prompt_filtered = schema.to_prompt(tables=["users"])
    assert "users(id int [PK], email varchar(150))" in prompt_filtered
    assert "orders(" not in prompt_filtered
