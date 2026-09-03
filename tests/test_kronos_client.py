from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows.errors import VendorNotConfiguredError
from tradingagents.dataflows.kronos import KronosSettings, forecast_kronos


def bars() -> pd.DataFrame:
    index = pd.bdate_range("2026-01-01", periods=30)
    return pd.DataFrame(
        {
            "open": [100.0] * 30, "high": [103.0] * 30, "low": [99.0] * 30,
            "close": [101.0] * 30, "volume": [1_000.0] * 30, "amount": [101_000.0] * 30,
        },
        index=index,
    )


def response_for(frame: pd.DataFrame, horizon: int = 5) -> dict:
    return {
        "model_id": "NeoQuasar/Kronos-base", "symbol": "005930",
        "generated_at": "2026-02-12T12:00:00+09:00",
        "input_end_date": frame.index[-1].date().isoformat(), "last_close": 101.0,
        "expected_return_pct": 1.0, "upside_probability": 0.67,
        "return_p10_pct": -1.0, "return_p50_pct": 1.0, "return_p90_pct": 3.0,
        "uncertainty_pct": 1.5,
        "median_path": [{"timestamp": str(index), "close": 102.0} for index in range(horizon)],
    }


def test_disabled_mode_never_calls_network(monkeypatch):
    monkeypatch.setenv("KRONOS_MODE", "disabled")
    monkeypatch.setattr("tradingagents.dataflows.kronos.requests.post", lambda *_a, **_k: pytest.fail("network"))
    with pytest.raises(VendorNotConfiguredError, match="disabled"):
        forecast_kronos("005930", bars())


def test_local_mode_has_safe_default_url(monkeypatch):
    monkeypatch.setenv("KRONOS_MODE", "local")
    monkeypatch.setenv("KRONOS_API_KEY", "secret")
    monkeypatch.delenv("KRONOS_API_URL", raising=False)
    assert KronosSettings.from_env().api_url == "http://127.0.0.1:8001/v1/forecast"


def test_remote_mode_rejects_plain_http(monkeypatch):
    monkeypatch.setenv("KRONOS_API_URL", "http://example.com/v1/forecast")
    monkeypatch.setenv("KRONOS_API_KEY", "secret")
    with pytest.raises(ValueError, match="HTTPS"):
        KronosSettings.from_env("remote")


def test_client_sends_contract_and_validates_response(monkeypatch):
    frame = bars()
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return response_for(frame)

    monkeypatch.setenv("KRONOS_API_URL", "https://example.test/v1/forecast")
    monkeypatch.setenv("KRONOS_API_KEY", "secret")
    monkeypatch.setattr(
        "tradingagents.dataflows.kronos.requests.post",
        lambda *args, **kwargs: calls.append((args, kwargs)) or FakeResponse(),
    )
    result = forecast_kronos("005930", frame, mode="remote")
    assert result["model_id"] == "NeoQuasar/Kronos-base"
    assert calls[0][1]["headers"] == {"X-API-Key": "secret"}
    assert len(calls[0][1]["json"]["bars"]) == 30


def test_client_rejects_mismatched_input_date(monkeypatch):
    frame = bars()

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            result = response_for(frame)
            result["input_end_date"] = "1999-01-01"
            return result

    monkeypatch.setenv("KRONOS_API_URL", "https://example.test/v1/forecast")
    monkeypatch.setenv("KRONOS_API_KEY", "secret")
    monkeypatch.setattr("tradingagents.dataflows.kronos.requests.post", lambda *_a, **_k: FakeResponse())
    with pytest.raises(RuntimeError, match="input_end_date mismatch"):
        forecast_kronos("005930", frame, mode="remote")
