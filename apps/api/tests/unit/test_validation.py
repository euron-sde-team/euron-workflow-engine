import pytest

from tests.unit.engine_fakes import REGISTRY, wf
from workflow_engine.engine.definition import (
    EdgeSpec,
    NodeSpec,
    RetryPolicy,
    WorkflowDefinition,
    checksum,
    empty_definition,
)
from workflow_engine.engine.graph import Graph
from workflow_engine.engine.validation import Issue, errors, validate


def codes(issues: list[Issue]) -> list[str]:
    return sorted(issue.code for issue in issues)


def test_a_well_formed_workflow_has_no_issues() -> None:
    definition = wf(
        [
            ("t", "trigger.manual"),
            ("fetch", "http", {"url": "{{ env.API }}/orders"}),
            ("done", "action"),
        ],
        ["t > fetch", "fetch > done"],
    )
    assert validate(definition, REGISTRY) == []


def test_a_workflow_needs_a_trigger() -> None:
    issues = validate(wf([("a", "action")], []), REGISTRY)
    assert "no_trigger" in codes(issues)


def test_duplicate_ids_names_and_unknown_types() -> None:
    definition = WorkflowDefinition(
        nodes=[
            NodeSpec(id="t", type="trigger.manual", name="Start"),
            NodeSpec(id="a", type="action", name="Step"),
            NodeSpec(id="a", type="action", name="step"),
            NodeSpec(id="x", type="mystery", name="Mystery"),
        ]
    )
    found = codes(validate(definition, REGISTRY))
    assert found.count("duplicate_id") == 2
    assert found.count("duplicate_name") == 2
    assert "unknown_type" in found


def test_config_errors_carry_the_field_path() -> None:
    definition = wf(
        [("t", "trigger.manual"), ("fetch", "http", {"timeout_s": "soon", "extra": 1})],
        ["t > fetch"],
    )
    issues = [i for i in validate(definition, REGISTRY) if i.code == "invalid_config"]
    assert {i.field for i in issues} == {"url", "timeout_s", "extra"}
    assert all(i.node_id == "fetch" for i in issues)


def test_template_syntax_errors_are_reported() -> None:
    definition = wf(
        [("t", "trigger.manual"), ("fetch", "http", {"url": "{{ env.API"})], ["t > fetch"]
    )
    issues = validate(definition, REGISTRY)
    assert [(i.code, i.field) for i in issues] == [("invalid_template", "url")]


def test_credentials_must_exist_and_match_the_type() -> None:
    definition = wf(
        [
            ("t", "trigger.manual"),
            ("a", "http", {"url": "https://example.com", "credential_id": "c1"}),
            ("b", "http", {"url": "https://example.com", "credential_id": "c2"}),
        ],
        ["t > a", "a > b"],
    )
    assert validate(definition, REGISTRY) == []  # not checked without the workspace's credentials
    issues = validate(definition, REGISTRY, credentials={"c1": "postgres"})
    assert codes(issues) == ["missing_credential", "wrong_credential_type"]


def test_edges_must_point_at_real_nodes_and_ports() -> None:
    definition = WorkflowDefinition(
        nodes=[
            NodeSpec(id="t", type="trigger.manual", name="Start"),
            NodeSpec(id="check", type="flow.if", name="Check"),
            NodeSpec(id="a", type="action", name="A"),
        ],
        edges=[
            EdgeSpec(id="e1", source="t", target="check"),
            EdgeSpec(id="e2", source="check", source_port="maybe", target="a"),
            EdgeSpec(id="e3", source="check", source_port="true", target="ghost"),
            EdgeSpec(id="e4", source="a", target="t"),
            EdgeSpec(id="e5", source="check", source_port="true", target="a", target_port="side"),
            EdgeSpec(id="e6", source="a", target="a"),
            EdgeSpec(id="e6", source="t", target="check"),
        ],
    )
    found = codes(validate(definition, REGISTRY))
    for expected in (
        "unknown_port",
        "unknown_node",
        "trigger_has_inputs",
        "self_edge",
        "duplicate_edge",
    ):
        assert expected in found, expected


