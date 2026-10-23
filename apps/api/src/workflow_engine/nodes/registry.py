"""Every node type, by type name. `REGISTRY` is what validation, routing and workers use."""

from __future__ import annotations

from types import MappingProxyType

from workflow_engine.nodes import aws, core, email, events, flow, http, postgres, slack, triggers
from workflow_engine.nodes.base import NodeType

CATEGORY_ORDER = ("trigger", "core", "flow", "integration")

_ALL: list[NodeType] = [
    *triggers.NODES,
    *core.NODES,
    *events.NODES,
    *flow.NODES,
    *http.NODES,
    *email.NODES,
    *slack.NODES,
    *aws.NODES,
    *postgres.NODES,
]
REGISTRY: MappingProxyType[str, NodeType] = MappingProxyType({n.type: n for n in _ALL})


def ordered() -> list[NodeType]:
    return sorted(_ALL, key=lambda n: (CATEGORY_ORDER.index(n.category), _ALL.index(n)))
