import pytest

from tradingagents.dataflows import global_risk as risk
from tradingagents.dataflows.korean_evidence import evidence_for_domain


def test_boj_filters_same_day_and_future_and_labels_market_rate(monkeypatch):
    monkeypatch.setattr(
        risk,
        "_get_json",
        lambda *a: {
            "STATUS": 200,
            "NEXTPOSITION": None,
            "RESULTSET": [
                {
                    "SERIES_CODE": "STRDCLUCON",
                    "VALUES": {
                        "SURVEY_DATES": [20260105, 20260106, 20260107, 20260108],
                        "VALUES": [0.7, 0.8, 99, 100],
                    },
                }
            ],
        },
    )
    result = risk.boj_call_rate_context("2026-01-07")
    assert "0.8%" in result and "99" not in result and "100" not in result
    assert "NOT the BOJ policy target" in result
    assert "+10.00 bp" in result
    assert "NOT proven" in result


def article(stamp, url="https://example.org/a"):
    return {"seendate": stamp, "url": url, "title": "Reported ceasefire", "domain": "example.org"}


def test_news_enforces_korean_close_and_deduplicates(monkeypatch):
    requests = []

    def response(url, params):
        requests.append(params)
        return {
            "articles": [
                article("20260107T060000Z"),
                article("20260107T060000Z"),
                article("20260107T073000Z", "https://example.org/b"),
            ]
        }

    monkeypatch.setattr(risk, "_get_json", response)
    result = risk.geopolitical_context("2026-01-07")
    assert requests[0]["enddatetime"] == "20260107063000"
    assert "valid unique: 1" in result
    assert "https://example.org/b" not in result
    assert "NOT publication" in result


def test_wrong_date_response_is_failure_not_no_news(monkeypatch):
    monkeypatch.setattr(risk, "_get_json", lambda *a: {"articles": [article("20260901T060000Z")]})
    with pytest.raises(ValueError, match="out-of-window"):
        risk.geopolitical_context("2026-01-07")


def test_empty_and_malformed_are_distinct(monkeypatch):
    monkeypatch.setattr(risk, "_get_json", lambda *a: {"articles": []})
    assert "NO_MATCHES" in risk.geopolitical_context("2026-01-07")
    monkeypatch.setattr(risk, "_get_json", lambda *a: {})
    with pytest.raises(ValueError, match="missing article"):
        risk.geopolitical_context("2026-01-07")


def test_new_evidence_reaches_macro_only():
    snapshot = "## Japan monetary conditions (BOJ official API)\nJapan\n## Geopolitical news evidence (GDELT DOC API)\nConflict\n## FRED: Yen\nFX"
    macro = evidence_for_domain(snapshot, "macro")
    assert all(x in macro for x in ("Japan", "Conflict", "FX"))
    assert evidence_for_domain(snapshot, "flow") == ""


def test_transport_failure_propagates(monkeypatch):
    def fail(*args, **kwargs):
        raise risk.requests.ConnectionError("offline")

    monkeypatch.setattr(risk.requests, "get", fail)
    with pytest.raises(risk.requests.ConnectionError):
        risk.geopolitical_context("2026-01-07")


def test_fred_uses_prior_date(monkeypatch):
    risk.global_risk_context.cache_clear()
    calls = []
    monkeypatch.setattr(risk, "geopolitical_context", lambda d: "news")
    monkeypatch.setattr(risk, "boj_call_rate_context", lambda d: "Japan")

    def fred(series, cutoff, **kwargs):
        calls.append((series, cutoff))
        return "**Latest:** 1"

    monkeypatch.setattr(risk, "get_macro_data", fred)
    risk.global_risk_context("2026-01-07")
    assert calls == [("DEXJPUS", "2026-01-06"), ("DCOILBRENTEU", "2026-01-06")]
    risk.global_risk_context.cache_clear()
