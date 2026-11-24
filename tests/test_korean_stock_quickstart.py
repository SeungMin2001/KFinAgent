"""Exercise the documented Korean CLI without account lookup or provider calls."""

from types import SimpleNamespace

import pandas as pd
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from scripts import korean_stock_research as cli
from tradingagents.agents.schemas import PortfolioDecision, ResearchPlan, TraderProposal
from tradingagents.dataflows import kis, korean_evidence
from tradingagents.graph import trading_graph


@pytest.fixture
def run_cli(monkeypatch):
    for key in ("KIS_APP_KEY", "KIS_APP_SECRET", "OPENAI_API_KEY", "DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KIS_APP_KEY", "fixture-kis-key")
    monkeypatch.setenv("KIS_APP_SECRET", "fixture-kis-secret")
    monkeypatch.setenv("KIS_ENV", "real")
    monkeypatch.setattr(cli, "korean_stock_config", lambda overrides: {
        "llm_provider": "openai",
        **overrides,
    })

    def run(*flags):
        monkeypatch.setattr("sys.argv", [
            "korean_stock_research.py", "005930", "--date", "2026-09-02",
            "--account-mode", "disabled", "--kronos-mode", "disabled", *flags,
        ])
        cli.main()

    return run


def test_configuration_reports_all_missing_keys_before_market_request(monkeypatch, run_cli, capsys):
    def no_network(*args, **kwargs):
        pytest.fail("Configuration error should stop before the KIS request")

    monkeypatch.setattr(cli, "verify_kis_data_access_with_bars", no_network)
    with pytest.raises(SystemExit) as error:
        run_cli("--enhanced")
    assert error.value.code == 2
    output = capsys.readouterr().err
    assert all(name in output for name in ("OPENAI_API_KEY", "DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY"))


def test_check_config_exits_before_market_request(monkeypatch, run_cli, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-openai-key")
    monkeypatch.setattr(
        cli, "verify_kis_data_access_with_bars",
        lambda *args, **kwargs: pytest.fail("Configuration preflight must not fetch KIS data"),
    )
    run_cli("--check-config")
    assert "Provider access has not been tested." in capsys.readouterr().out


class FixtureLLM(Runnable):
    def bind_tools(self, tools):
        return self

    def invoke(self, prompt, config=None, **kwargs):
        return AIMessage(content="Fixture analyst or debate response.")

    def with_structured_output(self, schema):
        cases = {
            ResearchPlan: {"recommendation": "Hold", "rationale": "Fixture", "strategic_actions": "Wait"},
            TraderProposal: {"action": "Hold", "reasoning": "Fixture"},
            PortfolioDecision: {
                "rating": "Hold",
                "executive_summary": "Fixture",
                "investment_thesis": "No change",
                "time_horizon": "20 sessions",
            },
        }
        fields = cases.get(schema, {
            "as_of": "2026-09-02",
            "observations": [],
            "conflicts": [],
            "missing_data": [],
            "limitations": [],
            "summary": "Fixture evidence.",
        })
        return SimpleNamespace(invoke=lambda _: schema(**fields))


@pytest.mark.parametrize("enhanced", [False, True])
def test_quickstart_writes_reports_through_real_graph(monkeypatch, run_cli, tmp_path, capsys, enhanced):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-openai-key")
    if enhanced:
        for key in ("DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY"):
            monkeypatch.setenv(key, "fixture-evidence-key")
    dates = pd.bdate_range(end="2026-09-02", periods=250, name="date")
    bars = pd.DataFrame(
        {
            "open": 101, "high": 104, "low": 99, "close": range(100, 350),
            "volume": 4000, "amount": 412000,
        },
        index=dates,
    )
    monkeypatch.setattr(kis, "get_kis_ohlcv_frame", lambda *args: bars)
    for source, heading in (
        ("disclosure_context", "OpenDART disclosures"),
        ("us_macro_context", "US macro snapshot"),
        ("korea_macro_context", "Bank of Korea ECOS macro snapshot"),
        ("investor_flow_context", "KIS investor flow snapshot"),
        ("kis_headline_context", "KIS market/disclosure headline snapshot"),
        ("periodic_fundamentals_context", "OpenDART periodic fundamentals"),
    ):
        report = f"## {heading}\n- Fixture evidence."
        monkeypatch.setattr(korean_evidence, source, lambda *args, report=report, **kwargs: report)
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli, "get_kis_account_snapshot", lambda *_: pytest.fail("Must not fetch balance"))
    monkeypatch.setattr(trading_graph, "create_llm_client", lambda **kwargs: SimpleNamespace(get_llm=FixtureLLM))

    create_graph = cli.create_korean_stock_graph

    def create_tmp_graph(overrides, **kwargs):
        return create_graph(
            {**overrides, "results_dir": str(tmp_path / "artifacts"), "data_cache_dir": str(tmp_path / "cache")},
            **kwargs,
        )

    monkeypatch.setattr(cli, "create_korean_stock_graph", create_tmp_graph)
    run_cli(*(["--enhanced"] if enhanced else []))
    assert "Final signal: Hold" in capsys.readouterr().out
    report = next((tmp_path / "artifacts" / "reports").glob("005930*"))
    for filename in ("complete_report.md", "0_evidence.md", "FINAL_BRIEF.md", "visuals/market_overview.svg"):
        assert (report / filename).stat().st_size > 0
