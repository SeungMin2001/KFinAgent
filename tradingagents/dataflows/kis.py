"""Korea Investment & Securities (KIS) market-data provider.

This module deliberately exposes *quotation* endpoints only.  It cannot place
orders or read account balances, so wiring it into an agent does not grant the
agent trading authority.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any

import pandas as pd
import requests

from .errors import NoMarketDataError, VendorNotConfiguredError, VendorRateLimitError

_DOMESTIC_DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
_TOKEN_PATH = "/oauth2/tokenP"
_DOMESTIC_CODE = re.compile(r"^\d{6}$")


class KisInvestorFlowTimeWindowError(RuntimeError):
    """KIS has not opened the requested day's finalized investor-flow data yet."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"KIS investor-flow request failed: {code} {detail}")


@dataclass(frozen=True)
class KisSettings:
    app_key: str
    app_secret: str
    environment: str = "real"
    base_url: str | None = None

    @classmethod
    def from_env(cls) -> KisSettings:
        app_key = os.getenv("KIS_APP_KEY", "").strip()
        app_secret = os.getenv("KIS_APP_SECRET", "").strip()
        if not app_key or not app_secret:
            raise VendorNotConfiguredError(
                "KIS_APP_KEY and KIS_APP_SECRET are required when the KIS data vendor is selected."
            )
        environment = os.getenv("KIS_ENV", "real").strip().lower()
        if environment not in {"real", "demo"}:
            raise ValueError("KIS_ENV must be 'real' or 'demo'.")
        return cls(app_key, app_secret, environment, os.getenv("KIS_BASE_URL") or None)

    @property
    def resolved_base_url(self) -> str:
        if self.base_url:
            return self.base_url.rstrip("/")
        if self.environment == "demo":
            return "https://openapivts.koreainvestment.com:29443"
        return "https://openapi.koreainvestment.com:9443"


