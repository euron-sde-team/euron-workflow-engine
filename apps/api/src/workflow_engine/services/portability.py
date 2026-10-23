"""Moving definitions between workspaces: exports, imports and the template gallery.

Credential ids mean nothing outside their workspace, so a portable definition replaces
each credential field with `@credential:<name>` and lists what it needs by name and type.
Importing resolves each reference to the workspace credential with that name and type;
anything unresolved is left empty and shows up as a validation error to fix.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from workflow_engine.nodes.base import NodeType

REFERENCE = "@credential:"


def externalize(
    definition: dict[str, Any],
    registry: Mapping[str, NodeType],
    credentials: Mapping[str, tuple[str, str]],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """credentials: id -> (name, type). Returns the portable copy and what it needs."""
    portable = copy.deepcopy(definition)
    needed: dict[tuple[str, str], dict[str, str]] = {}
    for node in portable.get("nodes", []):
        spec = registry.get(str(node.get("type")))
        if spec is None:
            continue
        config = node.get("config") or {}
        for field in spec.credential_fields:
            value = config.get(field)
            if not value:
                continue
            known = credentials.get(str(value))
            if known is None:
                config[field] = None
                continue
            name, kind = known
            config[field] = f"{REFERENCE}{name}"
            needed[(name, kind)] = {"name": name, "type": kind}
    return portable, sorted(needed.values(), key=lambda c: (c["type"], c["name"]))


def internalize(
    definition: dict[str, Any],
    registry: Mapping[str, NodeType],
    credentials: Mapping[tuple[str, str], str],
    declared: list[dict[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """credentials: (lower name, type) -> id; declared: the document's {name, type} list.

    Returns the resolved copy and the credentials still missing, by name and type.
    """
    declared_types = {
        str(c.get("name", "")).lower(): str(c.get("type", "")) for c in declared or []
    }
    resolved = copy.deepcopy(definition)
    missing: dict[tuple[str, str], dict[str, str]] = {}
    for node in resolved.get("nodes", []):
        spec = registry.get(str(node.get("type")))
        if spec is None:
            continue
        config = node.get("config") or {}
        for field, accepted in spec.credential_fields.items():
            value = config.get(field)
            if not isinstance(value, str) or not value.startswith(REFERENCE):
                continue
            name = value[len(REFERENCE) :]
            wanted = declared_types.get(name.lower())
            kinds = [wanted] if wanted in accepted else sorted(accepted)
            match = next(
                (credentials[(name.lower(), k)] for k in kinds if (name.lower(), k) in credentials),
                None,
            )
            config[field] = match
            if match is None:
                missing[(name, kinds[0])] = {"name": name, "type": kinds[0]}
    return resolved, sorted(missing.values(), key=lambda c: (c["type"], c["name"]))
