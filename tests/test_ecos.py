from __future__ import annotations

import pytest

from tradingagents.dataflows import ecos


class _Response:
    def __init__(self, rows):
        self._rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return {"StatisticSearch": {"row": self._rows}}


@pytest.mark.unit
def test_ecos_uses_statistic_search_with_as_of_bound(monkeypatch):
    urls = []

    def fake_get(url, timeout):
        urls.append(url)
        return _Response(
            [
                {"TIME": "20260902", "DATA_VALUE": "2.6", "UNIT_NAME": "연%"},
                {"TIME": "20260801", "DATA_VALUE": "2.5", "UNIT_NAME": "연%"},
                {"TIME": "20260903", "DATA_VALUE": "9.9", "UNIT_NAME": "연%"},
            ]
        )

    monkeypatch.setenv("ECOS_API_KEY", "test-key")
    monkeypatch.setattr(ecos.requests, "get", fake_get)

    report = ecos.korea_macro_context("2026-09-02")

    assert len(urls) == 5
    assert all("/StatisticSearch/" in url for url in urls)
    assert any("/D/20250729/20260902/0101000" in url for url in urls)
    assert any("/M/202507/202609/0" in url for url in urls)
    assert "observation period 20260902" in report
    assert "9.9" not in report
    assert "historical data vintages" in report
