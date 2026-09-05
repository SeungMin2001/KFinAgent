import json

from scripts.compare_agent_variants import compare


def _manifest(symbols):
    return {"status": "complete", "start": "2026-08-20", "end": "2026-08-21", "symbols": symbols,
            "cost_bps": 10, "cadence_sessions": 12, "initial_exposure": 0, "allocation_policy": "step"}


def _decision(signal, action, target):
    return {"signal": signal, "execution_action": action, "target": target,
            "llm_usage_by_model": {"m": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}}}


def test_pair_comparison_extracts_signal_tokens_and_kronos(tmp_path):
    agents, kronos = tmp_path / "agents", tmp_path / "kronos"
    agents.mkdir()
    kronos.mkdir()
    (agents / "manifest.json").write_text(json.dumps(_manifest(["005930"])))
    (kronos / "manifest.json").write_text(json.dumps(_manifest(["005930"])))
    (agents / "agents_005930_2026-08-19_decision.json").write_text(json.dumps(_decision("Hold", "WAIT", 0)))
    (kronos / "agents_kronos_005930_2026-08-19_decision.json").write_text(json.dumps(_decision("Buy", "ENTER", 0.5)))
    (kronos / "005930_2026-08-19_kronos.md").write_text(
        "Source model: NeoQuasar/Kronos-base\nForecast horizon: 12 business-day timestamps\n"
        "Median-path expected return: +2.0000%\nSample upside frequency: 0.6000\n"
        "Final-return range (p10 / p50 / p90): -5.0000% / 2.0000% / 8.0000%"
    )
    result = compare(agents, kronos)
    assert result["rows"][0]["action_changed"]
    assert result["rows"][0]["agent"]["tokens"]["total_tokens"] == 12
    assert result["rows"][0]["kronos_forecast"]["median_expected_return_pct"] == 2
