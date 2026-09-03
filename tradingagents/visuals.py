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
    """Write a readable report chart with historical KIS data and forecast separated."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "market_overview.svg"
    bars = market_bars.copy().sort_values("Date").tail(90)
    dates = pd.to_datetime(bars["Date"])
    closes = pd.to_numeric(bars["Close"], errors="raise").tolist()
    volumes = pd.to_numeric(bars["Volume"], errors="raise").tolist()
    forecasts, p10, p90 = _forecast_path(snapshot)

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
    volume_y, _, _ = scaled(volumes, volume_top, volume_bottom, 0, max(volumes) if volumes else 1)

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
    bar_width = max(2, plot_width / max(total_points, 1) * 0.62)
    volume_rects = "".join(
        f'<rect x="{x(i, total_points) - bar_width / 2:.1f}" y="{volume_y[i]:.1f}" width="{bar_width:.1f}" '
        f'height="{volume_bottom - volume_y[i]:.1f}" fill="#7ba7d9" opacity="0.82"/>'
        for i in range(len(volumes))
    )
    forecast_band = ""
    if forecasts and p10 is not None and p90 is not None:
        last_close = closes[-1]
        final_x = x(total_points - 1, total_points)
        band_values = [last_close * (1 + p10 / 100), last_close * (1 + p90 / 100)]
        band_y = [price_y(value) for value in band_values]
        forecast_band = (
            f'<line x1="{final_x:.1f}" y1="{band_y[0]:.1f}" x2="{final_x:.1f}" y2="{band_y[1]:.1f}" '
            'stroke="#e16a5b" stroke-width="8" opacity="0.65"/>'
            f'<text x="{final_x - 10:.1f}" y="{min(band_y) - 10:.1f}" text-anchor="end" class="annotation">p10–p90 range</text>'
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
    future_dots = "".join(
        f'<circle cx="{x(len(closes) + index, total_points):.1f}" cy="{forecast_y[index]:.1f}" r="4.5" class="forecast-dot"/>'
        for index in range(len(forecasts))
    )
    last_close = closes[-1]
    final_forecast = forecast_values[-1] if forecast_values else None
    final_return = (final_forecast / last_close - 1) * 100 if final_forecast is not None else None
    actual_label = f"Observed {last_close:,.0f}"
    forecast_label = "No forecast returned" if final_forecast is None else f"Median {final_forecast:,.0f} KRW  ({final_return:+.2f}%)"
    latest_x = x(len(closes) - 1, total_points)
    latest_y = history_y[-1]
    final_x = x(total_points - 1, total_points) if forecasts else latest_x
    final_y = forecast_y[-1] if forecasts else latest_y
    target.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="KIS historical price and Kronos forecast chart">
<title>KIS historical close and Kronos forecast</title><desc>Observed KIS closing prices are black. The dashed red line is the Kronos median forecast after the cut-off. The red vertical mark is the p10 to p90 range at the final forecast day.</desc>
<style>.bg{{fill:#ffffff}}.title{{font:600 22px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#1a1a1a}}.subtitle{{font:13px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#5b6570}}.panel{{font:600 14px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#1a1a1a}}.axis-label{{font:12px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#5b6570}}.annotation{{font:600 12px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#a63e33}}.window-label{{font:600 11px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#ad6257;letter-spacing:1px}}.grid{{stroke:#e2e5e8;stroke-width:1}}.divider{{stroke:#bfc5ca;stroke-width:1}}.cutoff{{stroke:#606870;stroke-width:1.1;stroke-dasharray:4 4}}.forecast-window{{fill:#fcf5f2}}.hist{{fill:none;stroke:#2b2b2b;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round}}.forecast{{fill:none;stroke:#c64e3b;stroke-width:2.7;stroke-dasharray:7 4;stroke-linecap:round;stroke-linejoin:round}}.actual-dot{{fill:#2b2b2b;stroke:#ffffff;stroke-width:2}}.forecast-dot{{fill:#c64e3b;stroke:#ffffff;stroke-width:2}}</style>
<rect width="{width}" height="{height}" class="bg"/>
<text x="{left}" y="32" class="title">Kronos forecast for KIS closing price</text>
<text x="{left}" y="55" class="subtitle">Input ends {html.escape(dates.iloc[-1].strftime('%Y-%m-%d'))}; forecast horizon = {len(forecasts)} trading days. Prices in KRW.</text>
<text x="{left}" y="92" class="panel">A  |  Observed close and probabilistic forecast</text><text x="{width-right}" y="92" text-anchor="end" class="axis-label">black: observed KIS close · red dashed: Kronos median · red bar: final p10–p90</text>
{price_grid}{cutoff_marker}<polyline points="{history_points}" class="hist"/><polyline points="{forecast_points}" class="forecast"/>{forecast_band}{future_dots}
<circle cx="{latest_x:.1f}" cy="{latest_y:.1f}" r="5" class="actual-dot"/><text x="{latest_x - 10:.1f}" y="{latest_y - 12:.1f}" text-anchor="end" class="annotation">{html.escape(actual_label)}</text>
<circle cx="{final_x:.1f}" cy="{final_y:.1f}" r="5" class="forecast-dot"/><text x="{final_x - 10:.1f}" y="{final_y + 22:.1f}" text-anchor="end" class="annotation">{html.escape(forecast_label)}</text>
<line x1="{left}" y1="{price_bottom}" x2="{width-right}" y2="{price_bottom}" class="divider"/>
<text x="{left}" y="510" class="panel">B  |  Observed daily trading volume</text><text x="{width-right}" y="510" text-anchor="end" class="axis-label">Kronos does not forecast volume in this figure</text>
<line x1="{left}" y1="{volume_bottom}" x2="{width-right}" y2="{volume_bottom}" class="divider"/>{volume_rects}
{date_labels}<text x="{left}" y="706" class="subtitle">The uncertainty mark is only at the final horizon: this workflow receives p10 and p90 only for that endpoint, and it is not a calibrated confidence interval.</text></svg>''',
        encoding="utf-8",
    )
    return target


def append_visual_section(report_path: Path, visual_path: Path) -> None:
    relative = visual_path.relative_to(report_path.parent).as_posix()
    with report_path.open("a", encoding="utf-8") as report:
        report.write(f"\n\n## VI. Deterministic Visual Evidence\n\n![KIS market overview]({relative})\n")
