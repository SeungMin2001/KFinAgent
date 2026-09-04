import pytest

from tradingagents.dataflows import dart
from tradingagents.dataflows.korean_evidence import evidence_for_domain


def filing(period, received, receipt):
    return {"report_nm": f"분기보고서 ({period})", "rcept_dt": received, "rcept_no": receipt}


def test_selects_latest_period_not_latest_old_correction(monkeypatch):
    calls = []
    monkeypatch.setattr(dart, "resolve_corp_code", lambda _: "00126380")

    def response(*args, **kwargs):
        calls.append(kwargs)
        return {
            "list": [
                filing("2025.12", "20260818", "20260818000001"),
                filing("2026.06", "20260814", "20260814000001"),
            ]
        }

    monkeypatch.setattr(dart, "_json", response)
    monkeypatch.setattr(dart, "disclosure_document", lambda r: "Revenue Cashflow " + r)
    result = dart.periodic_fundamentals_context("005930", "2026-08-19")
    assert "20260814000001" in result
    assert "20260818000001" not in result
    assert calls[0]["end_de"] == "20260818"
    assert calls[0]["pblntf_ty"] == "A" and calls[0]["last_reprt_at"] == "N"
    assert "Revenue Cashflow" in evidence_for_domain(result, "fundamentals")
    assert evidence_for_domain(result, "macro") == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"list": []},
        {"total_page": 2},
        {"list": [filing("2026.06", "20260819", "20260819000001")]},
    ],
)
def test_missing_future_or_truncated_periodic_data_stops(monkeypatch, payload):
    monkeypatch.setattr(dart, "resolve_corp_code", lambda _: "00126380")
    monkeypatch.setattr(dart, "_json", lambda *a, **kw: payload)
    with pytest.raises((ValueError, RuntimeError)):
        dart.periodic_fundamentals_context("005930", "2026-08-19")
