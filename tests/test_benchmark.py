import numpy as np
import pandas as pd
import pytest

from tradingagents.benchmark import metrics, rating_target, simulate


def test_step_allocation_and_legacy_policy():
    assert rating_target("Buy", 0) == 0.5
    assert rating_target("Overweight", 0) == 0.25
    assert rating_target("Underweight", 0.5) == 0.25
    assert rating_target("Sell", 0.5) == 0
    assert rating_target("Buy", 0.8) == 1
    assert rating_target("Buy", 0, "binary") == 1
    assert rating_target("Underweight", 0, "step") == 0
    assert rating_target("Buy", 0, "tier") == 1
    assert rating_target("Overweight", 0, "tier") == 0.75
    assert rating_target("Hold", 0, "tier") == 0.5
    assert rating_target("Underweight", 1, "tier") == 0.25
    assert rating_target("Sell", 1, "tier") == 0


def test_action_distinguishes_flat_wait_from_holding():
    from tradingagents.benchmark import execution_action

    assert execution_action(0, 0) == "WAIT"
    assert execution_action(0.5, 0.5) == "HOLD_POSITION"
    assert execution_action(0, 0.25) == "ENTER"
    assert execution_action(0.5, 0.25) == "REDUCE"
    assert execution_action(0.5, 0) == "EXIT"


def test_no_order_preserves_units_and_reports_actual_exposure():
    frame = bars()
    frame.loc[frame.index[60]:, "close"] = 120.0
    contexts = []

    def hold(history, context):
        contexts.append(context)
        return None

    curve, trades = simulate(
        frame,
        str(frame.index[60].date()),
        str(frame.index[-1].date()),
        hold,
        initial_exposure=0.5,
        cadence=1,
    )
    assert trades == []
    assert curve.units.nunique() == 1
    assert contexts[0]["target"] == pytest.approx(0.5)
    assert contexts[0]["position_status"] == "INVESTED"
    assert contexts[1]["target"] > 0.5
    assert curve.equity.iloc[-1] == pytest.approx(500_000 + 500_000 / 110 * 120)


def test_partial_entry_keeps_cash_and_hold_does_not_rebalance():
    frame = bars()
    count = 0

    def decide(history, account):
        nonlocal count
        count += 1
        return 0.25 if count == 1 else None

    curve, trades = simulate(
        frame,
        str(frame.index[60].date()),
        str(frame.index[-1].date()),
        decide,
        capital=1000,
        cost_bps=100,
        cadence=1,
    )
    assert len(trades) == 1
    assert trades[0]["notional"] == 250
    assert curve.cash.iloc[-1] == pytest.approx(747.5)
    assert curve.units.nunique() == 1


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


def test_snapshot_dates_exactly_match_simulator_calls():
    from tradingagents.benchmark import decision_dates
    frame = bars()
    start, end = str(frame.index[60].date()), str(frame.index[-1].date())
    seen = []
    def decide(history, account):
        seen.append(history.index[-1])
        return None
    simulate(frame, start, end, decide, cadence=3)
    assert decision_dates(frame, start, end, 3) == seen


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
