import pytest
from pydantic import ValidationError

from workflow_engine.nodes.credentials import CREDENTIAL_TYPES
from workflow_engine.nodes.flow import switch_ports
from workflow_engine.nodes.registry import REGISTRY, ordered
from workflow_engine.nodes.triggers import (
    CronTriggerConfig,
    EventTriggerConfig,
    IntervalTriggerConfig,
    WebhookTriggerConfig,
    event_matches,
)


def test_every_node_type_has_a_schema_and_a_runner_or_is_a_trigger() -> None:
    assert len(REGISTRY) == 21
    for node in ordered():
        assert node.config_schema()["type"] == "object"
        assert node.is_trigger == (node.run is None)
        assert node.is_trigger == (node.inputs == ())


def test_webhook_triggers_need_a_secret_unless_open() -> None:
    with pytest.raises(ValidationError, match="webhook secret"):
        WebhookTriggerConfig(path="orders")
    assert WebhookTriggerConfig(path="orders", auth="none").method == "POST"
    with pytest.raises(ValidationError):
        WebhookTriggerConfig(path="Orders!", auth="none")
    with pytest.raises(ValidationError, match="end with"):
        WebhookTriggerConfig(path="orders/", auth="none")


def test_schedules_and_intervals_are_validated() -> None:
    assert (
        CronTriggerConfig(expression="0 8 * * MON-FRI", timezone="Asia/Kolkata").timezone
        == "Asia/Kolkata"
    )
    with pytest.raises(ValidationError, match="unknown time zone"):
        CronTriggerConfig(expression="0 8 * * *", timezone="Nowhere/City")
    with pytest.raises(ValidationError, match="expected 5 fields"):
        CronTriggerConfig(expression="0 8 * *")
    assert IntervalTriggerConfig(every=15, unit="minutes").seconds == 900
    with pytest.raises(ValidationError, match="between 10 seconds"):
        IntervalTriggerConfig(every=5, unit="seconds")


def test_event_names_and_filters() -> None:
    assert EventTriggerConfig(event="order.*", filter="payload.total > `100`").event == "order.*"
    with pytest.raises(ValidationError):
        EventTriggerConfig(event="order*")
    with pytest.raises(ValidationError, match="invalid expression"):
        EventTriggerConfig(event="order.created", filter="payload.[")
    assert event_matches("order.*", "order.created")
    assert not event_matches("order.*", "orders.created")
    assert event_matches("lead.created", "lead.created")


def test_switch_ports_follow_the_cases() -> None:
    config = {"cases": [{"port": "high"}, {"port": "low"}], "fallback": True}
    assert switch_ports(config) == ("high", "low", "default")
    assert switch_ports({"cases": [{"port": "a"}], "fallback": False}) == ("a",)
    assert REGISTRY["flow.switch"].default_port(config) == "default"
    assert REGISTRY["flow.loop"].default_port({}) == "done"
    assert REGISTRY["flow.if"].default_port({}) == "true"


def test_credential_types_split_secrets_from_public_fields() -> None:
    postgres = CREDENTIAL_TYPES["postgres"]
    assert postgres.secret_fields == frozenset({"password"})
    values = postgres.model.model_validate(
        {"host": "warehouse", "database": "shop", "user": "reader", "password": "pw-123456"}
    ).model_dump()
    public, hidden = postgres.split(values)
    assert hidden == {"password": "pw-123456"}
    assert public["port"] == 5432
    assert CREDENTIAL_TYPES["webhook_secret"].secret_fields == frozenset({"secret"})
    with pytest.raises(ValidationError):
        CREDENTIAL_TYPES["slack_webhook"].model.model_validate({"url": "not a url at all"})
    with pytest.raises(ValidationError):
        CREDENTIAL_TYPES["webhook_secret"].model.model_validate({"secret": "short"})
