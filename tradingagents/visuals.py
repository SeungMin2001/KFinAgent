"""Deterministic report visuals and their text equivalent for LLM agents.

Charts are for human review. Agents receive the matching textual summary, not
an unsupported claim that a text-only model inspected an image.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pandas as pd


def build_visual_summary(market_bars: pd.DataFrame) -> str:
    """Describe the same KIS candle series rendered in the report chart."""
    bars = market_bars.copy().sort_values("Date")
    close = pd.to_numeric(bars["Close"], errors="raise")
    volume = pd.to_numeric(bars["Volume"], errors="raise")

    def change(days: int) -> str:
        if len(close) <= days:
            return "not available"
        return f"{(close.iloc[-1] / close.iloc[-days - 1] - 1) * 100:.2f}%"

    rsi_delta = close.diff()
    gain = rsi_delta.clip(lower=0).rolling(14).mean()
    loss = (-rsi_delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss)
    volume_ratio = volume.tail(5).mean() / volume.tail(20).mean() if len(volume) >= 20 and volume.tail(20).mean() else None
    lines = [
        "## Deterministic chart summary (same KIS candles rendered in the report)",
        "",
        f"- Charted daily candles: last {min(90, len(bars))} of {len(bars)} verified KIS rows.",
        f"- Latest close: {close.iloc[-1]:,.2f} on {pd.Timestamp(bars['Date'].iloc[-1]).date().isoformat()}.",
        f"- Close return: 5-day {change(5)}, 20-day {change(20)}, 60-day {change(60)}.",
        f"- Latest 14-day RSI: {'not available' if pd.isna(rsi.iloc[-1]) else f'{rsi.iloc[-1]:.2f}' }.",
        f"- Volume ratio (5-day mean / 20-day mean): {'not available' if volume_ratio is None else f'{volume_ratio:.2f}x'}.",
        "- This is a deterministic description of the rendered chart, not an image interpretation or investment recommendation.",
    ]
    return "\n".join(lines)


def _forecast_path(snapshot: str) -> tuple[list[tuple[pd.Timestamp, float]], float | None, float | None]:
    rows: list[tuple[pd.Timestamp, float]] = []
    in_table = False
    for line in snapshot.splitlines():
        if line.strip() == "### Median forecast path":
            in_table = True
            continue
        if in_table and line.startswith("### "):
            break
        if in_table and line.startswith("|") and "T" in line:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 5:
                try:
                    rows.append((pd.Timestamp(cells[0]), float(cells[4])))
                except (TypeError, ValueError):
                    continue
    range_match = re.search(
        r"Final-return range \(p10 / p50 / p90\):\s*([-+0-9.]+)% / [-+0-9.]+% / ([-+0-9.]+)%",
        snapshot,
    )
    if not range_match:
        return rows, None, None
    return rows, float(range_match.group(1)), float(range_match.group(2))


def write_market_overview_svg(output_dir: Path, market_bars: pd.DataFrame, snapshot: str) -> Path:
    """Write a portable SVG with close, volume, RSI, and Kronos forecast path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "market_overview.svg"
    bars = market_bars.copy().sort_values("Date").tail(90)
    dates = pd.to_datetime(bars["Date"])
    closes = pd.to_numeric(bars["Close"], errors="raise").tolist()
    volumes = pd.to_numeric(bars["Volume"], errors="raise").tolist()
    delta = pd.Series(closes).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsis = (100 - 100 / (1 + gain / loss)).tolist()
    forecasts, p10, p90 = _forecast_path(snapshot)

    width, height = 1000, 680
    left, right = 74, 28
    plot_width = width - left - right

    def x(index: int, count: int) -> float:
        return left + (plot_width * index / max(count - 1, 1))

    def scaled(values: list[float], top: float, bottom: float, low: float | None = None, high: float | None = None):
        lower = min(values) if low is None else low
        upper = max(values) if high is None else high
        padding = max((upper - lower) * 0.08, 1.0)
        lower -= padding
        upper += padding
        return [bottom - ((value - lower) / (upper - lower)) * (bottom - top) for value in values], lower, upper

    forecast_values = [value for _, value in forecasts]
    # Price observations and forecasts must use one shared scale.  Scaling the
    # forecast independently makes a value's vertical position incomparable to
    # the blue history, which is especially misleading on a short horizon.
    terminal_range = []
    if p10 is not None and p90 is not None:
        terminal_range = [closes[-1] * (1 + p10 / 100), closes[-1] * (1 + p90 / 100)]
    _, price_low, price_high = scaled(closes + forecast_values + terminal_range, 58, 315)

    def price_y(value: float) -> float:
        return 315 - ((value - price_low) / (price_high - price_low)) * (315 - 58)

    history_y = [price_y(value) for value in closes]
    forecast_y = [price_y(value) for value in forecast_values]
    volume_y, volume_low, volume_high = scaled(volumes, 375, 485, 0, max(volumes) if volumes else 1)
    rsi_values = [50.0 if pd.isna(value) else float(value) for value in rsis]
    rsi_y, _, _ = scaled(rsi_values, 535, 635, 0, 100)

    total_points = len(closes) + len(forecasts)
    history_points = " ".join(f"{x(i, total_points):.1f},{history_y[i]:.1f}" for i in range(len(closes)))
    forecast_points = ""
    if forecasts:
        # The first red point is the last observed close (the input cut-off),
        # followed by predictions at future timestamps.  It makes the boundary
        # and the model's actual forecast horizon visually unambiguous.
        forecast_points = " ".join(
            [f"{x(len(closes) - 1, total_points):.1f},{history_y[-1]:.1f}"]
            + [f"{x(len(closes) + i, total_points):.1f},{forecast_y[i]:.1f}" for i in range(len(forecasts))]
        )
    bar_width = max(2, plot_width / max(len(volumes), 1) * 0.65)
    volume_rects = "".join(
        f'<rect x="{x(i, len(volumes)) - bar_width / 2:.1f}" y="{volume_y[i]:.1f}" width="{bar_width:.1f}" '
        f'height="{485 - volume_y[i]:.1f}" fill="#4f81bd" opacity="0.65"/>'
        for i in range(len(volumes))
    )
    rsi_points = " ".join(f"{x(i, len(rsi_values)):.1f},{rsi_y[i]:.1f}" for i in range(len(rsi_values)))
    forecast_band = ""
    if forecasts and p10 is not None and p90 is not None:
        last_close = closes[-1]
        final_x = x(total_points - 1, total_points)
        band_values = [last_close * (1 + p10 / 100), last_close * (1 + p90 / 100)]
        band_y = [price_y(value) for value in band_values]
        forecast_band = (
            f'<line x1="{final_x:.1f}" y1="{band_y[0]:.1f}" x2="{final_x:.1f}" y2="{band_y[1]:.1f}" '
            'stroke="#c0504d" stroke-width="6" opacity="0.45"/>'
            f'<text x="{final_x - 6:.1f}" y="{band_y[0] - 8:.1f}" text-anchor="end" class="label">p10–p90</text>'
        )
    date_label_items = [(0, dates.iloc[0]), (len(closes) // 2, dates.iloc[len(closes) // 2]), (len(closes) - 1, dates.iloc[-1])]
    if forecasts:
        date_label_items.append((total_points - 1, forecasts[-1][0]))
    date_labels = "".join(
        f'<text x="{x(index, total_points):.1f}" y="665" text-anchor="middle" class="label">{html.escape(pd.Timestamp(date).strftime("%m-%d"))}</text>'
        for index, date in date_label_items
    )
    cutoff_x = x(len(closes) - 1, total_points)
    cutoff_marker = ""
    if forecasts:
        cutoff_marker = (
            f'<line x1="{cutoff_x:.1f}" y1="58" x2="{cutoff_x:.1f}" y2="315" class="cutoff"/>'
            f'<text x="{cutoff_x - 4:.1f}" y="72" text-anchor="end" class="label">input ends {html.escape(dates.iloc[-1].strftime("%m-%d"))}</text>'
        )
    target.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="KIS price, volume, RSI, and Kronos forecast overview">
<style>.title{{font:600 18px sans-serif;fill:#202124}}.label{{font:12px sans-serif;fill:#5f6368}}.axis{{stroke:#c8cdd3;stroke-width:1}}.cutoff{{stroke:#7f7f7f;stroke-width:1.2;stroke-dasharray:3 3}}.hist{{fill:none;stroke:#1f4e79;stroke-width:2.5}}.forecast{{fill:none;stroke:#c0504d;stroke-width:2.5;stroke-dasharray:7 4}}.rsi{{fill:none;stroke:#8064a2;stroke-width:2}}</style>
<text x="{left}" y="28" class="title">KIS market overview and Kronos forecast</text>
<text x="{left}" y="48" class="label">Historical close (blue) · Kronos median path (red dashed) · final p10–p90 range (red band)</text>
<line x1="{left}" y1="315" x2="{width-right}" y2="315" class="axis"/><line x1="{left}" y1="485" x2="{width-right}" y2="485" class="axis"/><line x1="{left}" y1="635" x2="{width-right}" y2="635" class="axis"/>
<text x="14" y="190" class="label">Close</text><text x="14" y="435" class="label">Volume</text><text x="14" y="590" class="label">RSI (14)</text>
<polyline points="{history_points}" class="hist"/>{cutoff_marker}{forecast_band}<polyline points="{forecast_points}" class="forecast"/>
{volume_rects}<line x1="{left}" y1="565" x2="{width-right}" y2="565" class="axis"/><line x1="{left}" y1="605" x2="{width-right}" y2="605" class="axis"/>
<text x="{width-right}" y="568" text-anchor="end" class="label">70</text><text x="{width-right}" y="608" text-anchor="end" class="label">30</text><polyline points="{rsi_points}" class="rsi"/>
{date_labels}</svg>''',
        encoding="utf-8",
    )
    return target


def append_visual_section(report_path: Path, visual_path: Path) -> None:
    relative = visual_path.relative_to(report_path.parent).as_posix()
    with report_path.open("a", encoding="utf-8") as report:
        report.write(f"\n\n## VI. Deterministic Visual Evidence\n\n![KIS market overview]({relative})\n")
