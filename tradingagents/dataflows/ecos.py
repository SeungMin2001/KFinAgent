"""Official Bank of Korea ECOS key-statistics client for Korean macro context."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta

import requests

from .errors import VendorNotConfiguredError

_BASE_URL = "https://ecos.bok.or.kr/api"


@dataclass(frozen=True)
class EcosSeries:
    label: str
    stat_code: str
    cycle: str
    item_code: str


_TARGETS = (
    EcosSeries("한국은행 기준금리", "722Y001", "D", "0101000"),
    EcosSeries("국고채수익률(3년)", "817Y002", "D", "010200000"),
    EcosSeries("국고채수익률(5년)", "817Y002", "D", "010200001"),
    EcosSeries("소비자물가지수", "901Y009", "M", "0"),
    EcosSeries("농산물 및 석유류 제외 소비자물가지수", "901Y010", "M", "QB"),
)


def _time_bounds(as_of: str, cycle: str, lookback_days: int) -> tuple[str, str]:
    end = date.fromisoformat(as_of)
    start = end - timedelta(days=lookback_days)
    fmt = "%Y%m%d" if cycle == "D" else "%Y%m"
    return start.strftime(fmt), end.strftime(fmt)


def _series_rows(key: str, target: EcosSeries, as_of: str, lookback_days: int) -> list[dict]:
    start, end = _time_bounds(as_of, target.cycle, lookback_days)
    url = (
        f"{_BASE_URL}/StatisticSearch/{key}/json/kr/1/1000/"
        f"{target.stat_code}/{target.cycle}/{start}/{end}/{target.item_code}"
    )
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    block = payload.get("StatisticSearch", {})
    rows = block.get("row")
    if not rows:
        raise RuntimeError(f"ECOS returned no observations for {target.label}: {block or payload}")
    total = int(block.get("list_total_count", len(rows)))
    if total > len(rows):
        raise RuntimeError(
            f"ECOS response for {target.label} was truncated ({len(rows)} of {total} rows)"
        )
    # Do not trust API order. Keep only rows whose observation key is within
    # the requested end bound, then choose the latest deterministically.
    rows = [row for row in rows if str(row.get("TIME", "")) <= end]
    rows.sort(key=lambda row: str(row.get("TIME", "")))
    if not rows:
        raise RuntimeError(f"ECOS returned no in-range observations for {target.label} as of {as_of}")
    return rows


def korea_macro_context(as_of: str, lookback_days: int = 400) -> str:
    """Fetch ECOS observations whose reference periods do not exceed ``as_of``."""
    key = os.getenv("ECOS_API_KEY", "").strip()
    if not key:
        raise VendorNotConfiguredError("ECOS_API_KEY is required for Korean macro analysis.")
    lines = [
        "## Bank of Korea ECOS macro snapshot (official)",
        "",
        f"- Requested analysis date: {as_of}",
        "- Observation periods after the requested date are excluded.",
    ]
    for target in _TARGETS:
        rows = _series_rows(key, target, as_of, lookback_days)
        latest = rows[-1]
        previous = rows[-2] if len(rows) > 1 else None
        comparison = ""
        if previous is not None:
            try:
                delta = float(latest["DATA_VALUE"]) - float(previous["DATA_VALUE"])
                comparison = (
                    f", previous {previous['DATA_VALUE']} ({previous['TIME']}), change {delta:+.4f}"
                )
            except (TypeError, ValueError):
                comparison = f", previous {previous['DATA_VALUE']} ({previous['TIME']})"
        lines.append(
            f"- {target.label}: {latest['DATA_VALUE']} {latest.get('UNIT_NAME', '')} "
            f"(observation period {latest['TIME']}, series {target.stat_code}/{target.item_code})"
            f"{comparison}"
        )
    lines += [
        "",
        "ECOS StatisticSearch supplies observation periods but not historical data vintages. "
        "This prevents future-period rows, but later revisions may still appear in a historical run. "
        "Do not describe an observation period as its public release date.",
    ]
    return "\n".join(lines)
