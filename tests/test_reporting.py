"""Report parity: the shared writer produces the report tree for the CLI and the
programmatic API alike (#1037)."""

from types import SimpleNamespace

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import write_final_brief, write_report_tree


def _state():
    return {
        "disclosure_report": "DART",
        "macro_report": "MACRO",
        "flow_report": "FLOW",
        "market_report": "MKT",
        "news_report": "NEWS",
        "investment_debate_state": {"judge_decision": "RM PLAN"},
        "trader_investment_plan": "TRADE",
        "risk_debate_state": {"judge_decision": "PM DECISION"},
    }


@pytest.mark.unit
def test_write_report_tree_creates_files(tmp_path):
    out = write_report_tree(_state(), "AAPL", tmp_path)
    assert out.name == "complete_report.md"
    assert (tmp_path / "1_analysts" / "market.md").read_text() == "MKT"
    assert (tmp_path / "1_analysts" / "disclosure.md").read_text() == "DART"
    assert (tmp_path / "1_analysts" / "macro.md").read_text() == "MACRO"
    assert (tmp_path / "1_analysts" / "flow.md").read_text() == "FLOW"
    assert (tmp_path / "1_analysts" / "news.md").read_text() == "NEWS"
    assert (tmp_path / "2_research" / "manager.md").read_text() == "RM PLAN"
    assert (tmp_path / "3_trading" / "trader.md").read_text() == "TRADE"
    assert (tmp_path / "5_portfolio" / "decision.md").read_text() == "PM DECISION"
    complete = out.read_text()
    assert "Trading Analysis Report: AAPL" in complete
    assert "MKT" in complete and "PM DECISION" in complete


@pytest.mark.unit
def test_write_report_tree_includes_read_only_account_context(tmp_path):
    state = {"account_snapshot": "Target 005930 current holding: 0 shares (not held)"}

    path = write_report_tree(state, "005930", tmp_path)

    assert (tmp_path / "0_account" / "context.md").read_text() == state["account_snapshot"]
    assert "Read-only Account Context" in path.read_text()


@pytest.mark.unit
def test_write_final_brief_is_decision_first_and_links_detailed_artifacts(tmp_path):
    report_path = tmp_path / "complete_report.md"
    report_path.write_text("# Full report", encoding="utf-8")
    visual = tmp_path / "visuals" / "market_overview.svg"
    visual.parent.mkdir()
    visual.write_text("<svg/>", encoding="utf-8")
    state = {
        "final_trade_decision": "**Rating**: Buy",
        "trader_investment_plan": "**Action**: Buy",
        "account_snapshot": "Target 005930 current holding: 0 shares (not held)",
        "historical_report_context": "Referenced prior report — 2026-08-02",
        "flow_report": "### Objective summary\n외국인 순매수 관찰.",
        "kronos_report": "### Objective summary\n12일 중앙 예측 경로.",
    }

    brief = write_final_brief(report_path, state, "005930", visual_path=visual)
    content = brief.read_text()

    assert brief.name == "FINAL_BRIEF.md"
    assert content.index("최종 포트폴리오 판단") < content.index("핵심 근거")
    assert "**Rating**: Buy" in content
    assert "외국인 순매수 관찰." in content
    assert "visuals/market_overview.svg" in content
    assert "complete_report.md" in content


@pytest.mark.unit
def test_save_reports_explicit_path(tmp_path):
    # Unbound: with an explicit save_path, the method doesn't touch self/config.
    out = TradingAgentsGraph.save_reports(None, _state(), "AAPL", save_path=tmp_path)
    assert (tmp_path / "complete_report.md").exists()
    assert out == tmp_path / "complete_report.md"


@pytest.mark.unit
def test_save_reports_defaults_under_results_dir(tmp_path):
    mock_self = SimpleNamespace(config={"results_dir": str(tmp_path)})
    out = TradingAgentsGraph.save_reports(mock_self, _state(), "AAPL")
    assert out.exists()
    assert out.parent.parent.name == "reports"  # results_dir/reports/AAPL_<stamp>/...
    assert out.parent.name.startswith("AAPL_")
