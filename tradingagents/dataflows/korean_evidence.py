"""Point-in-time Korean equity evidence snapshot assembled before LLM analysis."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from .dart import disclosure_context
from .ecos import korea_macro_context
from .kis import KisInvestorFlowTimeWindowError, get_kis_investor_flow
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
        "market": ("Verified market data snapshot",),
        "disclosure": ("OpenDART disclosures",),
        "macro": ("US macro snapshot", "FRED:", "Bank of Korea ECOS macro snapshot"),
        "flow": ("KIS investor flow snapshot",),
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


def enhanced_korean_evidence(
    symbol: str,
    as_of: str,
    market_snapshot: str,
    *,
    config: dict | None = None,
) -> str:
    """Strictly build the full source-attributed input used by enhanced research."""
    settings = config or {}
    return "\n\n".join(
        [
            market_snapshot,
            disclosure_context(
                symbol,
                as_of,
                lookback_days=int(settings.get("korean_disclosure_lookback_days", 45)),
                limit=int(settings.get("korean_disclosure_limit", 3)),
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
        ]
    )
