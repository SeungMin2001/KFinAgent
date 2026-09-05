"""Create a public-safe paired comparison of Agent and Agent+Kronos runs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _tokens(decision: dict) -> dict[str, int] | None:
    usage = decision.get("llm_usage_by_model", {})
    if not usage or any("input_tokens" not in item or "output_tokens" not in item for item in usage.values()):
        return None
    return {
        "input_tokens": sum(item["input_tokens"] for item in usage.values()),
        "output_tokens": sum(item["output_tokens"] for item in usage.values()),
        "total_tokens": sum(item.get("total_tokens", item["input_tokens"] + item["output_tokens"]) for item in usage.values()),
    }


def _forecast(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")

    def value(pattern: str) -> str:
        match = re.search(pattern, text)
        if match is None:
            raise ValueError(f"Missing Kronos field in {path.name}: {pattern}")
        return match.group(1)

    return {
        "model_id": value(r"Source model: (.+)"),
        "horizon_business_days": int(value(r"Forecast horizon: (\d+) business-day")),
        "median_expected_return_pct": float(value(r"Median-path expected return: ([-+0-9.]+)%")),
        "upside_frequency": float(value(r"Sample upside frequency: ([0-9.]+)")),
        "final_return_p10_p50_p90_pct": [
            float(part) for part in value(r"Final-return range \(p10 / p50 / p90\): ([-+0-9.]+% / [-+0-9.]+% / [-+0-9.]+%)").replace("%", "").split(" / ")
        ],
    }


def compare(agents_run: Path, kronos_run: Path) -> dict:
    left, right = _read(agents_run / "manifest.json"), _read(kronos_run / "manifest.json")
    for key in ("start", "end", "symbols", "cost_bps", "cadence_sessions", "initial_exposure", "allocation_policy"):
        if left.get(key) != right.get(key):
            raise ValueError(f"Runs differ on {key}; paired comparison rejected")
    if left.get("status") != "complete" or right.get("status") != "complete":
        raise ValueError("Both runs must be complete")
    rows = []
    for symbol in left["symbols"]:
        base = _read(next(agents_run.glob(f"agents_{symbol}_*_decision.json")))
        enhanced = _read(next(kronos_run.glob(f"agents_kronos_{symbol}_*_decision.json")))
        forecast = _forecast(next(kronos_run.glob(f"{symbol}_*_kronos.md")))
        rows.append({
            "symbol": symbol,
            "agent": {"signal": base["signal"], "action": base["execution_action"], "target_exposure": base["target"], "tokens": _tokens(base)},
            "agents_kronos": {"signal": enhanced["signal"], "action": enhanced["execution_action"], "target_exposure": enhanced["target"], "tokens": _tokens(enhanced)},
            "kronos_forecast": forecast,
            "action_changed": (base["signal"], base["execution_action"], base["target"]) != (enhanced["signal"], enhanced["execution_action"], enhanced["target"]),
        })
    return {
        "status": "complete_smoke_only",
        "paired_conditions": {key: left[key] for key in ("start", "end", "symbols", "cost_bps", "cadence_sessions", "initial_exposure", "allocation_policy")},
        "agent_run": agents_run.name,
        "agents_kronos_run": kronos_run.name,
        "rows": rows,
        "limitations": [
            "Two sessions and one decision per symbol; no performance conclusion is supported.",
            "Kronos output is a probabilistic uncalibrated model output, not a recommendation.",
            "Provider-reported token counts are not billed cost.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agents_run", type=Path)
    parser.add_argument("agents_kronos_run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.agents_run, args.agents_kronos_run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
