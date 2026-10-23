"""`core.transform` and `core.set`: reshape data and keep values for later nodes."""

from __future__ import annotations

from typing import Any, Literal

import anyio
from pydantic import Field, model_validator

from workflow_engine.engine.expressions import ExpressionError, compile_expression, evaluate
from workflow_engine.nodes.base import (
    NodeConfig,
    NodeContext,
    NodeError,
    NodeResult,
    NodeType,
    templated,
    widget,
)

VARIABLE_NAME = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"


class TransformConfig(NodeConfig):
    mode: Literal["jmespath", "template"] = "jmespath"
    expression: str | None = widget(
        None,
        name="expression",
        max_length=4000,
        description="JMESPath over {trigger, input, steps, vars, env, execution}.",
    )
    template: Any = templated(
        None,
        widget="json",
        description="JSON whose strings may contain {{ }} placeholders.",
    )

    @model_validator(mode="after")
    def _one_source(self) -> TransformConfig:
        if self.mode == "jmespath":
            if not self.expression or not self.expression.strip():
                raise ValueError("Write a JMESPath expression, for example input.items[?qty > `0`]")
            try:
                compile_expression(self.expression)
            except ExpressionError as exc:
                raise ValueError(str(exc)) from exc
        elif self.template is None:
            raise ValueError("Write the JSON template to produce.")
        return self


async def transform(ctx: NodeContext, config: TransformConfig) -> NodeResult:
    if config.mode == "template":
        return NodeResult(output=config.template)
    expression = config.expression or ""
    try:
        # JMESPath is synchronous CPU work: keep it off the event loop so heartbeats flow.
        result = await anyio.to_thread.run_sync(
            lambda: evaluate(expression, ctx.expression_context, now=ctx.now)
        )
    except ExpressionError as exc:
        raise NodeError("expression_error", str(exc)) from exc
    return NodeResult(output=result)


class Assignment(NodeConfig):
    name: str = Field(pattern=VARIABLE_NAME)
    value: Any = None


class SetConfig(NodeConfig):
    assignments: list[Assignment] = templated(
        ..., widget="assignments", min_length=1, max_length=50
    )
    keep_input: bool = Field(
        default=True, description="Pass the input on unchanged; otherwise output the variables."
    )


async def set_variables(ctx: NodeContext, config: SetConfig) -> NodeResult:
    values = {a.name: a.value for a in config.assignments}
    ctx.log("info", f"Set {', '.join(values)}", names=list(values))
    return NodeResult(output=ctx.input if config.keep_input else values, vars=values)


NODES = [
    NodeType(
        type="core.transform",
        name="Transform",
        category="core",
        description="Reshape data with JMESPath or a JSON template. No code runs.",
        icon="shuffle",
        config_model=TransformConfig,
        run=transform,
        default_timeout_s=10,
    ),
    NodeType(
        type="core.set",
        name="Set variables",
        category="core",
        description="Store values as execution variables, readable later as vars.<name>.",
        icon="variable",
        config_model=SetConfig,
        run=set_variables,
        default_timeout_s=10,
    ),
]
