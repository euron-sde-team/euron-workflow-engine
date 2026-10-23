"""Comparison operators for `flow.if` and `flow.switch`.

Values arrive from templates, so they are often numbers written as text. Comparisons
coerce sensibly: numeric when both sides read as numbers, by instant when both are ISO
dates, otherwise as text. There is deliberately no regular-expression operator: user
patterns are a denial-of-service risk (catastrophic backtracking) on a shared worker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

Operator = Literal[
    "equals",
    "not_equals",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "in",
    "not_in",
    "is_empty",
    "is_not_empty",
    "exists",
    "not_exists",
    "is_true",
    "is_false",
]
UNARY: frozenset[str] = frozenset(
    {"is_empty", "is_not_empty", "exists", "not_exists", "is_true", "is_false"}
)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def _as_instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) < 10 or value[4:5] != "-":
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        lb, rb = _as_bool(left), _as_bool(right)
        return lb is not None and lb == rb
    ln, rn = _as_number(left), _as_number(right)
    if ln is not None and rn is not None:
        return ln == rn
    if isinstance(left, list | dict) or isinstance(right, list | dict):
        return bool(left == right)
    if left is None or right is None:
        return left is None and right is None
    return _text(left) == _text(right)


def _order(left: Any, right: Any) -> int | None:
    """-1, 0 or 1, or None when the values cannot be ordered."""
    ln, rn = _as_number(left), _as_number(right)
    if ln is not None and rn is not None:
        return (ln > rn) - (ln < rn)
    li, ri = _as_instant(left), _as_instant(right)
    if li is not None and ri is not None:
        return (li > ri) - (li < ri)
    if isinstance(left, str) and isinstance(right, str):
        return (left > right) - (left < right)
    return None


def _contains(container: Any, item: Any) -> bool:
    if isinstance(container, str):
        return _text(item) in container
    if isinstance(container, list):
        return any(_equal(element, item) for element in container)
    if isinstance(container, dict):
        return _text(item) in container
    return False


def _members(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(",")]
    return [value]


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str | list | dict) and len(value) == 0)


def compare(left: Any, operator: str, right: Any = None) -> bool:
    match operator:
        case "equals":
            return _equal(left, right)
        case "not_equals":
            return not _equal(left, right)
        case "gt" | "gte" | "lt" | "lte":
            order = _order(left, right)
            if order is None:
                return False
            return {
                "gt": order > 0,
                "gte": order >= 0,
                "lt": order < 0,
                "lte": order <= 0,
            }[operator]
        case "contains":
            return _contains(left, right)
        case "not_contains":
            return not _contains(left, right)
        case "starts_with":
            return _text(left).startswith(_text(right))
        case "ends_with":
            return _text(left).endswith(_text(right))
        case "in":
            return any(_equal(left, member) for member in _members(right))
        case "not_in":
            return not any(_equal(left, member) for member in _members(right))
        case "is_empty":
            return _empty(left)
        case "is_not_empty":
            return not _empty(left)
        case "exists":
            return left is not None
        case "not_exists":
            return left is None
        case "is_true":
            return _as_bool(left) is True
        case "is_false":
            return _as_bool(left) is False
    raise ValueError(f"unknown operator '{operator}'")
