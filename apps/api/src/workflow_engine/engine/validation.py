"""Validate a workflow definition and report every issue with where it is.

Saving a draft accepts errors (a workflow is often half-built); publishing refuses them.
Each issue names the node, the config field (a JSON path such as `headers[1].value`) or
the edge it belongs to, so the editor can put the message next to the problem.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from workflow_engine.engine import templates
from workflow_engine.engine.definition import NodeSpec, WorkflowDefinition
from workflow_engine.engine.graph import Graph
from workflow_engine.engine.nodetypes import LOOP, LOOP_BACK, LOOP_BATCH, MERGE, Registry

Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class Issue:
    severity: Severity
    code: str
    message: str
    node_id: str | None = None
    field: str | None = None
    edge_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "field": self.field,
            "edge_id": self.edge_id,
        }


def _loc(loc: tuple[int | str, ...]) -> str:
    path = ""
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
    return path


def _config_issues(
    node: NodeSpec, registry: Registry, credentials: Mapping[str, str] | None
) -> list[Issue]:
    spec = registry[node.type]
    issues: list[Issue] = []
    try:
        spec.config_model.model_validate(node.config)
    except ValidationError as exc:
        issues.extend(
            Issue(
                "error",
                "invalid_config",
                str(error.get("msg", "Invalid value.")).removeprefix("Value error, "),
                node_id=node.id,
                field=_loc(tuple(error.get("loc", ()))) or None,
            )
            for error in exc.errors()
        )
    for name in sorted(spec.template_fields):
        if name in node.config:
            for path, message in templates.check(node.config[name], name):
                issues.append(Issue("error", "invalid_template", message, node.id, path))
    for name, accepted in spec.credential_fields.items():
        value = node.config.get(name)
        if not value or credentials is None:
            continue
        kind = credentials.get(str(value))
        if kind is None:
            issues.append(
                Issue(
                    "error", "missing_credential", "That credential does not exist.", node.id, name
                )
            )
        elif kind not in accepted:
            expected = ", ".join(sorted(accepted))
            issues.append(
                Issue(
                    "error",
                    "wrong_credential_type",
                    f"This node needs a credential of type {expected}, not {kind}.",
                    node.id,
                    name,
                )
            )
    return issues


def _ports(node: NodeSpec, registry: Registry) -> tuple[str, ...]:
    try:
        return registry[node.type].output_ports(node.config)
    except (KeyError, TypeError, ValueError, AttributeError):
        return ()


def validate(
    definition: WorkflowDefinition,
    registry: Registry,
    *,
    credentials: Mapping[str, str] | None = None,
) -> list[Issue]:
    """Every problem in the definition. `credentials` maps credential id to its type."""
    issues: list[Issue] = []

    ids = Counter(node.id for node in definition.nodes)
    names = Counter(node.name.strip().lower() for node in definition.nodes)
    for node in definition.nodes:
        if ids[node.id] > 1:
            issues.append(
                Issue("error", "duplicate_id", f"Node id '{node.id}' is used twice.", node.id)
            )
        if names[node.name.strip().lower()] > 1:
            issues.append(
                Issue(
                    "error",
                    "duplicate_name",
                    f"Another node is named '{node.name}'.",
                    node.id,
                    "name",
                )
            )
        if node.type not in registry:
            issues.append(
                Issue("error", "unknown_type", f"Unknown node type '{node.type}'.", node.id)
            )
        else:
            issues.extend(_config_issues(node, registry, credentials))

    graph = Graph(definition)
    known = {n.id: n for n in definition.nodes if n.type in registry}

    edge_ids = Counter(edge.id for edge in definition.edges)
    seen_links: set[tuple[str, str, str, str]] = set()
    for edge in definition.edges:
        if edge_ids[edge.id] > 1:
            issues.append(
                Issue("error", "duplicate_edge", "Two connections share an id.", edge_id=edge.id)
            )
        link = (edge.source, edge.source_port, edge.target, edge.target_port)
        if link in seen_links:
            issues.append(
                Issue(
                    "error", "duplicate_edge", "These nodes are already connected.", edge_id=edge.id
                )
            )
        seen_links.add(link)
        source, target = graph.nodes.get(edge.source), graph.nodes.get(edge.target)
        if source is None or target is None:
            missing = edge.source if source is None else edge.target
            issues.append(
                Issue(
                    "error",
                    "unknown_node",
                    f"The connection points to '{missing}', which does not exist.",
                    edge_id=edge.id,
                )
            )
            continue
        if edge.source == edge.target:
            issues.append(
                Issue(
                    "error",
                    "self_edge",
                    "A node cannot connect to itself.",
                    edge.source,
                    edge_id=edge.id,
                )
            )
        if source.id in known and edge.source_port not in _ports(source, registry):
            issues.append(
                Issue(
                    "error",
                    "unknown_port",
                    f"'{source.name}' has no output '{edge.source_port}'.",
                    source.id,
                    edge_id=edge.id,
                )
            )
        if target.id in known:
            spec = registry[target.type]
            if spec.is_trigger:
                issues.append(
                    Issue(
                        "error",
                        "trigger_has_inputs",
                        f"'{target.name}' is a trigger and cannot have incoming connections.",
                        target.id,
                        edge_id=edge.id,
                    )
                )
            elif edge.target_port not in spec.inputs:
                issues.append(
                    Issue(
                        "error",
                        "unknown_port",
                        f"'{target.name}' has no input '{edge.target_port}'.",
                        target.id,
                        edge_id=edge.id,
                    )
                )

    triggers = [n for n in definition.nodes if n.id in known and registry[n.type].is_trigger]
    if not triggers:
        issues.append(
            Issue(
                "error",
                "no_trigger",
                "Add a trigger: manual, webhook, schedule, interval or event.",
            )
        )

    cycle = graph.find_cycle()
    if cycle:
        path = " -> ".join(graph.nodes[n].name for n in cycle)
        issues.append(
            Issue(
                "error",
                "cycle",
                f"These nodes form a cycle: {path}. Use a Loop node to repeat work.",
                cycle[0],
            )
        )

    for node in definition.nodes:
        if node.type == LOOP:
            issues.extend(_loop_issues(node, graph))

    reachable: set[str] = set()
    for trigger in triggers:
        reachable |= graph.reachable_from(trigger.id)
    for node in definition.nodes:
        if triggers and node.id not in reachable:
            issues.append(
                Issue(
                    "warning",
                    "unreachable",
                    f"'{node.name}' is not connected to any trigger and will never run.",
                    node.id,
                )
            )
        if node.type == MERGE and len(graph.main_incoming(node.id)) < 2:
            issues.append(
                Issue(
                    "warning",
                    "merge_single_input",
                    f"'{node.name}' merges fewer than two inputs.",
                    node.id,
                )
            )
    return issues


def _loop_issues(loop: NodeSpec, graph: Graph) -> list[Issue]:
    issues: list[Issue] = []
    back = graph.back_edges(loop.id)
    if not back:
        issues.append(
            Issue(
                "error",
                "loop_not_closed",
                f"Connect the last node of the loop body back to the '{LOOP_BACK}' input of "
                f"'{loop.name}'.",
                loop.id,
            )
        )
        return issues
    if len(back) > 1:
        issues.append(
            Issue(
                "error",
                "loop_multiple_back_edges",
                f"'{loop.name}' has {len(back)} connections into its '{LOOP_BACK}' input; join the "
                "branches with a Merge node first.",
                loop.id,
            )
        )
    body = graph.loop_body(loop.id)
    issues.extend(
        Issue(
            "error",
            "loop_back_edge_outside",
            f"Only a node inside the loop body can connect back to '{loop.name}'.",
            loop.id,
            edge_id=edge.id,
        )
        for edge in back
        if edge.source not in body
    )
    for node_id in sorted(body):
        for edge in graph.incoming.get(node_id, []):
            from_batch = edge.source == loop.id and edge.source_port == LOOP_BATCH
            if edge.source not in body and not from_batch:
                issues.append(
                    Issue(
                        "error",
                        "loop_body_entered",
                        f"'{graph.nodes[node_id].name}' is inside the loop of '{loop.name}' and "
                        "can only be reached from its batch output.",
                        node_id,
                        edge_id=edge.id,
                    )
                )
        for edge in graph.outgoing.get(node_id, []):
            closes = edge.target == loop.id and edge.target_port == LOOP_BACK
            if edge.target not in body and not closes:
                issues.append(
                    Issue(
                        "error",
                        "loop_body_exit",
                        f"'{graph.nodes[node_id].name}' is inside the loop of '{loop.name}'; use "
                        "the loop's done output to continue after the loop.",
                        node_id,
                        edge_id=edge.id,
                    )
                )
    return issues


def errors(issues: list[Issue]) -> list[Issue]:
    return [issue for issue in issues if issue.severity == "error"]
