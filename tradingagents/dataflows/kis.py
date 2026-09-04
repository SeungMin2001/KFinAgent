"""Read-only Korea Investment & Securities (KIS) data provider.

The client can read quotations, investor flows, and a domestic-stock account
balance.  It deliberately has no order endpoint: connecting an account lets
the research workflow reason about current exposure, but never trade.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .errors import NoMarketDataError, VendorNotConfiguredError, VendorRateLimitError

_DOMESTIC_DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
_DOMESTIC_BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
_DOMESTIC_NEWS_TITLE_PATH = "/uapi/domestic-stock/v1/quotations/news-title"
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


@dataclass(frozen=True)
class KisAccountSettings:
    """Account identifiers required only for the read-only balance endpoint."""

    cano: str
    product_code: str

    @classmethod
    def from_env(cls) -> KisAccountSettings:
        cano = os.getenv("KIS_CANO", "").strip()
        product_code = os.getenv("KIS_ACNT_PRDT_CD", "").strip()
        if not cano or not product_code:
            raise VendorNotConfiguredError(
                "KIS_CANO and KIS_ACNT_PRDT_CD are required for account-aware research. "
                "They are used only for KIS read-only balance lookup."
            )
        if not cano.isdigit() or len(cano) != 8:
            raise ValueError("KIS_CANO must be the eight-digit account number without hyphens.")
        if not product_code.isdigit() or len(product_code) != 2:
            raise ValueError("KIS_ACNT_PRDT_CD must be the two-digit account product code, e.g. '01'.")
        return cls(cano=cano, product_code=product_code)


class KisClient:
    """Small, testable client for KIS domestic daily OHLCV quotations."""

    def __init__(
        self,
        settings: KisSettings,
        session: requests.Session | None = None,
        *,
        cache_tokens: bool | None = None,
    ):
        self.settings = settings
        self.session = session or requests.Session()
        self._access_token: str | None = None
        self._cache_tokens = session is None if cache_tokens is None else cache_tokens

    @property
    def _token_cache_path(self) -> Path:
        configured = os.getenv("KIS_TOKEN_CACHE_PATH", "").strip()
        if configured:
            return Path(configured).expanduser()
        return Path.cwd() / ".cache" / f"kis_access_token_{self.settings.environment}.json"

    def _load_cached_token(self) -> str | None:
        if not self._cache_tokens:
            return None
        try:
            cached = json.loads(self._token_cache_path.read_text(encoding="utf-8"))
            expires_at = datetime.strptime(cached["expires_at"], "%Y-%m-%d %H:%M:%S")
            if (
                cached.get("environment") != self.settings.environment
                or cached.get("base_url") != self.settings.resolved_base_url
                or expires_at <= datetime.now() + timedelta(minutes=1)
            ):
                return None
            token = cached.get("access_token")
            return token if isinstance(token, str) and token else None
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _save_cached_token(self, token: str, expires_at: str | None) -> None:
        if not self._cache_tokens or not expires_at:
            return
        try:
            # Validate the broker-provided expiry rather than guessing a TTL.
            datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
            path = self._token_cache_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "access_token": token,
                        "expires_at": expires_at,
                        "environment": self.settings.environment,
                        "base_url": self.settings.resolved_base_url,
                    }
                ),
                encoding="utf-8",
            )
            path.chmod(0o600)
        except (OSError, ValueError):
            # Caching is an optimization only. A live token remains usable.
            return

    def _clear_cached_token(self) -> None:
        if not self._cache_tokens:
            return
        try:
            self._token_cache_path.unlink(missing_ok=True)
        except OSError:
            return

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        if cached_token := self._load_cached_token():
            self._access_token = cached_token
            return cached_token
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
        self._save_cached_token(token, payload.get("access_token_token_expired"))
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
                self._clear_cached_token()
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

    def news_titles(self, symbol: str, as_of_date: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return KIS domestic market/disclosure headline rows for one symbol.

        The endpoint supplies HTS title metadata, not article bodies. Rows are
        filtered to the requested date after the response so a historical
        analysis cannot consume a later headline. KIS's query is paginated;
        only the requested number of qualifying rows is retained.
        """
        if not _DOMESTIC_CODE.fullmatch(symbol):
            raise ValueError("KIS domestic stock symbols must be six digits, e.g. '005930'.")
        if limit < 1 or limit > 100:
            raise ValueError("KIS headline limit must be between 1 and 100.")
        requested = datetime.strptime(as_of_date, "%Y-%m-%d").date()
        rows: list[dict[str, Any]] = []
        continuation = ""
        for _page in range(10):
            response = self.session.get(
                f"{self.settings.resolved_base_url}{_DOMESTIC_NEWS_TITLE_PATH}",
                headers={
                    "content-type": "application/json",
                    "authorization": f"Bearer {self._token()}",
                    "appkey": self.settings.app_key,
                    "appsecret": self.settings.app_secret,
                    "tr_id": "FHKST01011800",
                    "tr_cont": continuation,
                },
                params={
                    "FID_NEWS_OFER_ENTP_CODE": "2",
                    "FID_COND_MRKT_CLS_CODE": "00",
                    "FID_INPUT_ISCD": symbol,
                    "FID_TITL_CNTT": "",
                    "FID_INPUT_DATE_1": requested.strftime("%Y%m%d"),
                    "FID_INPUT_HOUR_1": "235959",
                    "FID_RANK_SORT_CLS_CODE": "01",
                    "FID_INPUT_SRNO": "1",
                },
                timeout=20,
            )
            if response.status_code == 429:
                raise VendorRateLimitError("KIS headline API rate-limited the request.")
            response.raise_for_status()
            payload = response.json()
            if payload.get("rt_cd") != "0":
                raise RuntimeError(
                    f"KIS headline request failed: {payload.get('msg_cd')} {payload.get('msg1')}"
                )
            page_rows = payload.get("output") or []
            if not isinstance(page_rows, list):
                raise RuntimeError("Unexpected KIS headline response: output is not a list.")
            for row in page_rows:
                if not isinstance(row, dict):
                    continue
                raw_date = str(row.get("data_dt", "")).strip()
                title = str(row.get("hts_pbnt_titl_cntt", "")).strip()
                codes = {str(row.get(f"iscd{index}", "")).zfill(6) for index in range(1, 6)}
                if not title or symbol not in codes:
                    continue
                try:
                    published = datetime.strptime(raw_date, "%Y%m%d").date()
                except ValueError as exc:
                    raise RuntimeError(f"Unexpected KIS headline date: {raw_date!r}") from exc
                if published <= requested:
                    rows.append(row)
                    if len(rows) >= limit:
                        return rows
            continuation = response.headers.get("tr_cont", "").strip()
            if continuation != "M":
                break
            continuation = "N"
        return rows

    def domestic_stock_balance(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Read all domestic stock positions and account totals from KIS.

        This maps to the official ``inquire-balance`` endpoint.  KIS returns at
        most 50 positions per page for real accounts, so continuation tokens
        are followed rather than silently discarding a large portfolio.
        """
        account = KisAccountSettings.from_env()
        tr_id = "VTTC8434R" if self.settings.environment == "demo" else "TTTC8434R"
        positions: list[dict[str, Any]] = []
        totals: dict[str, Any] | None = None
        foreign_key = ""
        next_key = ""

        for _page in range(50):
            response = self.session.get(
                f"{self.settings.resolved_base_url}{_DOMESTIC_BALANCE_PATH}",
                headers={
                    "content-type": "application/json",
                    "authorization": f"Bearer {self._token()}",
                    "appkey": self.settings.app_key,
                    "appsecret": self.settings.app_secret,
                    "tr_id": tr_id,
                },
                params={
                    "CANO": account.cano,
                    "ACNT_PRDT_CD": account.product_code,
                    "AFHR_FLPR_YN": "N",
                    "OFL_YN": "",
                    "INQR_DVSN": "02",
                    "UNPR_DVSN": "01",
                    "FUND_STTL_ICLD_YN": "N",
                    "FNCG_AMT_AUTO_RDPT_YN": "N",
                    "PRCS_DVSN": "00",
                    "CTX_AREA_FK100": foreign_key,
                    "CTX_AREA_NK100": next_key,
                },
                timeout=20,
            )
            if response.status_code == 429:
                raise VendorRateLimitError("KIS account-balance API rate-limited the request.")
            if response.status_code >= 400:
                # Do not call ``raise_for_status`` here: its message embeds the
                # complete request URL, including the account number (CANO).
                # Account-aware research must never leak that identifier into a
                # terminal transcript or report.
                try:
                    error_payload = response.json()
                except ValueError:
                    error_payload = {}
                if isinstance(error_payload, dict):
                    detail = " ".join(
                        str(error_payload.get(key, "")).strip()
                        for key in ("msg_cd", "msg1")
                    ).strip()
                else:
                    detail = ""
                suffix = f": {detail}" if detail else ""
                raise RuntimeError(f"KIS account-balance API returned HTTP {response.status_code}{suffix}")
            payload = response.json()
            if payload.get("rt_cd") != "0":
                raise RuntimeError(
                    "KIS account-balance request failed: "
                    f"{payload.get('msg_cd')} {payload.get('msg1')}"
                )
            page_positions = payload.get("output1")
            page_totals = payload.get("output2")
            if not isinstance(page_positions, list) or not isinstance(page_totals, list) or not page_totals:
                raise RuntimeError("Unexpected KIS account-balance response: missing output1/output2.")
            positions.extend(row for row in page_positions if isinstance(row, dict) and row.get("pdno"))
            if totals is None:
                totals = page_totals[0]

            # KIS includes context fields even on a final page.  The response
            # header is the authoritative continuation signal; treating a
            # non-empty context field as a signal caused an unnecessary second
            # request and a real-account HTTP 500.
            if response.headers.get("tr_cont", "").strip() != "M":
                break
            foreign_key = str(payload.get("ctx_area_fk100", "")).strip()
            next_key = str(payload.get("ctx_area_nk100", "")).strip()
            if not foreign_key and not next_key:
                raise RuntimeError("KIS account-balance response requested continuation without context keys.")
        else:
            raise RuntimeError("KIS account-balance pagination exceeded 50 pages.")

        if totals is None:
            raise RuntimeError("Unexpected KIS account-balance response: no account totals.")
        return positions, totals

    def account_snapshot(self, symbol: str) -> str:
        """Render a privacy-minimized account context for agents.

        No account identifier is returned.  The target symbol's holding is
        explicit so that ``Hold`` means retain an existing holding, never
        "wait while owning zero shares".  Other positions are summarized only
        as concentration context.
        """
        if not _DOMESTIC_CODE.fullmatch(symbol):
            raise ValueError("KIS domestic stock symbols must be six digits, e.g. '005930'.")
        positions, totals = self.domestic_stock_balance()

        def number(row: dict[str, Any], field: str) -> float:
            raw = row.get(field)
            if raw in (None, ""):
                raise RuntimeError(f"Unexpected KIS account-balance response: missing {field}.")
            try:
                return float(str(raw).replace(",", ""))
            except ValueError as exc:
                raise RuntimeError(f"Unexpected KIS account-balance value for {field}: {raw!r}") from exc

        total_assets = number(totals, "tot_evlu_amt")
        cash = number(totals, "dnca_tot_amt")
        stock_value = number(totals, "scts_evlu_amt")
        target = next((row for row in positions if str(row.get("pdno", "")).zfill(6) == symbol), None)
        target_qty = number(target, "hldg_qty") if target else 0.0
        target_value = number(target, "evlu_amt") if target else 0.0
        target_weight = (target_value / total_assets * 100) if total_assets > 0 else 0.0

        lines = [
            "## Read-only KIS account context (current, account number redacted)",
            "- This is a live account snapshot, not historical portfolio data and not an order instruction.",
            f"- Domestic positions held: {len(positions)}",
            f"- Total evaluated assets: {total_assets:,.0f} KRW",
            f"- Available cash/deposit: {cash:,.0f} KRW",
            f"- Domestic stock evaluated amount: {stock_value:,.0f} KRW",
        ]
        ranked_positions = sorted(positions, key=lambda row: number(row, "evlu_amt"), reverse=True)
        if ranked_positions:
            lines.append("- Holdings by evaluated value (for diversification context; account number redacted):")
            for row in ranked_positions[:10]:
                value = number(row, "evlu_amt")
                weight = (value / total_assets * 100) if total_assets > 0 else 0.0
                name = str(row.get("prdt_name", "")).strip() or "unnamed"
                code = str(row.get("pdno", "")).zfill(6)
                lines.append(
                    f"  - {code} {name}: {number(row, 'hldg_qty'):,.0f} shares, "
                    f"{value:,.0f} KRW ({weight:.2f}%)"
                )
        if target is None:
            lines.extend([
                f"- Target {symbol} current holding: 0 shares (not held)",
                "- Decision constraint: Hold/Underweight/Sell must not be presented as an action on this target; use Watch/No entry or Buy with a proposed size instead.",
            ])
        else:
            average = number(target, "pchs_avg_pric")
            current = number(target, "prpr")
            pnl = number(target, "evlu_pfls_amt")
            pnl_rate = number(target, "evlu_pfls_rt")
            lines.extend([
                f"- Target {symbol} current holding: {target_qty:,.0f} shares",
                f"- Target average cost / current price: {average:,.0f} / {current:,.0f} KRW",
                f"- Target evaluated value / portfolio weight: {target_value:,.0f} KRW / {target_weight:.2f}%",
                f"- Target unrealized P&L / return: {pnl:,.0f} KRW / {pnl_rate:.2f}%",
                "- Decision constraint: describe Buy as add, Hold as maintain, and Sell/Underweight as reduce or exit this existing position.",
            ])
        return "\n".join(lines)


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


def get_kis_account_snapshot(symbol: str) -> str:
    """Expose a redacted, read-only live account context for a target symbol."""
    return _default_client().account_snapshot(symbol)


def get_kis_news_titles(symbol: str, as_of_date: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Expose KIS HTS market/disclosure title metadata for a domestic symbol."""
    return _default_client().news_titles(symbol, as_of_date, limit=limit)


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
