"""Authenticated HTTP inference API around the upstream Kronos model."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator


class Bar(BaseModel):
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    amount: float | None = Field(default=None, ge=0)


class ForecastRequest(BaseModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    bars: list[Bar] = Field(min_length=30, max_length=512)
    future_timestamps: list[datetime] = Field(min_length=1, max_length=30)
    samples: int = Field(default=3, ge=1, le=10)
    temperature: float = Field(default=1.0, ge=0.1, le=2.0)
    top_p: float = Field(default=0.9, ge=0.1, le=1.0)

    @field_validator("bars")
    @classmethod
    def timestamps_must_increase(cls, bars: list[Bar]) -> list[Bar]:
        timestamps = [bar.timestamp for bar in bars]
        if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
            raise ValueError("bars must have unique, increasing timestamps")
        return bars


class ForecastResponse(BaseModel):
    model_id: str
    symbol: str
    generated_at: datetime
    input_end_date: str
    last_close: float
    expected_return_pct: float
    upside_probability: float
    return_p10_pct: float
    return_p50_pct: float
    return_p90_pct: float
    uncertainty_pct: float
    median_path: list[dict[str, float | str]]


app = FastAPI(title="Kronos Korea Inference API", version="0.1.0")


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("KRONOS_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="KRONOS_API_KEY is not configured")
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid API key")


@lru_cache(maxsize=1)
def predictor() -> Any:
    """Load the heavyweight upstream model only for the first forecast.

    Keeping this import lazy lets health checks and API-contract tests run
    without a GPU or a local checkout of the upstream Kronos repository.
    """
    import torch

    sys.path.insert(0, os.getenv("KRONOS_SOURCE_DIR", "/opt/kronos"))
    from model import Kronos, KronosPredictor, KronosTokenizer

    device = os.getenv("KRONOS_DEVICE", "cuda:0")
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("KRONOS_DEVICE requests CUDA but no GPU is available")
    tokenizer = KronosTokenizer.from_pretrained(os.environ["KRONOS_TOKENIZER_ID"])
    model = Kronos.from_pretrained(os.environ["KRONOS_MODEL_ID"])
    model.eval()
    return KronosPredictor(model, tokenizer, device=device, max_context=512)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "model_id": os.getenv("KRONOS_MODEL_ID", "not-configured")}


@app.post("/v1/forecast", response_model=ForecastResponse, dependencies=[Depends(require_api_key)])
def forecast(request: ForecastRequest) -> ForecastResponse:
    frame = pd.DataFrame([bar.model_dump() for bar in request.bars])
    timestamps = pd.to_datetime(frame.pop("timestamp"))
    frame["amount"] = frame["amount"].fillna(frame["close"] * frame["volume"])
    future = pd.to_datetime(pd.Series(request.future_timestamps))
    if future.min() <= timestamps.iloc[-1]:
        raise HTTPException(status_code=422, detail="future_timestamps must follow the last input bar")

    paths: list[pd.DataFrame] = []
    model_predictor = predictor()
    for _ in range(request.samples):
        paths.append(
            model_predictor.predict(
                frame,
                timestamps,
                future,
                pred_len=len(future),
                T=request.temperature,
                top_p=request.top_p,
                sample_count=1,
                verbose=False,
            )
        )

    close_paths = np.vstack([path["close"].to_numpy() for path in paths])
    last_close = float(frame.iloc[-1]["close"])
    final_returns = (close_paths[:, -1] / last_close - 1) * 100
    median = np.median(close_paths, axis=0)
    median_ohlcv = pd.concat(paths).groupby(level=0).median().reindex(future)
    median_path = [
        {
            "timestamp": timestamp.isoformat(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for timestamp, row in median_ohlcv.iterrows()
    ]
    return ForecastResponse(
        model_id=os.environ["KRONOS_MODEL_ID"],
        symbol=request.symbol,
        generated_at=datetime.now().astimezone(),
        input_end_date=timestamps.iloc[-1].date().isoformat(),
        last_close=last_close,
        expected_return_pct=round(float((median[-1] / last_close - 1) * 100), 8),
        upside_probability=round(float(np.mean(final_returns > 0)), 8),
        return_p10_pct=round(float(np.quantile(final_returns, 0.10)), 8),
        return_p50_pct=round(float(np.quantile(final_returns, 0.50)), 8),
        return_p90_pct=round(float(np.quantile(final_returns, 0.90)), 8),
        uncertainty_pct=round(float(np.std(final_returns)), 8),
        median_path=median_path,
    )
