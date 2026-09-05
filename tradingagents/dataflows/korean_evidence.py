"""Point-in-time Korean equity evidence snapshot assembled before LLM analysis."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from .dart import disclosure_context, periodic_fundamentals_context
from .ecos import korea_macro_context
from .evidence_snapshot import read_snapshot
from .global_risk import global_risk_context
from .kis import KisInvestorFlowTimeWindowError, get_kis_investor_flow, get_kis_news_titles
from .kronos import (
    PAPER_DAILY_HORIZON,
    PAPER_DAILY_LOOKBACK,
    PAPER_FORECAST_SAMPLES,
    PAPER_FORECAST_TEMPERATURE,
    PAPER_FORECAST_TOP_P,
    forecast_kronos,
)
from .us_macro import us_macro_context

_FLOW_FIELDS = {
    "frgn_ntby_qty": "외국인",
    "orgn_ntby_qty": "기관계",
    "ivtr_ntby_qty": "투자신탁",
    "fund_ntby_qty": "기금",
}


def evidence_sections(snapshot: str) -> dict[str, str]:
    """Split a combined snapshot at level-two Markdown headings.

    The enhanced collector deliberately produces one immutable evidence blob.
    Domain agents use this deterministic splitter so each one sees only its
    assigned source material rather than relying on an LLM to ignore unrelated
    sections.
    """
    sections: dict[str, list[str]] = {}
    current = ""
    for line in snapshot.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = [line]
        elif current:
            sections[current].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def evidence_for_domain(snapshot: str, domain: str) -> str:
    """Return only the verified snapshot sections assigned to ``domain``."""
    selectors = {
        "market": ("Verified market data snapshot", "Deterministic chart summary"),
        "disclosure": ("OpenDART disclosures", "KIS market/disclosure headline snapshot"),
        "fundamentals": ("OpenDART disclosures", "OpenDART periodic fundamentals"),
        "macro": ("US macro snapshot", "FRED:", "Bank of Korea ECOS macro snapshot", "Japan monetary conditions", "Geopolitical news evidence"),
        "flow": ("KIS investor flow snapshot",),
        "kronos": ("Kronos forecast snapshot",),
    }
    if domain not in selectors:
        raise ValueError(f"unknown Korean evidence domain: {domain}")
    matches = [
        body
        for heading, body in evidence_sections(snapshot).items()
        if any(heading.startswith(prefix) for prefix in selectors[domain])
    ]
    return "\n\n".join(matches)


def _consecutive_sign(values: pd.Series) -> int:
    sign = 1 if values.iloc[-1] > 0 else -1 if values.iloc[-1] < 0 else 0
    if sign == 0:
        return 0
    count = 0
    for value in reversed(values.tolist()):
        if (value > 0 and sign > 0) or (value < 0 and sign < 0):
            count += 1
        else:
            break
    return count * sign


def investor_flow_context(
    symbol: str,
    as_of: str,
    *,
    short_window: int = 5,
    long_window: int = 20,
) -> str:
    if short_window < 1 or long_window < short_window:
        raise ValueError("flow windows must satisfy 1 <= short_window <= long_window")
    requested = datetime.strptime(as_of, "%Y-%m-%d").date()
    query_date = requested
    try:
        frame = get_kis_investor_flow(symbol, query_date.isoformat())
    except KisInvestorFlowTimeWindowError:
        if requested != date.today():
            raise
        # The finalized daily flow endpoint opens after the market's KIS cutoff.
        # Retry only earlier weekdays; never replace the result with estimates.
        for offset in range(1, 8):
            candidate = requested - timedelta(days=offset)
            if candidate.weekday() >= 5:
                continue
            try:
                frame = get_kis_investor_flow(symbol, candidate.isoformat())
                query_date = candidate
                break
            except KisInvestorFlowTimeWindowError:
                continue
        else:
            raise RuntimeError("KIS finalized investor flow was unavailable for the prior 7 calendar days")

    actual_latest = frame.attrs.get("latest_date", frame.index[-1].date().isoformat())
    frame = frame.tail(long_window).copy()
    lines = [
        "## KIS investor flow snapshot (official)",
        "",
        f"- Requested analysis date: {as_of}",
        f"- KIS flow query date: {query_date.isoformat()}",
        f"- Latest completed flow row used: {actual_latest}",
    ]
    if query_date != requested:
        lines.append("- Availability note: 당일 확정 수급 공개 전이므로 직전 완료 거래일의 실제 KIS 데이터를 사용함")
    for field, label in _FLOW_FIELDS.items():
        if field not in frame:
            raise RuntimeError(f"KIS investor-flow response is missing {field}")
        values = pd.to_numeric(frame[field], errors="coerce").dropna()
        if values.empty:
            raise RuntimeError(f"KIS investor-flow response has no numeric values for {field}")
        streak = _consecutive_sign(values)
        direction = "연속 순매수" if streak > 0 else "연속 순매도" if streak < 0 else "보합"
        recent_short = values.tail(short_window)
        lines.append(
            f"- {label}: 최근 {len(recent_short)}일 누적 순매수 {recent_short.sum():,.0f}주, "
            f"최근 {len(values)}일 누적 순매수 {values.sum():,.0f}주, "
            f"최근 {abs(streak)}일 {direction}"
        )
    lines += ["", "수급은 인과관계가 아닌 관측값이다. 가격·공시·매크로와 충돌하면 충돌을 명시한다."]
    return "\n".join(lines)


def kis_headline_context(symbol: str, as_of: str, *, limit: int = 20) -> str:
    """Render KIS title metadata without pretending it contains article text."""
    rows = get_kis_news_titles(symbol, as_of, limit=limit)
    lines = [
        "## KIS market/disclosure headline snapshot (official HTS title metadata)",
        "",
        f"- Requested analysis date: {as_of}",
        f"- Symbol-filtered headlines retained: {len(rows)} (limit {limit})",
        "- This source supplies titles and metadata only. It does not supply article bodies, causes, or verified event details.",
    ]
    if not rows:
        lines.append("- No qualifying KIS headline row was returned for this query.")
        return "\n".join(lines)
    lines += ["", "| Published | Source | Category | Title |", "|---|---|---|---|"]
    for row in rows:
        timestamp = f"{row.get('data_dt', '')} {row.get('data_tm', '')}".strip()
        source = str(row.get("dorg", "")).strip() or str(row.get("news_ofer_entp_code", "")).strip() or "not provided"
        category = str(row.get("news_lrdv_code", "")).strip() or "not provided"
        title = str(row.get("hts_pbnt_titl_cntt", "")).replace("|", "\\|").strip()
        lines.append(f"| {timestamp} | {source} | {category} | {title} |")
    lines += [
        "",
        "Limitations: Headline wording is not a factual substitute for the linked article or an official filing. "
        "Use it to flag topics for scrutiny; do not infer event timing, magnitude, or trade direction from a title alone.",
    ]
    return "\n".join(lines)


def kronos_forecast_context(
    symbol: str,
    market_bars: pd.DataFrame,
    *,
    horizon: int = PAPER_DAILY_HORIZON,
    mode: str | None = None,
    lookback: int = PAPER_DAILY_LOOKBACK,
    temperature: float = PAPER_FORECAST_TEMPERATURE,
    top_p: float = PAPER_FORECAST_TOP_P,
    samples: int = PAPER_FORECAST_SAMPLES,
) -> str:
    """Render one source-attributed forecast from the configured Kronos API.

    ``market_bars`` must be the exact KIS rows used for the verified market
    snapshot. No second KIS request or synthetic candle is allowed here.
    """
    required = {"Date", "Open", "High", "Low", "Close", "Volume", "Amount"}
    missing = sorted(required - set(market_bars.columns))
    if missing:
        raise RuntimeError("Verified KIS bars are missing required Kronos fields: " + ", ".join(missing))
    bars = market_bars.rename(
        columns={
            "Date": "date", "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume", "Amount": "amount",
        }
    ).set_index("date")
    history = bars.tail(lookback)
    result = forecast_kronos(
        symbol, bars, horizon=horizon, mode=mode, lookback=lookback,
        temperature=temperature, top_p=top_p, samples=samples,
    )
    close = pd.to_numeric(history["close"], errors="raise")
    volume = pd.to_numeric(history["volume"], errors="raise")

    def trailing_return(days: int) -> float | None:
        if len(close) <= days:
            return None
        return float((close.iloc[-1] / close.iloc[-days - 1] - 1) * 100)

    def fmt_percent(value: float | None) -> str:
        return "not available" if value is None else f"{value:.4f}%"

    volatility_20 = close.pct_change().tail(20).std(ddof=1)
    volume_ratio = volume.tail(5).mean() / volume.tail(20).mean() if len(volume) >= 20 and volume.tail(20).mean() else None
    final_median_volume = float(result["median_path"][-1]["volume"])
    latest_volume = float(volume.iloc[-1])
    volume_change = (final_median_volume / latest_volume - 1) * 100 if latest_volume else None
    lines = [
        "## Kronos forecast snapshot (model output)",
        "",
        f"- Source model: {result['model_id']}",
        f"- Generated at: {result['generated_at']}",
        f"- Input symbol: {result['symbol']}",
        f"- Input end date: {result['input_end_date']}",
        f"- Verified KIS daily bars supplied: {len(history)}",
        f"- Forecast horizon: {horizon} business-day timestamps",
        f"- Inference sampling: temperature={temperature:.1f}, top_p={top_p:.1f}, paths={samples}",
        f"- Last observed close: {result['last_close']:,.2f}",
        "",
        "### Observable conditions in the candle input (not model causal attribution)",
        "",
        f"- Trailing 5-trading-day close return: {fmt_percent(trailing_return(5))}",
        f"- Trailing 20-trading-day close return: {fmt_percent(trailing_return(20))}",
        f"- Trailing 60-trading-day close return: {fmt_percent(trailing_return(60))}",
        f"- Last-20 daily-return standard deviation: {fmt_percent(float(volatility_20 * 100) if pd.notna(volatility_20) else None)}",
        f"- Recent-volume ratio (5-day mean / 20-day mean): "
        f"{'not available' if volume_ratio is None else f'{volume_ratio:.4f}x'}",
        "- These are deterministic summaries of the candles sent to Kronos. They are not attention weights, "
        "feature importance, or a causal explanation of the model output.",
        "",
        "### Kronos forecast output",
        "",
        f"- Median-path expected return: {result['expected_return_pct']:.4f}%",
        f"- Sample upside frequency: {result['upside_probability']:.4f}",
        f"- Final-return range (p10 / p50 / p90): {result['return_p10_pct']:.4f}% / "
        f"{result['return_p50_pct']:.4f}% / {result['return_p90_pct']:.4f}%",
        f"- Cross-sample uncertainty (standard deviation): {result['uncertainty_pct']:.4f}%",
        f"- Final-horizon median forecast volume: {final_median_volume:,.0f} "
        f"({volume_change:+.2f}% versus the latest observed volume)" if volume_change is not None
        else f"- Final-horizon median forecast volume: {final_median_volume:,.0f}",
        "- Volume has a median forecast path only. No volume quantiles or calibrated uncertainty interval are returned.",
        "",
        "### Median forecast path",
        "",
        "| Timestamp | Open | High | Low | Close | Volume |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in result["median_path"]:
        lines.append(
            f"| {row['timestamp']} | {row['open']:.2f} | {row['high']:.2f} | "
            f"{row['low']:.2f} | {row['close']:.2f} | {row['volume']:.0f} |"
        )
    lines += [
        "",
        "Limitations: This is a probabilistic model output, not a calibrated probability, investment "
        "recommendation, target price, or causal explanation. It has not yet been walk-forward validated "
        "for this Korean-market workflow. Reconcile it with observed KIS, DART, macro, and flow evidence.",
    ]
    return "\n".join(lines)


def enhanced_korean_evidence(
    symbol: str,
    as_of: str,
    market_snapshot: str,
    *,
    config: dict | None = None,
    market_bars: pd.DataFrame | None = None,
) -> str:
    """Strictly build the full source-attributed input used by enhanced research."""
    settings = config or {}
    sections = [
            market_snapshot,
            disclosure_context(
                symbol,
                as_of,
                lookback_days=int(settings.get("korean_disclosure_lookback_days", 45)),
                limit=int(settings.get("korean_disclosure_limit", 3)),
                compact=bool(settings.get("korean_dart_compact", True)),
            ),
            us_macro_context(
                as_of,
                lookback_days=int(settings.get("korean_us_macro_lookback_days", 370)),
            ),
            korea_macro_context(
                as_of,
                lookback_days=int(settings.get("korean_ecos_lookback_days", 400)),
            ),
            investor_flow_context(
                symbol,
                as_of,
                short_window=int(settings.get("korean_flow_short_window", 5)),
                long_window=int(settings.get("korean_flow_long_window", 20)),
            ),
            kis_headline_context(
                symbol,
                as_of,
                limit=int(settings.get("korean_headline_limit", 20)),
            ),
        ]
    if settings.get("enable_global_risk", False):
        snapshot_dir = settings.get("global_risk_snapshot_dir")
        sections.append(read_snapshot(snapshot_dir, as_of) if snapshot_dir else global_risk_context(as_of))
    if settings.get("enable_periodic_fundamentals", True):
        sections.append(periodic_fundamentals_context(
            symbol, as_of, compact=bool(settings.get("korean_dart_compact", True))
        ))
    kronos_mode = str(settings.get("kronos_mode", "disabled"))
    if kronos_mode != "disabled":
        if market_bars is None:
            raise RuntimeError("Kronos evidence requires the verified KIS bars from preflight")
        sections.append(
            kronos_forecast_context(
                symbol,
                market_bars,
                horizon=int(settings.get("kronos_horizon", PAPER_DAILY_HORIZON)),
                mode=kronos_mode,
                lookback=int(settings.get("kronos_lookback", PAPER_DAILY_LOOKBACK)),
                temperature=float(settings.get("kronos_temperature", PAPER_FORECAST_TEMPERATURE)),
                top_p=float(settings.get("kronos_top_p", PAPER_FORECAST_TOP_P)),
                samples=int(settings.get("kronos_samples", PAPER_FORECAST_SAMPLES)),
            )
        )
    return "\n\n".join(sections)
