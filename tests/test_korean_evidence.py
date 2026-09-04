from __future__ import annotations

import pandas as pd

from tradingagents.dataflows.kis import KisInvestorFlowTimeWindowError
from tradingagents.dataflows.korean_evidence import investor_flow_context, kis_headline_context


def test_current_day_flow_uses_prior_completed_kis_date(monkeypatch):
    from tradingagents.dataflows import korean_evidence

    today = pd.Timestamp.today().date()
    prior = today - pd.offsets.BDay(1)

    def fake_flow(_symbol, as_of):
        if as_of == today.isoformat():
            raise KisInvestorFlowTimeWindowError("OPSQ2001", "TIME LIMIT 00:00 ~ 15:40")
        frame = pd.DataFrame(
            {field: ["1", "2"] for field in korean_evidence._FLOW_FIELDS},
            index=pd.to_datetime([prior.date(), prior.date()]),
        )
        frame.attrs["latest_date"] = prior.date().isoformat()
        return frame

    monkeypatch.setattr(korean_evidence, "get_kis_investor_flow", fake_flow)
    rendered = investor_flow_context("005930", today.isoformat())

    assert f"Requested analysis date: {today.isoformat()}" in rendered
    assert f"Latest completed flow row used: {prior.date().isoformat()}" in rendered
    assert "직전 완료 거래일" in rendered


def test_kis_headline_context_preserves_titles_as_limited_metadata(monkeypatch):
    from tradingagents.dataflows import korean_evidence

    monkeypatch.setattr(
        korean_evidence,
        "get_kis_news_titles",
        lambda *_args, **_kwargs: [
            {
                "data_dt": "20260902",
                "data_tm": "101010",
                "dorg": "KIS",
                "news_lrdv_code": "market",
                "hts_pbnt_titl_cntt": "테스트 | 헤드라인",
            }
        ],
    )

    rendered = kis_headline_context("005930", "2026-09-02", limit=20)

    assert "테스트 \\| 헤드라인" in rendered
    assert "article bodies" in rendered
