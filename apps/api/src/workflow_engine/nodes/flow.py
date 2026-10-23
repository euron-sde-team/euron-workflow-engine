"""Control flow: if, switch, merge, loop, wait and stop.

These nodes decide routing; the engine (`engine/routing.py`) does the rest. `flow.merge`
receives `{"inputs": [{"node", "data"}, ...]}` from the router, `flow.loop` hands the
router a `LoopStart`, and `flow.wait` suspends its step until the scheduler wakes it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Literal

import anyio
from pydantic import Field, field_validator, model_validator

from workflow_engine.engine.conditions import UNARY, Operator, compare
from workflow_engine.engine.expressions import ExpressionError, compile_expression, evaluate
from workflow_engine.engine.routing import LoopStart
from workflow_engine.nodes.base import (
    NodeConfig,
    NodeContext,
    NodeError,
    NodeResult,
    NodeType,
    templated,
    widget,
)

PORT_NAME = r"^[a-z][a-z0-9_]{0,31}$"
MAX_WAIT = timedelta(days=30)
_UNIT_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}


class Condition(NodeConfig):
    left: Any = None
    operator: Operator = "equals"
    right: Any = None


class IfConfig(NodeConfig):
    combinator: Literal["all", "any"] = "all"
    conditions: list[Condition] = templated(..., widget="conditions", min_length=1, max_length=20)


async def if_node(ctx: NodeContext, config: IfConfig) -> NodeResult:
    results = [compare(c.left, c.operator, c.right) for c in config.conditions]
    passed = all(results) if config.combinator == "all" else any(results)
    ctx.log(
        "info",
        f"{sum(results)} of {len(results)} conditions held: taking the "
        f"{'true' if passed else 'false'} branch",
        results=results,
    )
    return NodeResult(output=ctx.input, ports=("true" if passed else "false",))


class Case(NodeConfig):
    port: str = Field(pattern=PORT_NAME, description="The output this case routes to.")
    operator: Operator = "equals"
    value: Any = None


class SwitchConfig(NodeConfig):
    value: Any = templated(None, description="The value to compare, usually a placeholder.")
    cases: list[Case] = templated(..., widget="cases", min_length=1, max_length=20)
    fallback: bool = Field(default=True, description="Add a 'default' output for no match.")

    @field_validator("cases")
    @classmethod
    def _unique_ports(cls, cases: list[Case]) -> list[Case]:
        ports = [c.port for c in cases]
        if len(set(ports)) != len(ports):
            raise ValueError("Each case needs its own output name.")
        if "default" in ports:
            raise ValueError("'default' is reserved for the fallback output.")
        return cases


def switch_ports(config: Mapping[str, Any]) -> tuple[str, ...]:
    cases = config.get("cases") or []
    ports = [str(c.get("port")) for c in cases if isinstance(c, dict) and c.get("port")]
    if config.get("fallback", True):
        ports.append("default")
    return tuple(dict.fromkeys(ports))


async def switch_node(ctx: NodeContext, config: SwitchConfig) -> NodeResult:
    for case in config.cases:
        if case.operator in UNARY:
            matched = compare(config.value, case.operator)
        else:
            matched = compare(config.value, case.operator, case.value)
        if matched:
            ctx.log("info", f"Matched case '{case.port}'", port=case.port)
            return NodeResult(output=ctx.input, ports=(case.port,))
    if config.fallback:
        ctx.log("info", "No case matched: taking the default output")
        return NodeResult(output=ctx.input, ports=("default",))
    ctx.log("info", "No case matched and there is no default output: nothing runs next")
    return NodeResult(output=ctx.input, ports=())


class MergeConfig(NodeConfig):
    mode: Literal["combine", "append", "merge_objects"] = Field(
        default="combine",
        description=(
            "combine: an object keyed by node id; append: one list of every input; "
            "merge_objects: one object, later inputs win."
        ),
    )


async def merge_node(ctx: NodeContext, config: MergeConfig) -> NodeResult:
    inputs = ctx.input.get("inputs", []) if isinstance(ctx.input, dict) else []
    if config.mode == "combine":
        return NodeResult(output={item["node"]: item.get("data") for item in inputs})
    if config.mode == "append":
        combined: list[Any] = []
        for item in inputs:
            data = item.get("data")
            if isinstance(data, list):
                combined.extend(data)
            else:
                combined.append(data)
        return NodeResult(output=combined)
    merged: dict[str, Any] = {}
    for item in inputs:
        data = item.get("data")
        if isinstance(data, dict):
            merged.update(data)
        else:
            ctx.log("warn", f"Input from '{item['node']}' is not an object and was ignored")
    return NodeResult(output=merged)


class LoopConfig(NodeConfig):
    items: str = widget(
        name="expression",
        min_length=1,
        max_length=2000,
        description="JMESPath that returns the list to loop over, for example input.body.orders",
    )
    batch_size: int = Field(default=1, ge=1, le=1000)
    max_items: int = Field(default=1000, ge=1, le=10_000)

    @field_validator("items")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            compile_expression(value)
        except ExpressionError as exc:
            raise ValueError(str(exc)) from exc
        return value


async def loop_node(ctx: NodeContext, config: LoopConfig) -> NodeResult:
    try:
        items = await anyio.to_thread.run_sync(
            lambda: evaluate(config.items, ctx.expression_context, now=ctx.now)
        )
    except ExpressionError as exc:
        raise NodeError("expression_error", str(exc)) from exc
    if items is None:
        items = []
    if not isinstance(items, list):
        raise NodeError(
            "not_a_list", f"'{config.items}' returned {type(items).__name__}, not a list."
        )
    if len(items) > config.max_items:
        raise NodeError(
            "too_many_items",
            f"{len(items)} items is more than max_items ({config.max_items}).",
        )
    batches = (len(items) + config.batch_size - 1) // config.batch_size
    ctx.log("info", f"{len(items)} items in {batches} batches of up to {config.batch_size}")
    return NodeResult(output=None, loop_start=LoopStart(items, config.batch_size))


class WaitConfig(NodeConfig):
    mode: Literal["delay", "until"] = "delay"
    amount: int = Field(default=5, ge=1, le=100_000)
    unit: Literal["seconds", "minutes", "hours", "days"] = "minutes"
    until: str | None = templated(
        None, max_length=200, description="An ISO 8601 time, usually from a placeholder."
    )

    @model_validator(mode="after")
    def _bounded(self) -> WaitConfig:
        if (
            self.mode == "delay"
            and self.amount * _UNIT_SECONDS[self.unit] > MAX_WAIT.total_seconds()
        ):
            raise ValueError("A wait can last at most 30 days.")
        if self.mode == "until" and not self.until:
            raise ValueError("Give the time to wait until.")
        return self


def _parse_until(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise NodeError("invalid_time", f"'{value}' is not an ISO 8601 time.") from exc
    if moment.tzinfo is None:
        raise NodeError("invalid_time", f"'{value}' has no time zone offset.")
    return moment


async def wait_node(ctx: NodeContext, config: WaitConfig) -> NodeResult:
    if ctx.resumed:
        ctx.log("info", "Wait finished")
        return NodeResult(output=ctx.input)
    if config.mode == "delay":
        until = ctx.now + timedelta(seconds=config.amount * _UNIT_SECONDS[config.unit])
    else:
        until = _parse_until(config.until or "")
        if until - ctx.now > MAX_WAIT:
            raise NodeError("wait_too_long", "A wait can last at most 30 days.")
    if until <= ctx.now:
        ctx.log("info", "The wait time has already passed: continuing")
        return NodeResult(output=ctx.input)
    ctx.log("info", f"Waiting until {until.isoformat(timespec='seconds')}", until=until.isoformat())
    return NodeResult(output=ctx.input, suspend_until=until)


class StopConfig(NodeConfig):
    code: str = Field(default="stopped", pattern=r"^[a-z][a-z0-9_]{0,47}$")
    message: str = templated("Stopped by the workflow.", min_length=1, max_length=1000)


async def stop_node(ctx: NodeContext, config: StopConfig) -> NodeResult:
    raise NodeError(config.code, config.message, details={"stopped_by": ctx.node.id})


NODES = [
    NodeType(
        type="flow.if",
        name="If",
        category="flow",
        description="Route to true or false by comparing values.",
        icon="git-branch",
        config_model=IfConfig,
        run=if_node,
        ports=("true", "false"),
        port_labels={"true": "true", "false": "false"},
        default_timeout_s=10,
    ),
    NodeType(
        type="flow.switch",
        name="Switch",
        category="flow",
        description="Route to the first matching case, or to default.",
        icon="split",
        config_model=SwitchConfig,
        run=switch_node,
        ports=("default",),
        dynamic_ports=switch_ports,
        default_timeout_s=10,
    ),
    NodeType(
        type="flow.merge",
        name="Merge",
        category="flow",
        description="Wait for every branch that runs, then continue once with their outputs.",
        icon="merge",
        config_model=MergeConfig,
        run=merge_node,
        default_timeout_s=10,
    ),
    NodeType(
        type="flow.loop",
        name="Loop over items",
        category="flow",
        description="Split a list into batches and run the loop body once per batch.",
        icon="repeat",
        config_model=LoopConfig,
        run=loop_node,
        inputs=("main", "loop"),
        ports=("batch", "done"),
        port_labels={"batch": "each batch", "done": "done"},
        default_timeout_s=10,
    ),
    NodeType(
        type="flow.wait",
        name="Wait",
        category="flow",
        description="Pause for a while or until a time, without holding a worker.",
        icon="hourglass",
        config_model=WaitConfig,
        run=wait_node,
        default_timeout_s=10,
    ),
    NodeType(
        type="flow.stop",
        name="Stop and fail",
        category="flow",
        description="Fail the execution on purpose with your own error code and message.",
        icon="octagon-x",
        config_model=StopConfig,
        run=stop_node,
        ports=(),
        default_timeout_s=10,
    ),
]
