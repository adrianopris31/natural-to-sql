"""Tests for deterministic write-request detection (the app is read-only)."""

import pytest

from app.core.intent import detect_write_request, mentions_write_words, read_only_refusal


@pytest.mark.parametrize(
    "question",
    [
        "delete user",
        "Delete the user Adrian Opris",
        "please remove all cancelled tasks",
        "Drop the migrations table",
        "Update the project name to Foo",
        "can you delete the client Acme?",
        "Could you please truncate timesheet_item",
        "I want to remove user 5",
        "go ahead and erase old requests",
        "Insert a new client called Acme",
    ],
)
def test_write_requests_detected(question: str) -> None:
    assert detect_write_request(question) is not None


@pytest.mark.parametrize(
    "question",
    [
        "How many users were deleted last month?",
        "Show deleted clients",
        "Which free day requests were updated this week?",
        "Change in hours logged between 2024 and 2025",
        "add up the hours per project",
        "What is the most expensive project?",
        "List users with their removal date",
    ],
)
def test_read_questions_not_refused(question: str) -> None:
    assert detect_write_request(question) is None


def test_mentions_write_words_for_soft_flag() -> None:
    assert mentions_write_words("Which requests were updated or deleted?") == [
        "deleted",
        "updated",
    ]
    assert mentions_write_words("Top projects by hours") == []


def test_refusal_message_is_explicit() -> None:
    msg = read_only_refusal("delete")
    assert msg.startswith("Not performed")
    assert "read-only" in msg and "Nothing was run" in msg
