"""Adjacency, reachability, loop bodies and cycle detection over a definition.

A `Graph` is immutable once built and cheap to keep: workers cache one per published
version, so routing a step never re-parses the definition.
"""

from __future__ import annotations

from collections import defaultdict, deque

from workflow_engine.engine.definition import EdgeSpec, NodeSpec, WorkflowDefinition
from workflow_engine.engine.nodetypes import LOOP, LOOP_BACK, LOOP_BATCH


class Graph:
    def __init__(self, definition: WorkflowDefinition) -> None:
        self.definition = definition
        self.nodes: dict[str, NodeSpec] = {}
        for node in definition.nodes:
            self.nodes.setdefault(node.id, node)
        self.outgoing: dict[str, list[EdgeSpec]] = defaultdict(list)
        self.incoming: dict[str, list[EdgeSpec]] = defaultdict(list)
        for edge in definition.edges:
            if edge.source in self.nodes and edge.target in self.nodes:
                self.outgoing[edge.source].append(edge)
                self.incoming[edge.target].append(edge)
        self._reachable: dict[str, frozenset[str]] = {}

    def node(self, node_id: str) -> NodeSpec:
        return self.nodes[node_id]

    def is_back_edge(self, edge: EdgeSpec) -> bool:
        target = self.nodes.get(edge.target)
        return target is not None and target.type == LOOP and edge.target_port == LOOP_BACK

    def main_incoming(self, node_id: str) -> list[EdgeSpec]:
        """Incoming edges that activate the node (a loop's back edge only continues it)."""
        return [e for e in self.incoming.get(node_id, []) if not self.is_back_edge(e)]

    def back_edges(self, loop_id: str) -> list[EdgeSpec]:
        return [e for e in self.incoming.get(loop_id, []) if self.is_back_edge(e)]

    def reachable_from(self, start: str) -> frozenset[str]:
        """Every node a token from `start` can reach, `start` included."""
        cached = self._reachable.get(start)
        if cached is not None:
            return cached
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for edge in self.outgoing.get(current, []):
                if edge.target not in seen:
                    seen.add(edge.target)
                    queue.append(edge.target)
        result = frozenset(seen)
        self._reachable[start] = result
        return result

    def loop_body(self, loop_id: str) -> set[str]:
        """Nodes reachable from the loop's `batch` port without passing through the loop."""
        body: set[str] = set()
        queue = deque(
            e.target
            for e in self.outgoing.get(loop_id, [])
            if e.source_port == LOOP_BATCH and e.target != loop_id
        )
        while queue:
            current = queue.popleft()
            if current in body or current == loop_id:
                continue
            body.add(current)
            for edge in self.outgoing.get(current, []):
                if edge.target != loop_id:
                    queue.append(edge.target)
        return body

    def find_cycle(self) -> list[str] | None:
        """A cycle that does not run through a loop's back edge, as a node path, or None."""
        white, grey, black = 0, 1, 2
        color = dict.fromkeys(self.nodes, white)
        parent: dict[str, str] = {}

        for root in self.nodes:
            if color[root] != white:
                continue
            stack: list[tuple[str, int]] = [(root, 0)]
            color[root] = grey
            while stack:
                current, index = stack[-1]
                edges = [e for e in self.outgoing.get(current, []) if not self.is_back_edge(e)]
                if index < len(edges):
                    stack[-1] = (current, index + 1)
                    target = edges[index].target
                    if color[target] == grey:
                        path = [target]
                        node = current
                        while node != target:
                            path.append(node)
                            node = parent[node]
                        path.append(target)
                        return list(reversed(path))
                    if color[target] == white:
                        color[target] = grey
                        parent[target] = current
                        stack.append((target, 0))
                else:
                    color[current] = black
                    stack.pop()
        return None


def parent_scope(scope: str) -> str:
    """`/outer:1/inner:3` -> `/outer:1`; the top level is the empty string."""
    return scope.rsplit("/", 1)[0] if scope else ""


def child_scope(scope: str, loop_id: str, index: int) -> str:
    return f"{scope}/{loop_id}:{index}"


def scope_key(node_id: str, scope: str) -> str:
    return f"{node_id}@{scope}"
