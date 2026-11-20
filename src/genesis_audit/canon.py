"""Canonical JSON output and strict JSON input.

Canonical output makes logs byte-reproducible. Strict input refuses the parts of
Python's JSON dialect that are ambiguous or unbounded: NaN/Infinity literals,
duplicate object keys and deep nesting.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def dumps(value: Any) -> str:
    """Serialize deterministically: sorted keys, no spaces, ASCII only, no NaN."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: Any) -> str:
    """SHA-256 of the canonical serialization."""
    return hashlib.sha256(dumps(value).encode("ascii")).hexdigest()


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite number literal: {name}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _finite_float(text: str) -> float:
    value = float(text)
    if value in (float("inf"), float("-inf")):
        raise ValueError("number too large")
    return value


def is_submission_attempt(text: str) -> bool:
    """True if the text is an object with a top-level member `"action": "submit"`.

    Used only to choose a branch for input that strict parsing has already refused: a broken
    submission is still a submission, and must not be mistaken for a harmless bad action.

    This is a single pass over the characters, with no recursion and no number parsing, so the
    answer cannot depend on the interpreter's recursion limit or integer limits. It looks only at
    string literals directly inside the outermost object: a member name, then its value.
    """
    depth, position, size = 0, 0, len(text)
    name: str | None = None  # the top-level member whose value comes next
    want_name = False
    while position < size:
        character = text[position]
        if character == '"':
            end = position + 1
            while end < size and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            literal = text[position + 1 : end]
            position = end + 1
            if depth == 1 and want_name:
                name, want_name = literal, False
            elif depth == 1 and name == "action" and literal == "submit":
                return True
            continue
        if character in "{[":
            depth += 1
            if depth == 1:
                if character != "{":
                    return False
                want_name = True
        elif character in "}]":
            depth -= 1
        elif character == "," and depth == 1:
            name, want_name = None, True
        elif depth == 0 and character not in " \t\r\n":
            return False  # the top-level value is not an object
        position += 1
    return False


def exceeds_depth(value: Any, limit: int) -> bool:
    """True if lists and objects are nested more than `limit` deep. Iterative, so it cannot overflow the stack."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict | list):
            if depth > limit:
                return True
            stack.extend((child, depth + 1) for child in (item.values() if isinstance(item, dict) else item))
    return False


def loads_strict(text: str, max_depth: int = 32) -> Any:
    """Parse JSON, raising ValueError for anything ambiguous or nested deeper than `max_depth`."""
    try:
        value = json.loads(
            text,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except RecursionError as exc:
        raise ValueError("JSON nesting too deep") from exc
    if exceeds_depth(value, max_depth):
        raise ValueError("JSON nesting too deep")
    return value
