from datetime import timedelta

import pytest

from tests.unit.node_fakes import NOW, run_node
from workflow_engine.nodes.base import NodeError

ORDER = {
    "id": "SO-1042",
    "total": 640,
    "items": [{"sku": "TENT-2P", "qty": 2}, {"sku": "LAMP", "qty": 1}],
}


async def test_transform_with_jmespath() -> None:
    result, _ = await run_node(
        "core.transform", {"expression": "input.items[?qty > `1`].sku"}, ORDER
    )
    assert result.output == ["TENT-2P"]
    assert result.ports == ("main",)


async def test_transform_with_a_template() -> None:
    config = {
        "mode": "template",
        "template": {"order": "{{ input.id }}", "big": "{{ input.total > `500` }}"},
    }
    result, _ = await run_node("core.transform", config, ORDER)
    assert result.output == {"order": "SO-1042", "big": True}


async def test_transform_reports_expression_errors() -> None:
    with pytest.raises(NodeError) as error:
        await run_node("core.transform", {"expression": "upper(input.total)"}, ORDER)
    assert error.value.code == "expression_error"
    assert not error.value.retryable


async def test_invalid_configs_name_the_field() -> None:
    with pytest.raises(NodeError) as error:
        await run_node("core.transform", {"mode": "jmespath", "expression": "input.["}, ORDER)
    assert error.value.code == "invalid_config"
    with pytest.raises(NodeError) as unknown:
        await run_node("core.transform", {"expression": "input", "surprise": 1}, ORDER)
    assert unknown.value.details["problems"][0]["field"] == "surprise"


async def test_template_errors_are_not_retryable() -> None:
    with pytest.raises(NodeError) as error:
        await run_node(
            "core.set", {"assignments": [{"name": "x", "value": "{{ upper(input.total) }}"}]}, ORDER
        )
    assert error.value.code == "template_error"


async def test_set_variables_passes_input_through() -> None:
    config = {
        "assignments": [
            {"name": "region", "value": "west"},
            {"name": "total", "value": "{{ input.total }}"},
        ]
    }
    result, ctx = await run_node("core.set", config, ORDER)
    assert result.vars == {"region": "west", "total": 640}
    assert result.output == ORDER
    assert ctx.logs[0].message == "Set region, total"
    result, _ = await run_node("core.set", {**config, "keep_input": False}, ORDER)
    assert result.output == {"region": "west", "total": 640}


async def test_if_takes_the_matching_branch() -> None:
    config = {
        "combinator": "all",
        "conditions": [
            {"left": "{{ input.total }}", "operator": "gt", "right": "500"},
            {"left": "{{ input.id }}", "operator": "starts_with", "right": "SO-"},
        ],
    }
    result, ctx = await run_node("flow.if", config, ORDER)
    assert result.ports == ("true",)
    assert "2 of 2" in ctx.logs[0].message
    result, _ = await run_node(
        "flow.if", {**config, "conditions": config["conditions"][:1]}, {"total": 10}
    )
    assert result.ports == ("false",)


async def test_switch_routes_to_the_first_match_or_default() -> None:
    config = {
        "value": "{{ input.tier }}",
        "cases": [
            {"port": "enterprise", "operator": "equals", "value": "enterprise"},
            {"port": "growth", "operator": "in", "value": "growth, scale"},
        ],
    }
    assert (await run_node("flow.switch", config, {"tier": "scale"}))[0].ports == ("growth",)
    assert (await run_node("flow.switch", config, {"tier": "free"}))[0].ports == ("default",)
    no_fallback = {**config, "fallback": False}
    assert (await run_node("flow.switch", no_fallback, {"tier": "free"}))[0].ports == ()


async def test_switch_cases_need_distinct_ports() -> None:
    config = {"value": "x", "cases": [{"port": "a", "value": 1}, {"port": "a", "value": 2}]}
    with pytest.raises(NodeError, match="own output"):
        await run_node("flow.switch", config, {})


async def test_merge_modes() -> None:
    inputs = {"inputs": [{"node": "a", "data": {"x": 1, "y": 1}}, {"node": "b", "data": {"y": 2}}]}
    assert (await run_node("flow.merge", {}, inputs))[0].output == {
        "a": {"x": 1, "y": 1},
        "b": {"y": 2},
    }
    assert (await run_node("flow.merge", {"mode": "merge_objects"}, inputs))[0].output == {
        "x": 1,
        "y": 2,
    }
    lists = {"inputs": [{"node": "a", "data": [1, 2]}, {"node": "b", "data": 3}]}
    assert (await run_node("flow.merge", {"mode": "append"}, lists))[0].output == [1, 2, 3]


async def test_loop_hands_the_items_to_the_router() -> None:
    result, ctx = await run_node("flow.loop", {"items": "input.items", "batch_size": 5}, ORDER)
    assert result.loop_start is not None
    assert result.loop_start.items == ORDER["items"]
    assert result.loop_start.batch_size == 5
    assert "2 items in 1 batches" in ctx.logs[0].message
    with pytest.raises(NodeError) as error:
        await run_node("flow.loop", {"items": "input.id"}, ORDER)
    assert error.value.code == "not_a_list"
    with pytest.raises(NodeError) as too_many:
        await run_node("flow.loop", {"items": "input.items", "max_items": 1}, ORDER)
    assert too_many.value.code == "too_many_items"


async def test_wait_suspends_then_continues() -> None:
    result, _ = await run_node("flow.wait", {"mode": "delay", "amount": 2, "unit": "hours"}, ORDER)
    assert result.suspend_until == NOW + timedelta(hours=2)
    resumed, _ = await run_node("flow.wait", {"amount": 2, "unit": "hours"}, ORDER, resumed=True)
    assert resumed.suspend_until is None
    assert resumed.output == ORDER
    until = {"mode": "until", "until": "{{ input.when }}"}
    past, _ = await run_node("flow.wait", until, {"when": "2026-01-01T00:00:00Z"})
    assert past.suspend_until is None
    with pytest.raises(NodeError) as error:
        await run_node("flow.wait", until, {"when": "next tuesday"})
    assert error.value.code == "invalid_time"
    with pytest.raises(NodeError, match="30 days"):
        await run_node("flow.wait", {"amount": 31, "unit": "days"}, ORDER)


async def test_stop_fails_with_the_configured_error() -> None:
    with pytest.raises(NodeError) as error:
        await run_node(
            "flow.stop", {"code": "out_of_stock", "message": "{{ input.id }} cannot ship"}, ORDER
        )
    assert error.value.code == "out_of_stock"
    assert error.value.message == "SO-1042 cannot ship"
    assert not error.value.retryable


async def test_emit_returns_the_event_for_the_completion_transaction() -> None:
    result, _ = await run_node(
        "event.emit",
        {"event": "order.{{ input.status }}", "payload": "{{ input }}"},
        {"status": "paid"},
    )
    assert result.events == [("order.paid", {"status": "paid"})]
    with pytest.raises(NodeError) as error:
        await run_node("event.emit", {"event": "execution.failed"}, {})
    assert error.value.code == "reserved_event_name"
    with pytest.raises(NodeError) as bad:
        await run_node("event.emit", {"event": "Order Paid"}, {})
    assert bad.value.code == "invalid_event_name"


async def test_triggers_do_not_run() -> None:
    with pytest.raises(NodeError) as error:
        await run_node("trigger.manual", {}, {})
    assert error.value.code == "not_runnable"
