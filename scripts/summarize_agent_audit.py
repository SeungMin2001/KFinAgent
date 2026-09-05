"""Audit completed benchmark decisions without calling any model or provider."""

import argparse
import json
from collections import Counter
from pathlib import Path


def summarize(run: Path):
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest.get("status") != "complete":
        raise ValueError("Only complete experiments can produce an Agent audit")
    records = []
    for path in sorted(run.glob("*_decision.json")):
        value = json.loads(path.read_text())
        strategy = "agents_kronos" if path.name.startswith("agents_kronos_") else "agents"
        usage = value.get("llm_usage_by_model", {})
        # Missing usage is unknown, not zero-cost inference.
        tokens = None
        models = None
        if usage and all("input_tokens" in v and "output_tokens" in v for v in usage.values()):
            models = {}
            for model, values in usage.items():
                input_details = values.get("input_token_details", {})
                output_details = values.get("output_token_details", {})
                models[model] = {
                    "input_tokens": values["input_tokens"],
                    "output_tokens": values["output_tokens"],
                    "total_tokens": values.get(
                        "total_tokens", values["input_tokens"] + values["output_tokens"]
                    ),
                    "cache_read_tokens": input_details.get("cache_read", 0),
                    "cache_creation_tokens": input_details.get("cache_creation", 0),
                    "reasoning_tokens": output_details.get("reasoning", 0),
                }
            tokens = {
                key: sum(value[key] for value in models.values())
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "cache_read_tokens",
                    "cache_creation_tokens",
                    "reasoning_tokens",
                )
            }
        records.append(
            {
                "decision_file": path.name,
                "strategy": strategy,
                "signal": value["signal"],
                "action": value["execution_action"],
                "exposure_before": value["account"]["target"],
                "exposure_target": value["target"],
                "tokens": tokens,
                "models": models,
                "fundamentals_report_present": bool(value.get("fundamentals_report", "").strip()),
            }
        )
    if len(records) != manifest.get("agent_graph_calls"):
        raise ValueError("Decision count does not match completed graph count")
    result = {
        "start": manifest["start"],
        "end": manifest["end"],
        "decisions": records,
        "note": "Token counts are provider-reported, not billed cost. Presence of a report does not prove factual correctness.",
        "strategies": {},
    }
    for strategy in sorted({r["strategy"] for r in records}):
        group = [r for r in records if r["strategy"] == strategy]
        result["strategies"][strategy] = {
            "decisions": len(group),
            "signals": dict(Counter(r["signal"] for r in group)),
            "actions": dict(Counter(r["action"] for r in group)),
            "hold_fraction": sum(r["signal"].lower() == "hold" for r in group) / len(group),
            "tokens": {
                k: sum(r["tokens"][k] for r in group) for k in group[0]["tokens"]
            }
            if all(r["tokens"] is not None for r in group)
            else None,
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    result = summarize(args.run)
    target = args.run / "AGENT_AUDIT.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(target)
