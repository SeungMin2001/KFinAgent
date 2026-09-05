import json

import pytest

from scripts.benchmark_korean_stock import enforce_evidence_budget
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


def test_audit_breaks_out_cache_and_reasoning_tokens(tmp_path):
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
            {
                "signal": "Buy",
                "execution_action": "ENTER",
                "account": {"target": 0},
                "target": 0.5,
                "llm_usage_by_model": {
                    "quick": {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "total_tokens": 120,
                        "input_token_details": {"cache_read": 40, "cache_creation": 50},
                        "output_token_details": {"reasoning": 3},
                    }
                },
            }
        )
    )
    audit = summarize(tmp_path)
    assert audit["decisions"][0]["tokens"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "cache_read_tokens": 40,
        "cache_creation_tokens": 50,
        "reasoning_tokens": 3,
    }
    assert audit["decisions"][0]["models"]["quick"]["total_tokens"] == 120


def test_evidence_budget_fails_before_large_corpus_is_sent():
    assert enforce_evidence_budget("x" * 100, 100) == 100
    with pytest.raises(ValueError, match="above the explicit"):
        enforce_evidence_budget("x" * 101, 100)
