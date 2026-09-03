import pandas as pd

from tradingagents.dataflows.korean_evidence import evidence_for_domain, kronos_forecast_context


def _bars():
    dates = pd.date_range("2026-01-01", periods=30, freq="B")
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": range(100, 130),
            "High": range(101, 131),
            "Low": range(99, 129),
            "Close": range(100, 130),
            "Volume": [1_000] * 30,
            "Amount": [100_000] * 30,
        }
    )


def test_kronos_context_uses_verified_bars_and_preserves_limitations(monkeypatch):
    def fake_forecast(symbol, bars, horizon, mode, lookback, temperature, top_p, samples):
        assert symbol == "005930"
        assert len(bars) == 30
        assert list(bars.columns) == ["open", "high", "low", "close", "volume", "amount"]
        assert horizon == 2
        assert mode == "remote"
        assert lookback == 30
        assert temperature == 0.6
        assert top_p == 0.9
        assert samples == 10
        return {
            "model_id": "test-model",
            "symbol": symbol,
            "generated_at": "2026-02-12T00:00:00Z",
            "input_end_date": "2026-02-11",
            "last_close": 129.0,
            "expected_return_pct": 1.5,
            "upside_probability": 0.66,
            "return_p10_pct": -2.0,
            "return_p50_pct": 1.5,
            "return_p90_pct": 4.0,
            "uncertainty_pct": 1.2,
            "median_path": [
                {"timestamp": "2026-02-12T00:00:00", "open": 130.0, "high": 131.0, "low": 129.0, "close": 130.0, "volume": 1000.0},
                {"timestamp": "2026-02-13T00:00:00", "open": 131.0, "high": 132.0, "low": 130.0, "close": 131.0, "volume": 1000.0},
            ],
        }

    monkeypatch.setattr("tradingagents.dataflows.korean_evidence.forecast_kronos", fake_forecast)
    text = kronos_forecast_context("005930", _bars(), horizon=2, lookback=30, mode="remote")

    assert "Verified KIS daily bars supplied: 30" in text
    assert "Observable conditions in the candle input" in text
    assert "not attention weights" in text
    assert "Median-path expected return: 1.5000%" in text
    assert "not a calibrated probability" in text


def test_kronos_domain_selector_returns_only_kronos_section():
    snapshot = "## Verified market data snapshot for 005930\nprice\n\n## Kronos forecast snapshot (model output)\nforecast"
    assert evidence_for_domain(snapshot, "kronos") == "## Kronos forecast snapshot (model output)\nforecast"