class KisClient:
    """Small, testable client for KIS domestic daily OHLCV quotations."""

    def __init__(self, settings: KisSettings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self._access_token: str | None = None

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        response = self.session.post(
            f"{self.settings.resolved_base_url}{_TOKEN_PATH}",
            headers={"content-type": "application/json"},
            json={
                "grant_type": "client_credentials",
                "appkey": self.settings.app_key,
                "appsecret": self.settings.app_secret,
            },
            timeout=15,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = payload.get("msg1") or payload.get("error_description") or str(payload)
            code = payload.get("msg_cd") or payload.get("error_code") or response.status_code
            raise RuntimeError(f"KIS token request failed ({code}): {detail}") from exc
        token = payload.get("access_token")
        if not token:
            raise RuntimeError(f"KIS token request failed: {payload.get('msg1', payload)}")
        self._access_token = token
        return token

    def _daily_request(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        if not _DOMESTIC_CODE.fullmatch(symbol):
            raise ValueError("KIS domestic stock symbols must be six digits, e.g. '005930'.")

        for attempt in range(2):
            response = self.session.get(
                f"{self.settings.resolved_base_url}{_DOMESTIC_DAILY_PATH}",
                headers={
                    "content-type": "application/json",
                    "authorization": f"Bearer {self._token()}",
                    "appkey": self.settings.app_key,
                    "appsecret": self.settings.app_secret,
                    "tr_id": "FHKST03010100",
                },
                params={
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": symbol,
                    "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                    "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
                    "FID_PERIOD_DIV_CODE": "D",
                    # Adjusted prices are the safer default for research and backtests.
                    "FID_ORG_ADJ_PRC": "0",
                },
                timeout=20,
            )
            if response.status_code == 429:
                raise VendorRateLimitError("KIS quotation API rate-limited the request.")
            response.raise_for_status()
            payload = response.json()
            if payload.get("rt_cd") == "0":
                return payload.get("output2") or []
            if attempt == 0 and payload.get("msg_cd") == "EGW00123":
                self._access_token = None
                continue
            raise RuntimeError(f"KIS daily quotation failed: {payload.get('msg_cd')} {payload.get('msg1')}")
        raise RuntimeError("KIS daily quotation failed after refreshing the access token.")

    def daily_ohlcv(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Return adjusted daily OHLCV data, inclusive, indexed by date.

        KIS limits each daily-chart response to roughly 100 observations.  The
        request is therefore split into conservative 90-calendar-day windows.
        """
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        if start > end:
            raise ValueError("start_date must be on or before end_date.")

        rows: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            window_end = min(cursor + timedelta(days=89), end)
            rows.extend(self._daily_request(symbol, cursor, window_end))
            cursor = window_end + timedelta(days=1)

        records = []
        for row in rows:
            try:
                records.append(
                    {
                        "date": pd.to_datetime(row["stck_bsop_date"], format="%Y%m%d"),
                        "open": float(row["stck_oprc"]),
                        "high": float(row["stck_hgpr"]),
                        "low": float(row["stck_lwpr"]),
                        "close": float(row["stck_clpr"]),
                        "volume": float(row.get("acml_vol", 0) or 0),
                        "amount": float(row.get("acml_tr_pbmn", 0) or 0),
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"Unexpected KIS daily quotation row: {row}") from exc

        if not records:
            raise NoMarketDataError(symbol, detail=f"no daily rows between {start_date} and {end_date}")
        frame = pd.DataFrame(records).drop_duplicates("date").sort_values("date")
        frame = frame[(frame["date"].dt.date >= start) & (frame["date"].dt.date <= end)]
        if frame.empty:
            raise NoMarketDataError(symbol, detail=f"no valid daily rows between {start_date} and {end_date}")
        return frame.set_index("date")

    def investor_flow(self, symbol: str, as_of_date: str) -> pd.DataFrame:
        """Return KIS investor net-buying rows, including fund and trust flows."""
        if not _DOMESTIC_CODE.fullmatch(symbol):
            raise ValueError("KIS domestic stock symbols must be six digits, e.g. '005930'.")
        response = self.session.get(
            f"{self.settings.resolved_base_url}/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily",
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self._token()}",
                "appkey": self.settings.app_key,
                "appsecret": self.settings.app_secret,
                "tr_id": "FHPTJ04160001",
            },
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": datetime.strptime(as_of_date, "%Y-%m-%d").strftime("%Y%m%d"),
                "FID_ORG_ADJ_PRC": "",
                "FID_ETC_CLS_CODE": "",
            },
            timeout=20,
        )
        if response.status_code == 429:
            raise VendorRateLimitError("KIS investor-flow API rate-limited the request.")
        response.raise_for_status()
        payload = response.json()
        if payload.get("rt_cd") != "0":
            if payload.get("msg_cd") == "OPSQ2001" and "TIME LIMIT" in str(payload.get("msg1", "")):
                raise KisInvestorFlowTimeWindowError(payload["msg_cd"], payload.get("msg1", ""))
            raise RuntimeError(f"KIS investor-flow request failed: {payload.get('msg_cd')} {payload.get('msg1')}")
        rows = payload.get("output2") or []
        if not rows:
            raise NoMarketDataError(symbol, detail="no KIS investor-flow rows")
        frame = pd.DataFrame(rows)
        if "stck_bsop_date" not in frame:
            raise RuntimeError("Unexpected KIS investor-flow response: missing stck_bsop_date")
        frame["date"] = pd.to_datetime(frame["stck_bsop_date"], format="%Y%m%d")
        requested = pd.Timestamp(as_of_date)
        frame = frame[frame["date"] <= requested].sort_values("date").set_index("date")
        if frame.empty:
            raise NoMarketDataError(symbol, detail=f"no KIS investor-flow rows on or before {as_of_date}")
        frame.attrs["requested_as_of"] = as_of_date
        frame.attrs["latest_date"] = frame.index[-1].date().isoformat()
        return frame


@lru_cache(maxsize=1)
def _default_client() -> KisClient:
    return KisClient(KisSettings.from_env())


def get_kis_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    frame = get_kis_ohlcv_frame(symbol, start_date, end_date)
    header = f"# KIS adjusted daily OHLCV for {symbol} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(frame)}\n\n"
    return header + frame.to_csv(float_format="%.2f")


def get_kis_ohlcv_frame(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Expose raw normalized KIS bars for deterministic validation tools."""
    return _default_client().daily_ohlcv(symbol, start_date, end_date)


def get_kis_investor_flow(symbol: str, as_of_date: str) -> pd.DataFrame:
    """Expose Korean investor-flow data without any secondary provider."""
    return _default_client().investor_flow(symbol, as_of_date)


def get_kis_indicators(symbol: str, indicator: str, curr_date: str, look_back_days: int) -> str:
    """Calculate supported technical indicators only from KIS daily data."""
    supported = {
        "close_50_sma", "close_200_sma", "close_10_ema", "macd", "macds", "macdh",
        "rsi", "boll", "boll_ub", "boll_lb", "atr", "vwma",
    }
    if indicator not in supported:
        raise ValueError(f"Indicator {indicator} is not supported. Choose from: {sorted(supported)}")
    end = datetime.strptime(curr_date, "%Y-%m-%d").date()
    # Extra history is required to warm up the longest indicator (200-day SMA).
    start = end - timedelta(days=max(420, look_back_days + 60))
    frame = get_kis_ohlcv_frame(symbol, start.isoformat(), end.isoformat()).copy()
    close = frame["close"]

    if indicator == "close_50_sma":
        values = close.rolling(50).mean()
    elif indicator == "close_200_sma":
        values = close.rolling(200).mean()
    elif indicator == "close_10_ema":
        values = close.ewm(span=10, adjust=False).mean()
    elif indicator in {"macd", "macds", "macdh"}:
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        signal = macd.ewm(span=9, adjust=False).mean()
        values = {"macd": macd, "macds": signal, "macdh": macd - signal}[indicator]
    elif indicator == "rsi":
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        values = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
    elif indicator in {"boll", "boll_ub", "boll_lb"}:
        mid = close.rolling(20).mean()
        std = close.rolling(20).std()
        values = {"boll": mid, "boll_ub": mid + 2 * std, "boll_lb": mid - 2 * std}[indicator]
    elif indicator == "atr":
        previous_close = close.shift(1)
        true_range = pd.concat(
            [frame["high"] - frame["low"], (frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()],
            axis=1,
        ).max(axis=1)
        values = true_range.rolling(14).mean()
    else:  # vwma
        values = (close * frame["volume"]).rolling(20).sum() / frame["volume"].rolling(20).sum()

    window = values.tail(max(1, look_back_days)).dropna()
    if window.empty:
        return f"## {indicator}\n\nInsufficient KIS history to calculate this indicator."
    rendered = "\n".join(f"{idx.date()}: {value:.4f}" for idx, value in window.items())
    return f"## {indicator} values for {symbol}\n\n{rendered}"
