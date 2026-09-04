import json

import pytest

from scripts.summarize_agent_audit import summarize


def test_incomplete_audit_is_rejected(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"status": "failed"}))
    with pytest.raises(ValueError, match="complete"):
        summarize(tmp_path)


def test_missing_usage_remains_unknown_and_hold_action_is_visible(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "start": "2026-08-20",
                "end": "2026-08-21",
                "agent_graph_calls": 1,
            }
        )
    )
    (tmp_path / "agents_005930_2026-08-19_decision.json").write_text(
        json.dumps(
            {"signal": "Hold", "execution_action": "WAIT", "account": {"target": 0}, "target": 0}
        )
    )
    audit = summarize(tmp_path)
    assert audit["strategies"]["agents"]["tokens"] is None
    assert audit["strategies"]["agents"]["hold_fraction"] == 1
    assert audit["strategies"]["agents"]["actions"] == {"WAIT": 1}
