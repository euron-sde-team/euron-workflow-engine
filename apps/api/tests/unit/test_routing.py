from typing import Any

from tests.unit.engine_fakes import SimStep, Simulator, wf
from workflow_engine.engine.graph import Graph
from workflow_engine.engine.routing import (
    Completion,
    LoopStart,
    Router,
    RoutingState,
    batch_payload,
)


def statuses(sim: Simulator) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for step in sim.steps:
        result.setdefault(step.node_id, []).append(step.status)
    return result


def branch(port: str):  # type: ignore[no-untyped-def]
    def behave(step: SimStep) -> tuple[Any, tuple[str, ...]]:
        if step.node_id.startswith("check"):
            return step.input, (port,)
        return {"from": step.node_id, "input": step.input}, ("main",)

    return behave


def test_a_linear_workflow_passes_outputs_along() -> None:
    sim = Simulator(
        wf([("t", "trigger.manual"), ("a", "action"), ("b", "action")], ["t > a", "a > b"])
    )
    sim.run("t", {"order": 1})
    assert statuses(sim) == {"t": ["succeeded"], "a": ["succeeded"], "b": ["succeeded"]}
    assert sim.runs("a")[0].input == {"order": 1}
    assert sim.runs("b")[0].input == {"order": 1}


def test_the_untaken_branch_is_skipped_to_its_end() -> None:
    definition = wf(
        [
            ("t", "trigger.manual"),
            ("check", "flow.if"),
            ("yes", "action"),
            ("no", "action"),
            ("no_2", "action"),
        ],
        ["t > check", "check:true > yes", "check:false > no", "no > no_2"],
    )
    sim = Simulator(definition, branch("true"))
    sim.run("t", {"total": 640})
    assert statuses(sim)["yes"] == ["succeeded"]
    assert statuses(sim)["no"] == ["skipped"]
    assert statuses(sim)["no_2"] == ["skipped"]


def test_a_merge_after_an_if_waits_only_for_the_branch_that_ran() -> None:
    definition = wf(
        [
            ("t", "trigger.manual"),
            ("check", "flow.if"),
            ("big", "action"),
            ("small", "action"),
            ("join", "flow.merge"),
            ("after", "action"),
        ],
        [
            "t > check",
            "check:true > big",
            "check:false > small",
            "big > join",
            "small > join",
            "join > after",
        ],
    )
    sim = Simulator(definition, branch("false"))
    sim.run("t", {"total": 12})
    assert statuses(sim)["big"] == ["skipped"]
    assert statuses(sim)["join"] == ["succeeded"]
    merge_input = sim.runs("join")[0].input
    assert merge_input == {
        "inputs": [{"node": "small", "data": {"from": "small", "input": {"total": 12}}}]
    }
    assert statuses(sim)["after"] == ["succeeded"]


def test_a_merge_of_parallel_branches_runs_once_with_every_input_in_edge_order() -> None:
    definition = wf(
        [("t", "trigger.manual"), ("a", "action"), ("b", "action"), ("join", "flow.merge")],
        ["t > b", "t > a", "a > join", "b > join"],
    )
    sim = Simulator(definition, lambda step: (step.node_id.upper(), ("main",)))
    sim.run("t")
    assert len(sim.runs("join")) == 1
    assert [i["node"] for i in sim.runs("join")[0].input["inputs"]] == ["a", "b"]


def test_a_skipped_merge_propagates_the_skip() -> None:
    definition = wf(
        [
            ("t", "trigger.manual"),
            ("check", "flow.if"),
            ("a", "action"),
            ("b", "action"),
            ("join", "flow.merge"),
            ("after", "action"),
        ],
        ["t > check", "check:true > a", "check:true > b", "a > join", "b > join", "join > after"],
    )
    sim = Simulator(definition, branch("false"))
    sim.run("t")
    assert statuses(sim)["join"] == ["skipped"]
    assert statuses(sim)["after"] == ["skipped"]


def test_or_joins_run_once_per_delivered_input() -> None:
    definition = wf(
        [("t", "trigger.manual"), ("a", "action"), ("b", "action"), ("notify", "action")],
        ["t > a", "t > b", "a > notify", "b > notify"],
    )
    sim = Simulator(definition)
    sim.run("t")
    assert statuses(sim)["notify"] == ["succeeded", "succeeded"]
    assert [s.run_index for s in sim.runs("notify")] == [0, 1]


