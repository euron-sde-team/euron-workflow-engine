import uuid

import pytest

from tests.unit.node_fakes import run_node
from workflow_engine.engine.definition import WorkflowDefinition
from workflow_engine.engine.validation import errors, validate
from workflow_engine.nodes.registry import REGISTRY
from workflow_engine.services import gallery, portability


def test_the_gallery_has_the_documented_templates() -> None:
    assert sorted(gallery.templates()) == [
        "customer-onboarding",
        "failure-alerts",
        "invoice-batch",
        "lead-routing",
        "low-stock-report",
        "order-fulfillment",
        "uptime-monitor",
    ]


@pytest.mark.parametrize("slug", sorted(gallery.templates()))
def test_every_template_validates_once_its_credentials_exist(slug: str) -> None:
    template = gallery.template(slug)
    lookup = {(c["name"].lower(), c["type"]): str(uuid.uuid4()) for c in template.credentials}
    resolved, missing = portability.internalize(
        template.definition, REGISTRY, lookup, list(template.credentials)
    )
    assert missing == []
    kinds = {credential_id: kind for (_, kind), credential_id in lookup.items()}
    issues = validate(WorkflowDefinition.model_validate(resolved), REGISTRY, credentials=kinds)
    assert errors(issues) == [], issues
    assert [i for i in issues if i.severity == "warning"] == []


def test_templates_without_credentials_report_what_is_missing() -> None:
    template = gallery.template("order-fulfillment")
    _, missing = portability.internalize(
        template.definition, REGISTRY, {}, list(template.credentials)
    )
    assert missing == [
        {"name": "Sales Slack", "type": "slack_webhook"},
        {"name": "Shop webhook secret", "type": "webhook_secret"},
    ]


def test_unknown_templates_are_not_found() -> None:
    with pytest.raises(Exception, match="Template not found"):
        gallery.template("nope")


async def test_the_low_stock_formatter_turns_rows_into_lines() -> None:
    template = gallery.template("low-stock-report")
    lines = next(n for n in template.definition["nodes"] if n["id"] == "lines")
    rows = {
        "rows": [
            {"title": "Lantern", "on_hand": 3, "reorder_point": 10},
            {"title": "Stove", "on_hand": 2, "reorder_point": 10},
        ],
        "row_count": 2,
    }
    result, _ = await run_node("core.transform", lines["config"], rows)
    assert result.output == "Lantern: 3 left of 10\nStove: 2 left of 10"
