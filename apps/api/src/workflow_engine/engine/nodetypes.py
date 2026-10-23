"""What the engine needs to know about a node type, without depending on its implementation.

The concrete types live in `workflow_engine.nodes` together with their `run` coroutines.
Validation and routing only see this protocol, which keeps the engine free of I/O imports.
"""

from __future__ import annotations

import builtins
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel

from workflow_engine.engine.definition import RetryPolicy

# Type names the engine itself gives meaning to.
LOOP = "flow.loop"
MERGE = "flow.merge"
STOP = "flow.stop"
WAIT = "flow.wait"
MAIN = "main"
LOOP_BACK = "loop"
LOOP_BATCH = "batch"
LOOP_DONE = "done"


class NodeTypeInfo(Protocol):
    @property
    def type(self) -> str: ...

    @property
    def is_trigger(self) -> bool: ...

    @property
    def inputs(self) -> tuple[str, ...]: ...

    @property
    def config_model(self) -> builtins.type[BaseModel]: ...

    @property
    def template_fields(self) -> frozenset[str]: ...

    @property
    def credential_fields(self) -> Mapping[str, frozenset[str]]: ...

    @property
    def default_retry(self) -> RetryPolicy: ...

    @property
    def default_timeout_s(self) -> int: ...

    def output_ports(self, config: Mapping[str, Any]) -> tuple[str, ...]: ...

    def default_port(self, config: Mapping[str, Any]) -> str | None: ...


Registry = Mapping[str, NodeTypeInfo]
