"""The templates gallery: realistic automations shipped as JSON documents.

Each document is a portable definition (credentials referenced by name) plus what it needs:
credential names and types, and workspace variables with an example value.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import orjson

import workflow_engine
from workflow_engine.core.errors import NotFoundError
from workflow_engine.engine.definition import WorkflowDefinition

TEMPLATES_DIR = Path(workflow_engine.__file__).parent / "templates"


@dataclass(frozen=True, slots=True)
class GalleryTemplate:
    slug: str
    name: str
    summary: str
    description: str
    category: str
    tags: tuple[str, ...]
    credentials: tuple[dict[str, str], ...]
    variables: tuple[dict[str, str], ...]
    definition: dict[str, Any]
    settings: dict[str, Any]

    @property
    def node_types(self) -> list[str]:
        return sorted({str(n["type"]) for n in self.definition.get("nodes", [])})

    @property
    def trigger_kinds(self) -> list[str]:
        return sorted(
            {
                str(n["type"]).removeprefix("trigger.")
                for n in self.definition.get("nodes", [])
                if str(n["type"]).startswith("trigger.")
            }
        )


@lru_cache(maxsize=1)
def templates() -> dict[str, GalleryTemplate]:
    found: dict[str, GalleryTemplate] = {}
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        data = orjson.loads(path.read_bytes())
        WorkflowDefinition.model_validate(data["definition"])  # a broken template fails loudly
        found[data["slug"]] = GalleryTemplate(
            slug=data["slug"],
            name=data["name"],
            summary=data["summary"],
            description=data["description"],
            category=data["category"],
            tags=tuple(data.get("tags", [])),
            credentials=tuple(data.get("credentials", [])),
            variables=tuple(data.get("variables", [])),
            definition=data["definition"],
            settings=data.get("settings", {}),
        )
    return found


def template(slug: str) -> GalleryTemplate:
    found = templates().get(slug)
    if found is None:
        raise NotFoundError("Template not found.")
    return found
