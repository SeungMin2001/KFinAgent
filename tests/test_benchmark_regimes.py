import pytest

from scripts.benchmark_regimes import plan, render
from tradingagents.benchmark import baseline_target


def test_regimes_have_requested_gap_and_twelve_conditions():
    jobs = plan("2026-09-03", ["buy_hold", "cash"], [10, 30, 50], [0, 0.5], 1, ["step"])
    assert len(jobs) == 12
    assert {(j["start"], j["end"]) for j in jobs} == {
        ("2026-01-01", "2026-06-22"),
        ("2026-07-01", "2026-09-03"),
    }
    assert all(j["repeat"] == 1 for j in jobs)


def test_invalid_exposure_rejected():
    with pytest.raises(ValueError):
        plan("2026-09-03", ["cash"], [10], [2], 1, ["step"])


def test_cash_is_an_explicit_baseline():
    from types import SimpleNamespace

    assert baseline_target("cash", SimpleNamespace(close=[]), 0.5) == 0


def test_report_labels_cost_exposure_and_excess():
    jobs = plan("2026-09-03", ["cash"], [10], [0.5], 1, ["step"])
    metrics = {
        "cash": {
            "return_pct": -0.1,
            "excess_buy_hold_pp": 2.0,
            "max_drawdown_pct": -0.1,
            "sharpe_rf0": None,
            "trades": 1,
            "mean_exposure_pct": 0,
            "sessions": 40,
        }
    }
    page, markdown = render([{"job": jobs[0], "metrics": metrics}])
    assert "초기 보유 50%" in page
    assert "+2.00pp" in page and "N/A" in page
    assert "매수보유 대비" in markdown
