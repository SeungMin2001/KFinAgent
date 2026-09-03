from __future__ import annotations

import pandas as pd

from tradingagents.dataflows.kis import KisInvestorFlowTimeWindowError
from tradingagents.dataflows.korean_evidence import investor_flow_context


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
