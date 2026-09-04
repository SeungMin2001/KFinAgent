import numpy as np
import pandas as pd
import pytest

from tradingagents.benchmark import simulate, metrics, rating_target


def bars():
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 120.0,
            "low": 90.0,
            "close": 110.0,
            "volume": 10000.0,
            "amount": 1000000.0,
        },
        index=pd.bdate_range("2025-01-01", periods=70),
    )


def test_trade_uses_next_open_not_signal_close_and_charges_cost():
    frame = bars()
    start, end = str(frame.index[60].date()), str(frame.index[-1].date())
    seen = []

    def decide(history, account):
        seen.append(history.index[-1])
        return 1

    curve, trades = simulate(frame, start, end, decide, capital=1000, cost_bps=100)
    assert seen == [frame.index[59]]
    assert trades[0]["date"] == start
    assert trades[0]["price"] == 100
    assert curve.equity.iloc[0] == pytest.approx(1000 / 1.01 * 1.1)


def test_future_prices_cannot_change_first_trade():
    frame = bars()
    start, end = str(frame.index[60].date()), str(frame.index[-1].date())

    def decide(history, account):
        return float(history.close.iloc[-1] > 100)

    _, before = simulate(frame, start, end, decide)
    frame.iloc[61:, frame.columns.get_loc("close")] = 500
    frame.iloc[61:, frame.columns.get_loc("high")] = 500
    _, after = simulate(frame, start, end, decide)
    assert before[0] == after[0]


def test_hold_stays_cash_and_review_stops():
    assert rating_target("Hold", 0) == 0
    with pytest.raises(ValueError, match="Untradeable"):
        rating_target("REVIEW", 0)


def test_drawdown_includes_initial_capital():
    result = metrics(pd.Series([90.0, 95.0]), 100)
    assert result["max_drawdown_pct"] == pytest.approx(-10)
    assert result["return_pct"] == pytest.approx(-5)
    assert np.isfinite(result["sharpe_rf0"])


def test_missing_prices_are_not_forward_filled():
    frame = bars()
    frame.iloc[-1, frame.columns.get_loc("close")] = np.nan
    with pytest.raises(ValueError, match="missing"):
        simulate(frame, "2025-03-26", "2025-04-08", lambda *_: 1)


def test_combining_sleeves_recomputes_portfolio_drawdown(tmp_path):
    from scripts.combine_benchmarks import combine
    from tradingagents.benchmark import write_report

    runs = []
    for symbol, final in (("005930", 110.0), ("000660", 90.0)):
        run = tmp_path / symbol
        run.mkdir()
        curve = pd.DataFrame(
            {"equity": [100.0, final], "exposure": [1.0, 1.0]},
            index=pd.Index(["2026-01-02", "2026-01-05"], name="date"),
        )
        curve.to_csv(run / f"buy_hold_{symbol}_equity.csv")
        manifest = {
            "status": "complete",
            "start": "2026-01-02",
            "end": "2026-01-05",
            "symbols": [symbol],
            "strategies": ["buy_hold"],
            "cost_bps": 10,
            "capital_per_symbol": 100,
            "cadence_sessions": 12,
            "input_sha256": {},
            "agent_graph_calls": 0,
        }
        write_report(run, {"buy_hold": curve}, {"buy_hold": []}, manifest, 100)
        runs.append(run)
    result = combine(runs, tmp_path / "combined")
    # +10 and -10 cancel at portfolio level, so MDD is not mean(stock MDD).
    assert result["buy_hold"]["return_pct"] == 0
    assert result["buy_hold"]["max_drawdown_pct"] == 0
    with pytest.raises(ValueError, match="Duplicate"):
        combine([runs[0], runs[0]], tmp_path / "duplicate")
