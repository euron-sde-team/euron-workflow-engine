from datetime import UTC, datetime

import pytest

from workflow_engine.engine.expressions import (
    ExpressionError,
    compile_expression,
    evaluate,
    truthy,
)

ORDERS = {
    "orders": [
        {"id": "SO-1", "total": 120.5, "region": "west", "email": "a@example.com"},
        {"id": "SO-2", "total": 80, "region": "east", "email": "b@example.com"},
        {"id": "SO-3", "total": 640, "region": "west", "email": "a@example.com"},
    ]
}
NOW = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)


def test_standard_jmespath_projections_and_filters() -> None:
    assert evaluate("orders[?total > `100`].id", ORDERS) == ["SO-1", "SO-3"]
    assert evaluate("sum(orders[].total)", ORDERS) == 840.5
    assert evaluate("{count: length(orders), first: orders[0].id}", ORDERS) == {
        "count": 3,
        "first": "SO-1",
    }


def test_string_functions() -> None:
    data = {"name": "  Maya Patel  ", "csv": "a,b,c"}
    assert evaluate("upper(trim(name))", data) == "MAYA PATEL"
    assert evaluate("lower(name)", data) == "  maya patel  "
    assert evaluate("split(csv, ',')", data) == ["a", "b", "c"]
    assert evaluate("replace(csv, ',', ';')", data) == "a;b;c"
    assert evaluate("url_encode('a b&c')", data) == "a%20b%26c"
    assert evaluate("base64_decode(base64_encode('user:pass'))", data) == "user:pass"
    assert len(evaluate("sha256('x')", data)) == 64


def test_number_functions_accept_numeric_strings() -> None:
    assert evaluate("format_number(`1234.5`, `2`)", {}) == "1,234.50"
    assert evaluate("format_number('1234.5', '0')", {}) == "1,234"
    assert evaluate("round(`2.345`, `2`)", {}) == 2.35
    assert evaluate("round(`2.5`, `0`)", {}) == 2
    with pytest.raises(ExpressionError, match="expected a number"):
        evaluate("round('abc', `1`)", {})
    with pytest.raises(ExpressionError, match="digits"):
        evaluate("round(`1`, `40`)", {})


def test_default_keeps_false_and_zero() -> None:
    data = {"zero": 0, "no": False, "empty": "", "missing": None}
    assert evaluate("default(zero, `5`)", data) == 0
    assert evaluate("default(no, `true`)", data) is False
    assert evaluate("default(empty, 'fallback')", data) == "fallback"
    assert evaluate("default(nothing, 'fallback')", data) == "fallback"


def test_json_and_dates() -> None:
    assert evaluate("to_json(orders[0].id)", ORDERS) == '"SO-1"'
    assert evaluate("from_json('{\"a\": [1, 2]}').a", {}) == [1, 2]
    assert evaluate("now()", {}, now=NOW) == "2026-10-23T08:00:00Z"
    assert evaluate("date_add(now(), `3600`)", {}, now=NOW) == "2026-10-23T09:00:00Z"
    assert evaluate("format_date('2026-10-23T08:00:00Z', '%d %b %Y')", {}) == "23 Oct 2026"
    with pytest.raises(ExpressionError, match="ISO 8601"):
        evaluate("format_date('yesterday', '%Y')", {})
    with pytest.raises(ExpressionError, match="could not parse"):
        evaluate("from_json('{oops')", {})


def test_unique_and_group_by() -> None:
    assert evaluate("unique(orders[].email)", ORDERS) == ["a@example.com", "b@example.com"]
    grouped = evaluate("group_by(orders, &region)", ORDERS)
    assert sorted(grouped) == ["east", "west"]
    assert [o["id"] for o in grouped["west"]] == ["SO-1", "SO-3"]


def test_syntax_errors_are_reported_with_a_position() -> None:
    with pytest.raises(ExpressionError, match="invalid expression"):
        compile_expression("orders[?total >")
    with pytest.raises(ExpressionError, match="empty"):
        compile_expression("   ")
    with pytest.raises(ExpressionError, match="longer than"):
        compile_expression("a" * 5000)


def test_type_errors_become_expression_errors() -> None:
    with pytest.raises(ExpressionError):
        evaluate("upper(orders)", ORDERS)
    with pytest.raises(ExpressionError):
        evaluate("no_such_function(orders)", ORDERS)


def test_truthiness_follows_jmespath_not_python() -> None:
    assert truthy(0)
    assert truthy("0")
    assert truthy([0])
    assert not truthy(None)
    assert not truthy(False)
    assert not truthy("")
    assert not truthy([])
    assert not truthy({})
