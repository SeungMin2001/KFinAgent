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
        (
            "Disclosure Evidence Analyst",
            "Macro Evidence Analyst",
            "Flow Evidence Analyst",
            "Time-Series Forecast Evidence Analyst",
        ),
        "Market Analyst",
    ) in workflow.waiting_edges


def test_korean_role_upgrade_preserves_analyst_order_before_added_roles():
    setup = GraphSetup(
        _FakeLLM(),
        _FakeLLM(),
        {key: lambda _state: {} for key in ("market", "social", "news", "fundamentals")},
        ConditionalLogic(),
        preload_verified_snapshot=True,
        enable_korean_evidence_agents=True,
        enable_kronos_evidence_agent=True,
        korean_role_upgrade=True,
    )
    workflow = setup.setup_graph(("market", "social", "news", "fundamentals"))

    assert ("__start__", "Market Analyst") in workflow.edges
    assert ("Msg Clear Market", "Sentiment Analyst") in workflow.edges
    assert ("Msg Clear Sentiment", "News Analyst") in workflow.edges
    assert ("Msg Clear News", "Fundamentals Analyst") in workflow.edges
    assert ("Msg Clear Fundamentals", "Macro Evidence Analyst") in workflow.edges
    assert ("Macro Evidence Analyst", "Time-Series Forecast Evidence Analyst") in workflow.edges
    assert ("Time-Series Forecast Evidence Analyst", "Bull Researcher") in workflow.edges
