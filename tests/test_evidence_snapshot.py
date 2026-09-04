import json

import pytest
import requests

from tradingagents.dataflows import evidence_snapshot as snapshot, global_risk as risk

EVIDENCE = (
    "## Geopolitical news evidence\nnews\n## Japan monetary conditions\nrate\nDEXJPUS\nDCOILBRENTEU"
)


def test_snapshot_reuse_makes_no_second_network_call(tmp_path, monkeypatch):
    calls = []

    def collect(day):
        calls.append(day)
        return EVIDENCE

    monkeypatch.setattr(snapshot, "global_risk_context", collect)
    snapshot.collect_snapshot(tmp_path, "2026-08-19")
    snapshot.collect_snapshot(tmp_path, "2026-08-19")
    text = snapshot.read_snapshot(tmp_path, "2026-08-19")
    assert calls == ["2026-08-19"]
    assert "SHA256" in text and "Not a fresh API connection check" in text


def test_corrupted_snapshot_fails_without_live_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "global_risk_context", lambda _: EVIDENCE)
    path = snapshot.collect_snapshot(tmp_path, "2026-08-19")
    record = json.loads(path.read_text())
    record["evidence"] += "tampered"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="checksum"):
        snapshot.collect_snapshot(tmp_path, "2026-08-19")


def test_missing_snapshot_is_not_replaced_by_another_date(tmp_path):
    with pytest.raises(FileNotFoundError):
        snapshot.read_snapshot(tmp_path, "2026-08-19")


def test_network_failure_creates_no_success_snapshot(tmp_path, monkeypatch):
    def fail(_):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(snapshot, "global_risk_context", fail)
    with pytest.raises(requests.ConnectionError):
        snapshot.collect_snapshot(tmp_path, "2026-08-19")
    assert not list(tmp_path.iterdir())


def test_retry_after_is_respected(monkeypatch):
    limited = requests.Response()
    limited.status_code = 429
    limited.headers["Retry-After"] = "45"
    ok = requests.Response()
    ok.status_code = 200
    ok._content = b'{"articles": []}'
    replies = iter([limited, ok])
    waits = []
    monkeypatch.setattr(risk.requests, "get", lambda *a, **kw: next(replies))
    monkeypatch.setattr(risk.clock, "sleep", waits.append)
    assert risk._get_json(risk.GDELT_URL, {}) == {"articles": []}
    assert waits == [45]


def test_long_server_cooldown_stops_instead_of_retrying_early(monkeypatch):
    limited = requests.Response()
    limited.status_code = 429
    limited.headers["Retry-After"] = "120"
    calls = []

    def get(*a, **kw):
        calls.append(1)
        return limited

    monkeypatch.setattr(risk.requests, "get", get)
    with pytest.raises(requests.HTTPError):
        risk._get_json(risk.GDELT_URL, {})
    assert calls == [1]
