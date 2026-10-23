import pytest

from workflow_engine.engine.conditions import compare


@pytest.mark.parametrize(
    ("left", "operator", "right", "expected"),
    [
        ("640", "gt", 500, True),
        ("1,200.50", "gte", "1200.5", True),
        (12, "lt", "9", False),
        ("2026-10-23T08:00:00Z", "lt", "2026-10-23T09:00:00+00:00", True),
        ("apple", "lt", "banana", True),
        ({"a": 1}, "gt", 1, False),
        ("10", "equals", 10.0, True),
        ("true", "equals", True, True),
        (False, "equals", "no", False),
        (None, "equals", None, True),
        (None, "equals", "", False),
        ([1, 2], "equals", [1, 2], True),
        ("Gold", "not_equals", "gold", True),
        ("priority shipping", "contains", "shipping", True),
        (["a", "b"], "contains", "b", True),
        ([1, 2], "contains", "2", True),
        ({"sku": 1}, "contains", "sku", True),
        ("x", "not_contains", "y", True),
        ("INV-2026-001", "starts_with", "INV-", True),
        ("report.csv", "ends_with", ".csv", True),
        ("west", "in", "east, west", True),
        (3, "in", [1, 2, 3], True),
        ("north", "not_in", ["east", "west"], True),
        ("", "is_empty", None, True),
        ([], "is_not_empty", None, False),
        (0, "is_empty", None, False),
        (0, "exists", None, True),
        (None, "not_exists", None, True),
        ("TRUE", "is_true", None, True),
        ("false", "is_false", None, True),
        (1, "is_true", None, False),
    ],
)
def test_operators(left: object, operator: str, right: object, expected: bool) -> None:
    assert compare(left, operator, right) is expected


def test_unknown_operators_raise() -> None:
    with pytest.raises(ValueError, match="unknown operator"):
        compare(1, "matches", ".*")
