"""Validated client for a local or remotely deployed Kronos service."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from urllib.parse import urlparse

import pandas as pd
import requests

from .errors import VendorNotConfiguredError

KronosMode = Literal["disabled", "local", "remote"]
PAPER_DAILY_LOOKBACK = 40
PAPER_DAILY_HORIZON = 12
PAPER_FORECAST_TEMPERATURE = 0.6
PAPER_FORECAST_TOP_P = 0.9
PAPER_FORECAST_SAMPLES = 10
_REQUIRED_RESPONSE_FIELDS = {
    "model_id", "symbol", "generated_at", "input_end_date", "last_close",
    "expected_return_pct", "upside_probability", "return_p10_pct",
    "return_p50_pct", "return_p90_pct", "uncertainty_pct", "median_path",
}


@dataclass(frozen=True)
class KronosSettings:
    mode: KronosMode
    api_url: str | None
    api_key: str | None

    @classmethod
    def from_env(cls, mode: str | None = None) -> KronosSettings:
        selected = (mode or os.getenv("KRONOS_MODE", "disabled")).strip().lower()
        if selected not in {"disabled", "local", "remote"}:
            raise ValueError("KRONOS_MODE must be disabled, local, or remote.")
        if selected == "disabled":
            return cls("disabled", None, None)
        default_url = "http://127.0.0.1:8001/v1/forecast" if selected == "local" else ""
        url = os.getenv("KRONOS_API_URL", default_url).strip().rstrip("/")
        key = os.getenv("KRONOS_API_KEY", "").strip()
        if not url or not key:
            raise VendorNotConfiguredError(
                f"KRONOS_API_URL and KRONOS_API_KEY are required in {selected} mode."
            )
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("KRONOS_API_URL must be an absolute HTTP(S) URL.")
        if selected == "remote" and parsed.scheme != "https":
            raise ValueError("Remote Kronos requires an HTTPS API URL.")
        if not parsed.path.endswith("/v1/forecast"):
            raise ValueError("KRONOS_API_URL must end with /v1/forecast.")
        return cls(selected, url, key)


def _validated_response(data: object, symbol: str, input_end_date: str, horizon: int) -> dict:
    if not isinstance(data, dict):
        raise RuntimeError("Kronos returned a non-object JSON response.")
    missing = sorted(_REQUIRED_RESPONSE_FIELDS - data.keys())
    if missing:
        raise RuntimeError(f"Kronos response is missing required fields: {', '.join(missing)}")
    if data["symbol"] != symbol:
        raise RuntimeError(f"Kronos response symbol mismatch: expected {symbol}, got {data['symbol']}")
    if data["input_end_date"] != input_end_date:
        raise RuntimeError(
            f"Kronos response input_end_date mismatch: expected {input_end_date}, got {data['input_end_date']}"
        )
    numeric_fields = _REQUIRED_RESPONSE_FIELDS - {
        "model_id", "symbol", "generated_at", "input_end_date", "median_path",
    }
    for field in numeric_fields:
        value = data[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise RuntimeError(f"Kronos response field {field} must be a finite number.")
    if not 0 <= data["upside_probability"] <= 1:
        raise RuntimeError("Kronos upside_probability must be between 0 and 1.")
    if data["uncertainty_pct"] < 0:
        raise RuntimeError("Kronos uncertainty_pct must not be negative.")
    if not data["return_p10_pct"] <= data["return_p50_pct"] <= data["return_p90_pct"]:
        raise RuntimeError("Kronos return quantiles are not ordered.")
    if not isinstance(data["median_path"], list) or len(data["median_path"]) != horizon:
        raise RuntimeError(f"Kronos median_path must contain exactly {horizon} rows.")
    return data


def forecast_kronos(
    symbol: str,
    bars: pd.DataFrame,
    horizon: int = PAPER_DAILY_HORIZON,
    *,
    mode: str | None = None,
    lookback: int = PAPER_DAILY_LOOKBACK,
    temperature: float = PAPER_FORECAST_TEMPERATURE,
    top_p: float = PAPER_FORECAST_TOP_P,
    samples: int = PAPER_FORECAST_SAMPLES,
) -> dict:
    """Run the paper's daily forecasting protocol unless explicitly overridden.

    The paper's daily benchmark is 40 historical K-lines to 12 future K-lines,
    using T=0.6, top-p=0.9, and ten Monte-Carlo inference trajectories.
    """
    settings = KronosSettings.from_env(mode)
    if settings.mode == "disabled":
        raise VendorNotConfiguredError("Kronos is disabled. Select local or remote mode explicitly.")
    if horizon < 1 or horizon > 30:
        raise ValueError("Kronos horizon must be between 1 and 30 trading days.")
    if lookback < 30 or lookback > 512:
        raise ValueError("Kronos lookback must be between 30 and 512 daily bars.")
    if not 0.1 <= temperature <= 2.0:
        raise ValueError("Kronos temperature must be between 0.1 and 2.0.")
    if not 0.1 <= top_p <= 1.0:
        raise ValueError("Kronos top_p must be between 0.1 and 1.0.")
    if not 1 <= samples <= 10:
        raise ValueError("Kronos samples must be between 1 and 10.")
    required_columns = ["open", "high", "low", "close", "volume", "amount"]
    missing_columns = sorted(set(required_columns) - set(bars.columns))
    if missing_columns:
        raise ValueError(f"Kronos bars are missing columns: {', '.join(missing_columns)}")
    history = bars.tail(lookback).copy()
    if len(history) < 30:
        raise ValueError("Kronos requires at least 30 historical OHLCV bars.")
    history.index = pd.to_datetime(history.index)
    if not history.index.is_monotonic_increasing or history.index.has_duplicates:
        raise ValueError("Kronos bars must have unique, increasing timestamps.")
    if history[required_columns].isna().any().any():
        raise ValueError("Kronos bars must not contain missing OHLCV values.")
    future = pd.bdate_range(history.index[-1] + timedelta(days=1), periods=horizon)
    input_end_date = history.index[-1].date().isoformat()
    payload = {
        "symbol": symbol,
        "bars": [
            {
                "timestamp": timestamp.isoformat(),
                "open": float(row.open), "high": float(row.high), "low": float(row.low),
                "close": float(row.close), "volume": float(row.volume), "amount": float(row.amount),
            }
            for timestamp, row in history.iterrows()
        ],
        "future_timestamps": [timestamp.isoformat() for timestamp in future],
        "samples": samples,
        "temperature": temperature,
        "top_p": top_p,
    }
    response = requests.post(
        settings.api_url,
        json=payload,
        headers={"X-API-Key": settings.api_key},
        timeout=120,
    )
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Kronos returned invalid JSON.") from exc
    return _validated_response(data, symbol, input_end_date, horizon)
