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


def _forecast_path(
    snapshot: str,
) -> tuple[list[tuple[pd.Timestamp, float]], list[tuple[pd.Timestamp, float]], float | None, float | None]:
    """Extract the median close and volume paths rendered in the evidence table."""
    price_rows: list[tuple[pd.Timestamp, float]] = []
    volume_rows: list[tuple[pd.Timestamp, float]] = []
    in_table = False
    for line in snapshot.splitlines():
        if line.strip() == "### Median forecast path":
            in_table = True
            continue
        if in_table and line.startswith("### "):
            break
        if in_table and line.startswith("|") and "T" in line:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 6:
                try:
                    timestamp = pd.Timestamp(cells[0])
                    price_rows.append((timestamp, float(cells[4])))
                    volume_rows.append((timestamp, float(cells[5])))
                except (TypeError, ValueError):
                    continue
    range_match = re.search(
        r"Final-return range \(p10 / p50 / p90\):\s*([-+0-9.]+)% / [-+0-9.]+% / ([-+0-9.]+)%",
        snapshot,
    )
    if not range_match:
        return price_rows, volume_rows, None, None
    return price_rows, volume_rows, float(range_match.group(1)), float(range_match.group(2))


def write_market_overview_svg(output_dir: Path, market_bars: pd.DataFrame, snapshot: str) -> Path:
    """Write a readable report chart with historical KIS data and forecast separated."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "market_overview.svg"
    bars = market_bars.copy().sort_values("Date").tail(90)
    dates = pd.to_datetime(bars["Date"])
    closes = pd.to_numeric(bars["Close"], errors="raise").tolist()
    volumes = pd.to_numeric(bars["Volume"], errors="raise").tolist()
    forecasts, forecast_volumes, p10, p90 = _forecast_path(snapshot)

    width, height = 1200, 720
    left, right = 92, 48
    plot_width = width - left - right
    price_top, price_bottom = 122, 440
    volume_top, volume_bottom = 535, 638

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
    _, price_low, price_high = scaled(closes + forecast_values + terminal_range, price_top, price_bottom)

    def price_y(value: float) -> float:
        return price_bottom - ((value - price_low) / (price_high - price_low)) * (price_bottom - price_top)

    history_y = [price_y(value) for value in closes]
    forecast_y = [price_y(value) for value in forecast_values]
    forecast_volume_values = [value for _, value in forecast_volumes]
    volume_y, volume_low, volume_high = scaled(
        volumes + forecast_volume_values,
        volume_top,
        volume_bottom,
        0,
        max(volumes + forecast_volume_values) if volumes or forecast_volume_values else 1,
    )

    def volume_scale(value: float) -> float:
        return volume_bottom - ((value - volume_low) / (volume_high - volume_low)) * (volume_bottom - volume_top)

    observed_volume_y = volume_y[:len(volumes)]
    forecast_volume_y = [volume_scale(value) for value in forecast_volume_values]

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
    volume_history_points = " ".join(
        f"{x(i, total_points):.1f},{observed_volume_y[i]:.1f}" for i in range(len(volumes))
    )
    forecast_volume_points = ""
    if forecast_volumes:
        forecast_volume_points = " ".join(
            [f"{x(len(closes) - 1, total_points):.1f},{observed_volume_y[-1]:.1f}"]
            + [
                f"{x(len(closes) + i, total_points):.1f},{forecast_volume_y[i]:.1f}"
                for i in range(len(forecast_volumes))
            ]
        )
    date_label_items = [(0, dates.iloc[0]), (len(closes) // 2, dates.iloc[len(closes) // 2]), (len(closes) - 1, dates.iloc[-1])]
    if forecasts:
        date_label_items.append((total_points - 1, forecasts[-1][0]))
    date_labels = "".join(
        f'<text x="{x(index, total_points):.1f}" y="676" text-anchor="middle" class="axis-label">{html.escape(pd.Timestamp(date).strftime("%b %-d"))}</text>'
        for index, date in date_label_items
    )
    cutoff_x = x(len(closes) - 1, total_points)
    cutoff_marker = ""
    if forecasts:
        cutoff_marker = (
            f'<rect x="{cutoff_x:.1f}" y="{price_top}" width="{width-right-cutoff_x:.1f}" height="{price_bottom-price_top}" class="forecast-window"/>'
            f'<line x1="{cutoff_x:.1f}" y1="{price_top}" x2="{cutoff_x:.1f}" y2="{price_bottom}" class="cutoff"/>'
            f'<text x="{cutoff_x + 12:.1f}" y="{price_top + 22}" class="window-label">FORECAST WINDOW</text>'
        )
    price_ticks = [price_low + (price_high - price_low) * fraction for fraction in (0.0, 1 / 3, 2 / 3, 1.0)]
    price_grid = "".join(
        f'<line x1="{left}" y1="{price_y(tick):.1f}" x2="{width-right}" y2="{price_y(tick):.1f}" class="grid"/>'
        f'<text x="{left - 12}" y="{price_y(tick) + 4:.1f}" text-anchor="end" class="axis-label">{tick:,.0f}</text>'
        for tick in price_ticks
    )
    target.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="KIS historical close and volume with Kronos forecast chart">
<title>Kronos-style KIS close and volume forecast</title><desc>In the style of the official Kronos example: blue solid lines are observed KIS close and volume, and red solid lines are the Kronos median forecasts after the input cut-off.</desc>
<style>.bg{{fill:#ffffff}}.title{{font:18px DejaVu Sans,Arial,sans-serif;fill:#111}}.axis-label{{font:12px DejaVu Sans,Arial,sans-serif;fill:#333}}.tick{{font:11px DejaVu Sans,Arial,sans-serif;fill:#333}}.legend{{font:12px DejaVu Sans,Arial,sans-serif;fill:#222}}.grid{{stroke:#b0b0b0;stroke-width:.8;stroke-dasharray:2 2;opacity:.7}}.divider{{stroke:#333;stroke-width:1}}.cutoff{{stroke:#777;stroke-width:1;stroke-dasharray:4 3}}.forecast-window{{fill:#ffffff}}.window-label{{font:11px DejaVu Sans,Arial,sans-serif;fill:#555}}.hist{{fill:none;stroke:#1f77b4;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}}.forecast{{fill:none;stroke:#d62728;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}}.forecast-volume{{fill:none;stroke:#d62728;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}}</style>
<rect width="{width}" height="{height}" class="bg"/>
<text x="{left}" y="35" class="title">Kronos Prediction — KIS daily candles</text>
<text x="{left}" y="58" class="axis-label">Close Price (KRW)</text>
{price_grid}{cutoff_marker}<polyline points="{history_points}" class="hist"/><polyline points="{forecast_points}" class="forecast"/>
<line x1="{left + 14}" y1="{price_bottom - 38}" x2="{left + 42}" y2="{price_bottom - 38}" class="hist"/><text x="{left + 50}" y="{price_bottom - 34}" class="legend">Ground Truth (KIS)</text>
<line x1="{left + 14}" y1="{price_bottom - 18}" x2="{left + 42}" y2="{price_bottom - 18}" class="forecast"/><text x="{left + 50}" y="{price_bottom - 14}" class="legend">Prediction (Kronos median)</text>
<line x1="{left}" y1="{price_bottom}" x2="{width-right}" y2="{price_bottom}" class="divider"/>
<text x="{left}" y="486" class="axis-label">Volume</text>
<line x1="{left}" y1="{volume_top}" x2="{width-right}" y2="{volume_top}" class="grid"/><line x1="{left}" y1="{(volume_top + volume_bottom) / 2:.1f}" x2="{width-right}" y2="{(volume_top + volume_bottom) / 2:.1f}" class="grid"/>
<polyline points="{volume_history_points}" class="hist"/><polyline points="{forecast_volume_points}" class="forecast-volume"/>
<line x1="{left + 14}" y1="{volume_top + 22}" x2="{left + 42}" y2="{volume_top + 22}" class="hist"/><text x="{left + 50}" y="{volume_top + 26}" class="legend">Ground Truth (KIS)</text>
<line x1="{left + 14}" y1="{volume_top + 42}" x2="{left + 42}" y2="{volume_top + 42}" class="forecast"/><text x="{left + 50}" y="{volume_top + 46}" class="legend">Prediction (Kronos median)</text>
<line x1="{left}" y1="{volume_bottom}" x2="{width-right}" y2="{volume_bottom}" class="divider"/>
{date_labels}<text x="{left}" y="706" class="tick">Blue: verified KIS observations · Red: Kronos median forecast · vertical line: input cut-off. Price uncertainty and volume uncertainty remain in the evidence table.</text></svg>''',
        encoding="utf-8",
    )
    return target


def append_visual_section(report_path: Path, visual_path: Path) -> None:
    relative = visual_path.relative_to(report_path.parent).as_posix()
    with report_path.open("a", encoding="utf-8") as report:
        report.write(f"\n\n## VI. Deterministic Visual Evidence\n\n![KIS market overview]({relative})\n")