def test_an_or_join_is_skipped_only_when_every_input_was_skipped() -> None:
    definition = wf(
        [
            ("t", "trigger.manual"),
            ("check", "flow.if"),
            ("x", "action"),
            ("y", "action"),
            ("z", "action"),
        ],
        ["t > check", "check:true > x", "check:true > y", "x > z", "y > z"],
    )
    sim = Simulator(definition, branch("false"))
    sim.run("t")
    assert statuses(sim)["z"] == ["skipped"]


def test_a_merge_does_not_wait_for_a_trigger_that_did_not_fire() -> None:
    definition = wf(
        [
            ("hook", "trigger.manual"),
            ("cron", "trigger.manual"),
            ("a", "action"),
            ("b", "action"),
            ("join", "flow.merge"),
        ],
        ["hook > a", "cron > b", "a > join", "b > join"],
    )
    sim = Simulator(definition)
    sim.run("hook")
    assert statuses(sim)["join"] == ["succeeded"]
    assert "b" not in statuses(sim)


def loop_behavior(items: list[Any], size: int):  # type: ignore[no-untyped-def]
    def behave(step: SimStep) -> tuple[Any, tuple[str, ...]] | LoopStart:
        if step.node_id == "loop":
            return LoopStart(items, size)
        if step.node_id == "check":
            batch = step.input["batch"]
            return step.input, ("true" if sum(batch) > 3 else "false",)
        if step.node_id == "work":
            return {"sum": sum(step.input["batch"])}, ("main",)
        return step.input, ("main",)

    return behave


def test_a_loop_runs_its_body_once_per_batch_and_collects_results() -> None:
    definition = wf(
        [("t", "trigger.manual"), ("loop", "flow.loop"), ("work", "action"), ("after", "action")],
        ["t > loop", "loop:batch > work", "work > loop:loop", "loop:done > after"],
    )
    sim = Simulator(definition, loop_behavior([1, 2, 3, 4, 5], 2))
    state = sim.run("t")
    work = sim.runs("work")
    assert [s.scope for s in work] == ["/loop:0", "/loop:1", "/loop:2"]
    assert [s.input["batch"] for s in work] == [[1, 2], [3, 4], [5]]
    assert [s.run_index for s in work] == [0, 1, 2]
    done = sim.runs("after")[0].input
    assert done == {"results": [{"sum": 3}, {"sum": 7}, {"sum": 5}], "batches": 3, "items": 5}
    loop_rows = sim.runs("loop")
    assert [s.ports for s in loop_rows] == [("batch",), ("batch",), ("batch",), ("done",)]
    assert state.loops == {}
    assert not state.pending


def test_an_empty_loop_goes_straight_to_done() -> None:
    definition = wf(
        [("t", "trigger.manual"), ("loop", "flow.loop"), ("work", "action"), ("after", "action")],
        ["t > loop", "loop:batch > work", "work > loop:loop", "loop:done > after"],
    )
    sim = Simulator(definition, loop_behavior([], 10))
    sim.run("t")
    assert "work" not in statuses(sim)
    assert sim.runs("after")[0].input == {"results": [], "batches": 0, "items": 0}


def test_a_branch_inside_a_loop_body_skips_back_to_the_loop() -> None:
    definition = wf(
        [
            ("t", "trigger.manual"),
            ("loop", "flow.loop"),
            ("check", "flow.if"),
            ("work", "action"),
            ("after", "action"),
        ],
        [
            "t > loop",
            "loop:batch > check",
            "check:true > work",
            "work > loop:loop",
            "loop:done > after",
        ],
    )
    sim = Simulator(definition, loop_behavior([1, 2, 3, 4], 1))
    sim.run("t")
    assert statuses(sim)["work"] == ["skipped", "skipped", "skipped", "succeeded"]
    assert sim.runs("after")[0].input["results"] == [{"sum": 4}]


def test_a_merge_inside_a_loop_matches_inputs_by_iteration() -> None:
    definition = wf(
        [
            ("t", "trigger.manual"),
            ("loop", "flow.loop"),
            ("a", "action"),
            ("b", "action"),
            ("join", "flow.merge"),
            ("after", "action"),
        ],
        [
            "t > loop",
            "loop:batch > a",
            "loop:batch > b",
            "a > join",
            "b > join",
            "join > loop:loop",
            "loop:done > after",
        ],
    )
    sim = Simulator(definition, loop_behavior(["x", "y", "z"], 1))
    sim.run("t")
    joins = sim.runs("join")
    assert [j.scope for j in joins] == ["/loop:0", "/loop:1", "/loop:2"]
    assert all(len(j.input["inputs"]) == 2 for j in joins)
    assert len(sim.runs("after")[0].input["results"]) == 3


