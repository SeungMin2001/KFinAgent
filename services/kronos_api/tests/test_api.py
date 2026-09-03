from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from services.kronos_api.app import main


class FakePredictor:
    def predict(self, _frame, _timestamps, future, **_kwargs):
        return pd.DataFrame(
            {
                "open": [101.0] * len(future),
                "high": [103.0] * len(future),
                "low": [100.0] * len(future),
                "close": [102.0] * len(future),
                "volume": [1_000.0] * len(future),
                "amount": [102_000.0] * len(future),
            },
            index=future,
        )


def request_body() -> dict:
    start = datetime(2026, 1, 1)
    bars = []
    for offset in range(30):
        timestamp = start + timedelta(days=offset)
        bars.append(
            {
                "timestamp": timestamp.isoformat(),
                "open": 100,
                "high": 103,
                "low": 99,
                "close": 100,
                "volume": 1_000,
                "amount": 100_000,
            }
        )
    return {
        "symbol": "005930",
        "bars": bars,
        "future_timestamps": [(start + timedelta(days=30)).isoformat()],
        "samples": 3,
    }


def test_health_does_not_load_model(monkeypatch):
    monkeypatch.setenv("KRONOS_MODEL_ID", "NeoQuasar/Kronos-base")
    monkeypatch.setattr(main, "predictor", lambda: (_ for _ in ()).throw(AssertionError("loaded")))

    response = TestClient(main.app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_id": "NeoQuasar/Kronos-base"}


def test_forecast_requires_api_key(monkeypatch):
    monkeypatch.setenv("KRONOS_API_KEY", "secret")

    response = TestClient(main.app).post("/v1/forecast", json=request_body())

    assert response.status_code == 401


def test_forecast_contract_with_fake_predictor(monkeypatch):
    monkeypatch.setenv("KRONOS_API_KEY", "secret")
    monkeypatch.setenv("KRONOS_MODEL_ID", "NeoQuasar/Kronos-base")
    monkeypatch.setattr(main, "predictor", lambda: FakePredictor())

    response = TestClient(main.app).post(
        "/v1/forecast",
        json=request_body(),
        headers={"X-API-Key": "secret"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["model_id"] == "NeoQuasar/Kronos-base"
    assert result["symbol"] == "005930"
    assert result["input_end_date"] == "2026-01-30"
    assert result["last_close"] == 100.0
    assert result["expected_return_pct"] == 2.0
    assert result["upside_probability"] == 1.0
    assert len(result["median_path"]) == 1
