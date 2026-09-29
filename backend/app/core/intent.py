"""Deterministic detection of requests to change data (the app is read-only).

Runs before the LLM so obvious write requests ("delete the user X") are refused
clearly instead of being turned into a SELECT or an "are you sure?" question.
"""

from __future__ import annotations

import re

# Unambiguous data-changing verbs: an imperative with one of these is refused outright.
_STRONG_VERBS = (
    r"delete|remove|drop|truncate|insert|update|alter|rename|erase|wipe|purge|destroy|"
    r"grant|revoke|deactivate|ban|reset"
)
# Verbs that are often harmless in questions ("add up", "change in revenue", "set of users").
_SOFT_VERBS = r"add|change|set|modify|edit|create|replace|write|save|assign|move|merge|approve|deny"

_STRONG_PATTERNS = [
    # "delete the user X", "please remove ..."
    re.compile(rf"^\s*(?:please\s+)?(?:{_STRONG_VERBS})\b", re.IGNORECASE),
    # "can you delete ...", "could you please drop ..."
    re.compile(
        rf"\b(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:{_STRONG_VERBS})\b",
        re.IGNORECASE,
    ),
    # "I want to delete ...", "go ahead and remove ..."
    re.compile(
        rf"\b(?:i\s+(?:want|need|would\s+like)\s+to|let'?s|go\s+ahead\s+and|please)\s+"
        rf"(?:{_STRONG_VERBS})\b",
        re.IGNORECASE,
    ),
]
_ANY_WRITE_WORD = re.compile(rf"\b(?:{_STRONG_VERBS}|{_SOFT_VERBS})\w*\b", re.IGNORECASE)


def detect_write_request(question: str) -> str | None:
    """Return the matched phrase if the question clearly asks to change data, else None."""
    for pattern in _STRONG_PATTERNS:
        match = pattern.search(question)
        if match:
            return match.group(0).strip()
    return None


def mentions_write_words(question: str) -> list[str]:
    """Write-ish words anywhere in the question (used only for soft risk flags)."""
    return sorted({m.group(0).lower() for m in _ANY_WRITE_WORD.finditer(question)})


def read_only_refusal(matched: str | None = None) -> str:
    """User-facing explanation for a refused write request."""
    what = f' ("{matched}")' if matched else ""
    return (
        f"Not performed: this assistant is read-only and cannot delete, change or add data{what}. "
        "Nothing was run against the database. You can ask to see the data instead, "
        'for example "Show the user <name>" or "How many users are inactive?".'
    )
