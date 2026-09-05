import json

import pytest

from tradingagents.dataflows import dart_compact as compact


def test_excerpts_preserve_lines_and_archive_full_source(monkeypatch):
    saved = []
    monkeypatch.setattr(compact, "archive_content", lambda r, k, c: saved.append(c) or "archive")
    source = "\n".join(f"매출 {i}억원" for i in range(100))
    result = compact.compact_document("20260814000001", source, budget=300)
    assert saved == [source]
    assert "omitted" in result and "incomplete" in result
    excerpts = [line for line in result.splitlines() if line.startswith("L")]
    assert sum(len(line) + 1 for line in excerpts) <= 300
    for line in excerpts:
        number, text = line.split(": ", 1)
        assert text == source.splitlines()[int(number[1:]) - 1]


def test_structured_financials_preserve_scopes_periods_and_values(monkeypatch):
    monkeypatch.setattr(compact, "archive_content", lambda *a: "archive")
    def request(path, **params):
        assert path == "fnlttSinglAcntAll.json"
        return {"list": [{
            "rcept_no": "20260814000001", "corp_code": "00126380",
            "bsns_year": "2026", "reprt_code": "11012", "currency": "KRW",
            "account_nm": "매출액", "thstrm_amount": "100", "thstrm_add_amount": "190",
        }]}
    result = compact.financial_context("00126380", (2026, 6), "20260814000001", request)
    assert "CFS" in result and "OFS" in result
    tables = [json.loads(line) for line in result.splitlines() if line.startswith('{')]
    for table in tables:
        row = dict(zip(table["columns"], table["rows"][0], strict=True))
        assert row["thstrm_amount"] == "100"
        assert row["thstrm_add_amount"] == "190"


def test_future_or_different_receipt_is_rejected(monkeypatch):
    monkeypatch.setattr(compact, "archive_content", lambda *a: "archive")
    with pytest.raises(RuntimeError, match="mismatch"):
        compact.financial_context("00126380", (2026, 6), "20260814000001",
                                  lambda *a, **k: {"list": [{"rcept_no": "20260901000001"}]})


def test_archive_content_is_checksummed_and_immutable(tmp_path, monkeypatch):
    monkeypatch.setattr(compact, "__file__", str(tmp_path / "pkg" / "dataflows" / "test.py"))
    compact.archive_content("20260814000001", "financial.json", json.dumps({"value": 1}))
    compact.archive_content("20260814000001", "financial.json", json.dumps({"value": 2}))
    assert len(list((tmp_path / "artifacts" / "dart_sources" / "20260814000001").iterdir())) == 2