def test_nested_loops_keep_their_scopes_apart() -> None:
    definition = wf(
        [
            ("t", "trigger.manual"),
            ("outer", "flow.loop"),
            ("inner", "flow.loop"),
            ("work", "action"),
            ("collect", "action"),
            ("after", "action"),
        ],
        [
            "t > outer",
            "outer:batch > inner",
            "inner:batch > work",
            "work > inner:loop",
            "inner:done > collect",
            "collect > outer:loop",
            "outer:done > after",
        ],
    )

    def behave(step: SimStep) -> tuple[Any, tuple[str, ...]] | LoopStart:
        if step.node_id == "outer":
            return LoopStart([[1, 2], [3]], 1)
        if step.node_id == "inner":
            return LoopStart(step.input["item"], 1)
        if step.node_id == "work":
            return step.input["item"] * 10, ("main",)
        return step.input, ("main",)

    sim = Simulator(definition, behave)
    sim.run("t")
    assert [s.scope for s in sim.runs("work")] == [
        "/outer:0/inner:0",
        "/outer:0/inner:1",
        "/outer:1/inner:0",
    ]
    results = sim.runs("after")[0].input["results"]
    assert [r["results"] for r in results] == [[10, 20], [30]]


def test_flush_settles_a_merge_whose_input_never_arrives() -> None:
    definition = wf(
        [("t", "trigger.manual"), ("a", "action"), ("b", "action"), ("join", "flow.merge")],
        ["t > a", "a > join", "b > join"],
    )
    graph = Graph(definition)
    state = RoutingState(trigger="t")
    # b is not reachable from t, so it is not live: the merge runs as soon as a arrives.
    plan = Router(graph, state).complete(Completion("s1", "a", "", {"ok": True}, ("main",)))
    assert [s.node_id for s in plan.queued] == ["join"]

    state = RoutingState(trigger=None)  # unknown trigger: every node counts as live
    router = Router(graph, state)
    plan = router.complete(Completion("s1", "a", "", {"ok": True}, ("main",)))
    assert plan.steps == []
    assert "join@" in state.joins
    flushed = Router(graph, state).flush()
    assert [s.node_id for s in flushed.queued] == ["join"]
    assert flushed.queued[0].input == {"inputs": [{"node": "a", "data": {"ok": True}}]}
    assert not state.pending


def test_flush_closes_an_iteration_that_never_returns() -> None:
    definition = wf(
        [("t", "trigger.manual"), ("loop", "flow.loop"), ("work", "action"), ("after", "action")],
        ["t > loop", "loop:batch > work", "work > loop:loop", "loop:done > after"],
    )
    graph = Graph(definition)
    state = RoutingState(trigger="t")
    Router(graph, state).complete(Completion("s1", "loop", "", None, (), LoopStart([1], 1)))
    assert "loop@" in state.loops
    flushed = Router(graph, state).flush()
    assert [s.node_id for s in flushed.queued] == ["after"]
    assert flushed.queued[0].input == {"results": [], "batches": 1, "items": 1}


def test_stale_back_edge_tokens_are_ignored() -> None:
    definition = wf(
        [("t", "trigger.manual"), ("loop", "flow.loop"), ("work", "action")],
        ["t > loop", "loop:batch > work", "work > loop:loop"],
    )
    graph = Graph(definition)
    state = RoutingState(trigger="t")
    Router(graph, state).complete(Completion("s1", "loop", "", None, (), LoopStart([1, 2], 1)))
    plan = Router(graph, state).complete(Completion("s2", "work", "/loop:5", "late", ("main",)))
    assert plan.steps == []
    assert state.loops["loop@"]["index"] == 0


def test_state_round_trips_through_json() -> None:
    state = RoutingState(trigger="t", vars={"region": "west"}, runs={"a": 2})
    state.joins["m@"] = {"e1": {"delivered": True, "data": 1, "source": "a", "step_id": "s1"}}
    assert RoutingState.from_json(state.to_json()) == state
    assert RoutingState.from_json(None) == RoutingState()


def test_batch_payload_shapes() -> None:
    assert batch_payload([1, 2, 3], 2, 1, 2) == {
        "batch": [3],
        "index": 1,
        "batch_number": 2,
        "total_batches": 2,
        "items_total": 3,
    }
    assert batch_payload(["only"], 1, 0, 1)["item"] == "only"
