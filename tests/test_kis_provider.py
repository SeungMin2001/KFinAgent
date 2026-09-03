from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows.config import get_config, set_config
from tradingagents.dataflows.kis import KisClient, KisInvestorFlowTimeWindowError, KisSettings
from tradingagents.graph.propagation import Propagator
from tradingagents.korea import korean_stock_config


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({"access_token": "test-token"})

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        # KIS may return newest-first.  The provider must normalize this.
        return FakeResponse(
            {
                "rt_cd": "0",
                "output2": [
                    {
                        "stck_bsop_date": "20260103",
                        "stck_oprc": "71000",
                        "stck_hgpr": "71500",
                        "stck_lwpr": "70500",
                        "stck_clpr": "71200",
                        "acml_vol": "1200000",
                        "acml_tr_pbmn": "85200000000",
                    },
                    {
                        "stck_bsop_date": "20260102",
                        "stck_oprc": "70000",
                        "stck_hgpr": "71100",
                        "stck_lwpr": "69900",
                        "stck_clpr": "71000",
                        "acml_vol": "1000000",
                        "acml_tr_pbmn": "71000000000",
                    },
                ],
            }
        )


def test_kis_daily_ohlcv_authenticates_maps_and_sorts_rows():
    session = FakeSession()
    client = KisClient(KisSettings("key", "secret", base_url="https://example.test"), session=session)

    frame = client.daily_ohlcv("005930", "2026-01-02", "2026-01-03")

    assert len(session.posts) == 1
    assert len(session.gets) == 1
    _, request = session.gets[0]
    assert request["headers"]["authorization"] == "Bearer test-token"
    assert request["params"]["FID_INPUT_ISCD"] == "005930"
    assert request["params"]["FID_ORG_ADJ_PRC"] == "0"
    assert frame.index.strftime("%Y-%m-%d").tolist() == ["2026-01-02", "2026-01-03"]
    assert frame.loc["2026-01-03", "close"] == 71200.0
    assert frame.loc["2026-01-02", "amount"] == 71000000000.0


def test_korean_stock_config_uses_only_kis_for_market_data():
    config = korean_stock_config()

    assert config["data_vendors"]["core_stock_apis"] == "kis"
    assert config["data_vendors"]["technical_indicators"] == "kis"
    assert config["instrument_identity_provider"] == "none"
    assert config["memory_log_path"] is None
    assert config["output_language"] == "Korean"
    assert config["data_cache_dir"].endswith("/.cache")
    assert config["results_dir"].endswith("/artifacts")


def test_kis_verification_uses_live_provider_and_propagates_failure(monkeypatch):
    from tradingagents import korea

    called = []

    def unavailable(*args, **kwargs):
        called.append((args, kwargs))
        raise RuntimeError("KIS authentication failed")

    monkeypatch.setattr(korea, "build_verified_market_snapshot_with_bars", unavailable)

    with pytest.raises(RuntimeError, match="KIS authentication failed"):
        korea.verify_kis_data_access("005930", "2026-09-02")

    assert called


def test_kis_reuses_unexpired_disk_cached_token(tmp_path, monkeypatch):
    monkeypatch.setenv("KIS_TOKEN_CACHE_PATH", str(tmp_path / "kis-token.json"))
    settings = KisSettings("key", "secret", base_url="https://example.test")
    first_session = FakeSession()
    first_session.post = lambda *_args, **_kwargs: FakeResponse(
        {"access_token": "cached-token", "access_token_token_expired": "2099-01-01 00:00:00"}
    )
    first = KisClient(settings, session=first_session, cache_tokens=True)
    assert first._token() == "cached-token"

    second_session = FakeSession()
    second = KisClient(settings, session=second_session, cache_tokens=True)
    assert second._token() == "cached-token"
    assert second_session.posts == []


def test_propagator_keeps_the_preverified_snapshot_in_agent_state():
    state = Propagator().create_initial_state(
        "005930",
        "2026-09-02",
        verified_market_snapshot="verified KIS snapshot",
    )

    assert state["verified_market_snapshot"] == "verified KIS snapshot"


def test_verified_snapshot_uses_kis_when_kis_vendor_is_selected(monkeypatch):
    from tradingagents.dataflows import kis, market_data_validator

    bars = pd.DataFrame(
        {
            "open": [70000, 71000],
            "high": [71200, 72000],
            "low": [69500, 70500],
            "close": [71000, 71500],
            "volume": [1000000, 1200000],
            "amount": [71000000000, 85800000000],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-03"]),
    )
    bars.index.name = "date"
    calls = []

    def fake_kis_frame(symbol, start_date, end_date):
        calls.append((symbol, start_date, end_date))
        return bars

    monkeypatch.setattr(kis, "get_kis_ohlcv_frame", fake_kis_frame)
    monkeypatch.setattr(
        market_data_validator,
        "load_ohlcv",
        lambda *_: (_ for _ in ()).throw(AssertionError("yfinance path must not run")),
    )
    original = get_config()
    try:
        set_config({"data_vendors": {"core_stock_apis": "kis"}})
        snapshot = market_data_validator.build_verified_market_snapshot("005930", "2026-01-03")
    finally:
        set_config(original)

    assert calls and calls[0][0] == "005930"
    assert "Latest trading row used: 2026-01-03" in snapshot
    assert "| Close | 71500 |" in snapshot


def test_kis_investor_flow_exposes_finalization_time_window():
    session = FakeSession()
    session.get = lambda *_args, **_kwargs: FakeResponse(
        {"rt_cd": "1", "msg_cd": "OPSQ2001", "msg1": "TIME LIMIT 00:00 ~ 15:40"}
    )
    client = KisClient(KisSettings("key", "secret", base_url="https://example.test"), session=session)

    with pytest.raises(KisInvestorFlowTimeWindowError, match="OPSQ2001"):
        client.investor_flow("005930", "2026-09-03")