def test_cycles_are_refused_except_through_a_loop() -> None:
    cyclic = wf(
        [("t", "trigger.manual"), ("a", "action"), ("b", "action")],
        ["t > a", "a > b", "b > a"],
    )
    issues = validate(cyclic, REGISTRY)
    assert codes(issues) == ["cycle"]
    assert "a -> b -> a" in issues[0].message

    looped = wf(
        [("t", "trigger.manual"), ("loop", "flow.loop"), ("work", "action")],
        ["t > loop", "loop:batch > work", "work > loop:loop"],
    )
    assert validate(looped, REGISTRY) == []


def test_loops_must_be_closed_once_and_kept_self_contained() -> None:
    open_loop = wf(
        [("t", "trigger.manual"), ("loop", "flow.loop"), ("work", "action")],
        ["t > loop", "loop:batch > work"],
    )
    assert codes(validate(open_loop, REGISTRY)) == ["loop_not_closed"]

    twice = wf(
        [("t", "trigger.manual"), ("loop", "flow.loop"), ("a", "action"), ("b", "action")],
        ["t > loop", "loop:batch > a", "loop:batch > b", "a > loop:loop", "b > loop:loop"],
    )
    assert codes(validate(twice, REGISTRY)) == ["loop_multiple_back_edges"]

    leaky = wf(
        [
            ("t", "trigger.manual"),
            ("loop", "flow.loop"),
            ("work", "action"),
            ("side", "action"),
            ("after", "action"),
        ],
        [
            "t > loop",
            "loop:batch > work",
            "work > loop:loop",
            "work > after",
            "loop:done > after",
            "t > side",
            "side > work",
        ],
    )
    found = codes(validate(leaky, REGISTRY))
    assert found == ["loop_body_entered", "loop_body_entered"]

    reentry = wf(
        [("t", "trigger.manual"), ("loop", "flow.loop"), ("work", "action")],
        ["t > loop", "loop:batch > work", "work > loop:loop", "work > loop"],
    )
    assert "loop_body_exit" in codes(validate(reentry, REGISTRY))


def test_a_dead_end_side_branch_inside_a_loop_is_fine() -> None:
    definition = wf(
        [("t", "trigger.manual"), ("loop", "flow.loop"), ("work", "action"), ("notify", "action")],
        ["t > loop", "loop:batch > work", "work > loop:loop", "work > notify"],
    )
    assert validate(definition, REGISTRY) == []


def test_unreachable_nodes_and_lonely_merges_are_warnings() -> None:
    definition = wf(
        [("t", "trigger.manual"), ("a", "action"), ("orphan", "action"), ("join", "flow.merge")],
        ["t > a", "a > join"],
    )
    issues = validate(definition, REGISTRY)
    assert {(i.code, i.severity) for i in issues} == {
        ("unreachable", "warning"),
        ("merge_single_input", "warning"),
    }
    assert errors(issues) == []
    assert issues[0].to_json()["severity"] == "warning"


def test_checksums_ignore_key_order_but_not_content() -> None:
    a = wf([("t", "trigger.manual"), ("x", "action", {"b": 1, "a": 2})], ["t > x"])
    b = wf([("t", "trigger.manual"), ("x", "action", {"a": 2, "b": 1})], ["t > x"])
    c = wf([("t", "trigger.manual"), ("x", "action", {"a": 3, "b": 1})], ["t > x"])
    assert checksum(a) == checksum(b)
    assert checksum(a) != checksum(c)


def test_the_empty_definition_is_valid() -> None:
    assert validate(empty_definition(), REGISTRY) == []


def test_retry_policies_are_ordered() -> None:
    with pytest.raises(ValueError, match="max_delay_ms"):
        RetryPolicy(initial_delay_ms=5000, max_delay_ms=1000)


def test_graph_reachability_and_loop_bodies() -> None:
    graph = Graph(
        wf(
            [
                ("t", "trigger.manual"),
                ("loop", "flow.loop"),
                ("a", "action"),
                ("b", "action"),
                ("after", "action"),
            ],
            ["t > loop", "loop:batch > a", "a > b", "b > loop:loop", "loop:done > after"],
        )
    )
    assert graph.reachable_from("t") == frozenset({"t", "loop", "a", "b", "after"})
    assert graph.loop_body("loop") == {"a", "b"}
    assert [e.id for e in graph.back_edges("loop")] == ["e3"]
    assert [e.id for e in graph.main_incoming("loop")] == ["e0"]
    assert graph.find_cycle() is None
