"""Render one publication-style SVG from one complete benchmark run.

The figure intentionally renders all pre-declared strategies. It never selects
the best curve or rewrites the comparison after observing the result.
"""

import argparse
import html
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tradingagents.benchmark import STRATEGY_LABELS  # noqa: E402

ORDER = ("agents_kronos", "agents", "buy_hold", "balanced_50", "sma", "macd", "rsi", "cash")
COLORS = {
    "agents_kronos": "#0b4f9c",
    "agents": "#007c91",
    "buy_hold": "#171717",
    "balanced_50": "#7b8794",
    "sma": "#d97706",
    "macd": "#a855f7",
    "rsi": "#e11d48",
    "cash": "#94a3b8",
}


def _points(values, low, spread, x0=72, y0=382, width=760, height=286):
    return " ".join(
        f"{x0 + i * width / (len(values) - 1):.1f},{y0 - (v - low) / spread * height:.1f}"
        for i, v in enumerate(values)
    )


def render(run: Path, output: Path | None = None) -> Path:
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest.get("status") != "complete":
        raise ValueError("Only a complete benchmark run can be rendered")
    metrics = json.loads((run / "metrics.json").read_text())
    names = [name for name in ORDER if name in metrics]
    if not names:
        raise ValueError("No recognized strategies in metrics.json")
    capital = float(manifest["capital_per_symbol"]) * len(manifest["symbols"])
    series = {}
    for name in names:
        frame = pd.read_csv(run / f"{name}_equity.csv")
        series[name] = (frame["equity"].to_numpy(dtype=float) / capital - 1) * 100
    low = min(0.0, *(float(v.min()) for v in series.values()))
    high = max(0.0, *(float(v.max()) for v in series.values()))
    spread = max(1.0, high - low)
    pad = spread * 0.08
    low, high = low - pad, high + pad
    spread = high - low
    ticks = np.linspace(low, high, 5)
    lines = []
    for tick in ticks:
        y = 382 - (tick - low) / spread * 286
        lines.append(f'<line x1="72" x2="832" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        lines.append(
            f'<text x="60" y="{y + 4:.1f}" text-anchor="end" class="axis">{tick:+.0f}%</text>'
        )
    for name in reversed(names):
        width = 3.2 if name.startswith("agents") else 1.65
        lines.append(
            f'<polyline points="{_points(series[name], low, spread)}" fill="none" '
            f'stroke="{COLORS[name]}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>'
        )
    legend = []
    for index, name in enumerate(names):
        x, y = 72 + (index % 4) * 190, 425 + (index // 4) * 24
        legend.append(
            f'<line x1="{x}" x2="{x + 20}" y1="{y}" y2="{y}" stroke="{COLORS[name]}" stroke-width="3"/>'
        )
        legend.append(
            f'<text x="{x + 27}" y="{y + 4}" class="legend">{html.escape(STRATEGY_LABELS.get(name, name))}</text>'
        )
    rows = []
    for i, name in enumerate(names):
        m = metrics[name]
        y = 157 + i * 31
        sharp = "—" if m["sharpe_rf0"] is None else f"{m['sharpe_rf0']:.2f}"
        row_class = " agent" if name.startswith("agents") else ""
        rows.append(
            f'<rect x="872" y="{y - 19}" width="490" height="29" class="row{row_class}"/>'
            f'<text x="885" y="{y}" class="table-label">{html.escape(STRATEGY_LABELS.get(name, name))}</text>'
            f'<text x="1127" y="{y}" text-anchor="end" class="table-num">{m["return_pct"]:+.1f}%</text>'
            f'<text x="1195" y="{y}" text-anchor="end" class="table-num">{sharp}</text>'
            f'<text x="1265" y="{y}" text-anchor="end" class="table-num">{m["max_drawdown_pct"]:.1f}%</text>'
            f'<text x="1345" y="{y}" text-anchor="end" class="table-num">{m["mean_exposure_pct"]:.0f}%</text>'
        )
    audit_note = "Agent decision audit unavailable"
    audit = run / "AGENT_AUDIT.json"
    if audit.exists():
        values = json.loads(audit.read_text()).get("strategies", {})
        chunks = []
        for name in ("agents", "agents_kronos"):
            if name in values:
                chunks.append(
                    f"{STRATEGY_LABELS.get(name, name)} Hold {values[name]['hold_fraction']:.0%} ({values[name]['decisions']} decisions)"
                )
        if chunks:
            audit_note = " · ".join(chunks)
    content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 520" role="img" aria-label="Korean stock agent benchmark">
<style>
.title{{font:700 25px Arial,sans-serif;fill:#102a43}} .sub{{font:13px Arial,sans-serif;fill:#52606d}} .axis{{font:12px Arial,sans-serif;fill:#627d98}} .grid{{stroke:#d9e2ec;stroke-width:1}} .legend{{font:12px Arial,sans-serif;fill:#334e68}} .table-label{{font:13px Arial,sans-serif;fill:#243b53}} .table-num{{font:13px Arial,sans-serif;fill:#102a43;font-weight:600}} .head{{font:11px Arial,sans-serif;fill:#627d98;letter-spacing:.5px}} .row{{fill:#f7fafc}} .row.agent{{fill:#e6f4f8}} .note{{font:11px Arial,sans-serif;fill:#627d98}}
</style><rect width="1400" height="520" fill="#ffffff"/>
<text x="72" y="49" class="title">Korean Stock Agent Benchmark</text>
<text x="72" y="73" class="sub">{html.escape(" · ".join(manifest["symbols"]))}  |  {html.escape(manifest["start"])} to {html.escape(manifest["end"])}  |  next-open execution, {manifest["cost_bps"]:g}bp per side</text>
<text x="72" y="104" class="head">CUMULATIVE NET RETURN</text>{"".join(lines)}
<line x1="72" x2="832" y1="382" y2="382" stroke="#9fb3c8"/><text x="72" y="402" class="axis">{html.escape(manifest["start"])}</text><text x="832" y="402" text-anchor="end" class="axis">{html.escape(manifest["end"])}</text>{"".join(legend)}
<rect x="856" y="72" width="520" height="360" rx="10" fill="#f8fafc" stroke="#d9e2ec"/>
<text x="884" y="108" class="title" style="font-size:18px">Net performance</text>
<text x="1127" y="132" text-anchor="end" class="head">RETURN</text><text x="1195" y="132" text-anchor="end" class="head">SHARPE</text><text x="1265" y="132" text-anchor="end" class="head">MDD</text><text x="1345" y="132" text-anchor="end" class="head">AVG EXP.</text>{"".join(rows)}
<text x="72" y="492" class="note">Pre-declared strategies shown; no post-hoc winner selection. 50% baseline controls for the five-tier Hold = 50% target allocation.</text>
<text x="72" y="510" class="note">{html.escape(audit_note)}. Historical simulation only; not investment advice or evidence of future outperformance.</text>
</svg>"""
    target = output or run / "PUBLIC_BENCHMARK.svg"
    target.write_text(content, encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(render(args.run, args.output))
