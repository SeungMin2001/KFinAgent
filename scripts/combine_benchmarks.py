"""Combine completed independent-stock runs by summing NAV, never averaging Sharpe."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tradingagents.benchmark import metrics, write_report  # noqa: E402


def combine(runs: list[Path], output: Path):
    manifests = [json.loads((run / "manifest.json").read_text()) for run in runs]
    reference = manifests[0]
    for manifest in manifests:
        if manifest.get("status") != "complete":
            raise ValueError("Only complete runs can be combined")
        for key in (
            "start",
            "end",
            "strategies",
            "cost_bps",
            "cadence_sessions",
            "capital_per_symbol",
            "model_override",
            "global_risk",
            "global_risk_source",
            "global_snapshot_sha256",
            "allocation_policy",
            "initial_exposure",
            "periodic_fundamentals",
            "dart_evidence_policy",
            "max_output_tokens_per_response",
            "source_sha256",
            "llm_config",
            "git_commit",
        ):
            if manifest.get(key) != reference.get(key):
                raise ValueError(f"Incompatible experiment field: {key}")
    symbols = [symbol for manifest in manifests for symbol in manifest["symbols"]]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Duplicate symbols across runs")
    output.mkdir(parents=True, exist_ok=False)
    capital = reference["capital_per_symbol"]
    curves, trades, individual = {}, {}, {}
    for strategy in reference["strategies"]:
        sleeves, orders = [], []
        for run, manifest in zip(runs, manifests, strict=True):
            orders.extend(json.loads((run / "trades.json").read_text())[strategy])
            for symbol in manifest["symbols"]:
                path = run / f"{strategy}_{symbol}_equity.csv"
                frame = pd.read_csv(path, index_col="date")
                sleeves.append(frame)
                individual.setdefault(symbol, {})[strategy] = metrics(frame.equity, capital)
                shutil.copy2(path, output / path.name)
        if len({tuple(s.index) for s in sleeves}) != 1:
            raise ValueError("Nonmatching calendars")
        curve = pd.DataFrame(index=sleeves[0].index)
        curve["equity"] = sum(s.equity for s in sleeves)
        curve["exposure"] = sum(s.equity * s.exposure for s in sleeves) / curve.equity
        curves[strategy], trades[strategy] = curve, orders
    combined = {**reference, "symbols": symbols, "source_runs": [str(p) for p in runs]}
    combined["source_manifest_sha256"] = {
        str(p): hashlib.sha256((p / "manifest.json").read_bytes()).hexdigest() for p in runs
    }
    combined["source_snapshots_available"] = all(bool(m.get("source_sha256")) for m in manifests)
    combined["agent_graph_calls"] = sum(m["agent_graph_calls"] for m in manifests)
    combined["input_sha256"] = {k: v for m in manifests for k, v in m["input_sha256"].items()}
    for run, manifest in zip(runs, manifests, strict=True):
        for name, digest in manifest["input_sha256"].items():
            path = run / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Input data checksum mismatch")
            shutil.copy2(path, output / path.name)
    (output / "symbol_metrics.json").write_text(json.dumps(individual, indent=2, allow_nan=False))
    return write_report(
        output, curves, trades, combined, capital * len(symbols), symbol_results=individual
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "artifacts"
        / "benchmarks"
        / ("combined_" + datetime.now().strftime("%Y%m%d_%H%M%S")),
    )
    args = parser.parse_args()
    print(json.dumps(combine(args.runs, args.output), indent=2))
    print(args.output / "BENCHMARK.html")
