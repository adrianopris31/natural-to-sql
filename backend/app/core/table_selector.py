"""Table selection module for large database schemas exceeding SCHEMA_FULL_MAX_TABLES."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.core.schema import SchemaModel, TableModel

if TYPE_CHECKING:
    from app.config import Settings

STOPWORDS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "show",
    "the",
    "to",
    "what",
    "which",
    "with",
}


def _tokenize(text: str) -> set[str]:
    """Tokenize string into lowercase alphanumeric words, filtering stopwords."""
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return {w for w in words if len(w) > 1 and w not in STOPWORDS}


def _build_fk_adjacency(schema: SchemaModel) -> dict[str, set[str]]:
    """Build bidirectional foreign key relationship map for all tables."""
    adj: dict[str, set[str]] = {t.name.lower(): set() for t in schema.tables}

    for table in schema.tables:
        t_name = table.name.lower()
        for col in table.columns:
            if col.is_fk and col.fk_target:
                # fk_target is usually "target_table.col"
                target_table = col.fk_target.split(".")[0].lower()
                if target_table in adj:
                    adj[t_name].add(target_table)
                    adj[target_table].add(t_name)

    return adj


def score_table(table: TableModel, query_tokens: set[str]) -> float:
    """Compute relevance score of a table for given query tokens."""
    if not query_tokens:
        return 0.0

    score = 0.0
    t_name = table.name.lower()
    t_tokens = _tokenize(t_name)

    # 1. Exact or plural/singular match on table name
    for token in query_tokens:
        if token == t_name or token in t_tokens:
            score += 10.0
        elif token.rstrip("s") == t_name.rstrip("s"):
            score += 8.0
        elif token in t_name or t_name in token:
            score += 5.0

    # 2. Match column names
    col_tokens: set[str] = set()
    for col in table.columns:
        c_name = col.name.lower()
        col_tokens.update(_tokenize(c_name))
        for token in query_tokens:
            if token == c_name:
                score += 4.0
            elif token.rstrip("s") == c_name.rstrip("s"):
                score += 3.0

    # Column token overlap
    overlap = len(query_tokens.intersection(col_tokens))
    score += overlap * 2.0

    # 3. Match comments
    if table.comment:
        comment_tokens = _tokenize(table.comment)
        score += len(query_tokens.intersection(comment_tokens)) * 1.5

    return score


def select_relevant_tables(
    schema: SchemaModel,
    question: str,
    settings: Settings,
    top_k: int = 8,
) -> SchemaModel:
    """Select the most relevant tables and expand with 1-hop FK neighbors when schema is large."""
    if len(schema.tables) <= settings.SCHEMA_FULL_MAX_TABLES:
        return schema

    query_tokens = _tokenize(question)
    fk_graph = _build_fk_adjacency(schema)

    # Score all tables
    scored_tables: list[tuple[float, TableModel]] = []
    for table in schema.tables:
        s = score_table(table, query_tokens)
        scored_tables.append((s, table))

    # Sort descending by score
    scored_tables.sort(key=lambda x: x[0], reverse=True)

    # Pick top K scoring tables (or all tables with positive score up to top_k)
    selected_names: set[str] = set()
    for _score, table in scored_tables:
        if len(selected_names) >= top_k:
            break
        selected_names.add(table.name.lower())

    # Fallback if no tables scored > 0: pick the first top_k
    if not selected_names:
        for _, table in scored_tables[:top_k]:
            selected_names.add(table.name.lower())

    # 1-hop FK expansion
    expanded_names: set[str] = set(selected_names)
    for name in selected_names:
        neighbors = fk_graph.get(name, set())
        expanded_names.update(neighbors)

    # Filter original schema tables preserving order
    pruned_tables = [t for t in schema.tables if t.name.lower() in expanded_names]

    return SchemaModel(tables=pruned_tables)
