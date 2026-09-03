from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup


class _FakeLLM:
    def with_structured_output(self, _schema):
        return self

    def bind_tools(self, _tools):
        return self


def test_kronos_evidence_node_starts_and_is_a_market_barrier():
    setup = GraphSetup(
        _FakeLLM(),
        _FakeLLM(),
        {"market": lambda _state: {}},
        ConditionalLogic(),
        preload_verified_snapshot=True,
        enable_korean_evidence_agents=True,
        enable_kronos_evidence_agent=True,
    )
    workflow = setup.setup_graph(("market",))

    assert ("__start__", "Time-Series Forecast Evidence Analyst") in workflow.edges
    assert (
        "Time-Series Forecast Evidence Analyst",
        "Market Analyst",
    ) in workflow.edges
