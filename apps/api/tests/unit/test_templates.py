from datetime import UTC, datetime

import pytest

from workflow_engine.engine.templates import (
    TemplateError,
    check,
    parse_template,
    render,
    render_string,
    step_references,
    stringify,
)

CONTEXT = {
    "trigger": {"body": {"order_id": "SO-1042", "items": [{"sku": "TENT-2P", "qty": 2}]}},
    "input": {"customer": {"name": "Maya Patel"}, "total": 129.5, "vip": True, "note": None},
    "steps": {"fetch_customer": {"body": {"tier": "gold"}}},
    "vars": {"region": "west"},
    "env": {"SHOP_API": "http://demo-apis:9131/shop"},
}


def test_interpolation_formats_values() -> None:
    text = "Order {{ trigger.body.order_id }} for {{ upper(input.customer.name) }}"
    assert render_string(text, CONTEXT) == "Order SO-1042 for MAYA PATEL"
    assert render_string("vip={{ input.vip }} note=[{{ input.note }}]", CONTEXT) == (
        "vip=true note=[]"
    )
    assert render_string("total {{ input.total }}", CONTEXT) == "total 129.5"
    assert (
        render_string("{{ env.SHOP_API }}/orders", CONTEXT) == "http://demo-apis:9131/shop/orders"
    )


def test_a_single_placeholder_keeps_the_raw_value() -> None:
    assert render_string("{{ trigger.body.items }}", CONTEXT) == [{"sku": "TENT-2P", "qty": 2}]
    assert render_string("  {{ input.total }} ", CONTEXT) == 129.5
    assert render_string("{{ input.missing }}", CONTEXT) is None


def test_objects_in_text_become_json() -> None:
    assert render_string("items: {{ trigger.body.items }}", CONTEXT) == (
        'items: [{"sku":"TENT-2P","qty":2}]'
    )


def test_multiselect_hashes_with_braces_parse() -> None:
    value = render_string(
        "{{ {id: trigger.body.order_id, tier: steps.fetch_customer.body.tier} }}", CONTEXT
    )
    assert value == {"id": "SO-1042", "tier": "gold"}
    nested = render_string("{{ {a: {b: vars.region}} }}", CONTEXT)
    assert nested == {"a": {"b": "west"}}


def test_quotes_inside_placeholders_may_contain_braces() -> None:
    assert render_string("{{ join('}}', ['a', 'b']) }}", CONTEXT) == "a}}b"


def test_escaped_braces_are_literal() -> None:
    assert render_string("\\{{ not a template }} {{ vars.region }}", CONTEXT) == (
        "{{ not a template }} west"
    )


def test_render_walks_nested_json() -> None:
    config = {
        "url": "{{ env.SHOP_API }}/orders/{{ trigger.body.order_id }}",
        "headers": [{"name": "X-Region", "value": "{{ vars.region }}"}],
        "body": {"qty": "{{ trigger.body.items[0].qty }}", "fixed": 3, "flag": False},
        "{{ vars.region }}_key": "dynamic key",
    }
    rendered = render(config, CONTEXT)
    assert rendered["url"] == "http://demo-apis:9131/shop/orders/SO-1042"
    assert rendered["headers"][0]["value"] == "west"
    assert rendered["body"] == {"qty": 2, "fixed": 3, "flag": False}
    assert rendered["west_key"] == "dynamic key"


def test_syntax_errors_carry_a_position() -> None:
    with pytest.raises(TemplateError) as unclosed:
        parse_template("Hello {{ input.name")
    assert unclosed.value.position == 6
    with pytest.raises(TemplateError, match="empty"):
        parse_template("{{   }}")
    with pytest.raises(TemplateError, match="invalid expression"):
        parse_template("{{ input.[ }}")


def test_evaluation_errors_name_the_placeholder() -> None:
    with pytest.raises(TemplateError, match="upper"):
        render_string("{{ upper(input.total) }}", CONTEXT)


def test_check_reports_paths() -> None:
    problems = check({"url": "{{ ok }}", "headers": [{"value": "{{ broken"}]})
    assert problems == [("headers[0].value", "a '{{' is never closed with '}}'")]


def test_step_references_are_extracted() -> None:
    config = {
        "url": "{{ steps.fetch_customer.body.id }}",
        "body": ["{{ steps . lookup_tier.tier }}", "{{ input.x }}", "steps.not_a_template"],
    }
    assert step_references(config) == {"fetch_customer", "lookup_tier", "not_a_template"}


def test_stringify() -> None:
    assert stringify(3.0) == "3"
    assert stringify(2.5) == "2.5"
    assert stringify(None) == ""
    assert stringify({"a": 1}) == '{"a":1}'
    assert stringify(datetime(2026, 1, 1, tzinfo=UTC).isoformat()) == "2026-01-01T00:00:00+00:00"
