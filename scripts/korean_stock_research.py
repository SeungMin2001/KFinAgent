"""Run the quotation-only Korean-stock TradingAgents workflow.

Example:
    python scripts/korean_stock_research.py 005930 --date 2026-09-02

It never creates orders.  KIS is used only for adjusted daily OHLCV data.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Allow the documented ``python scripts/korean_stock_research.py ...`` command
# to run from a source checkout without relying on the caller's PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load machine-local credentials/config before importing DEFAULT_CONFIG.
# The source directory may be shared through iCloud, but no absolute path is
# assumed and each Mac can keep its own process environment if desired.
load_dotenv(PROJECT_ROOT / ".env")

from tradingagents.korea import (  # noqa: E402, I001
    create_korean_stock_graph,
    korean_stock_config,
    verify_kis_data_access_with_bars,
)
from tradingagents.dataflows.korean_evidence import enhanced_korean_evidence  # noqa: E402, I001
from tradingagents.dataflows.kronos import KronosSettings  # noqa: E402, I001


STAGE_LABELS = {
    "Disclosure Evidence Analyst": "공시 근거 정규화",
    "Macro Evidence Analyst": "거시 근거 정규화",
    "Flow Evidence Analyst": "수급 근거 정규화",
    "Time-Series Forecast Evidence Analyst": "Kronos 시계열 예측 근거 정규화",
    "Market Analyst": "시장 종합 분석",
    "Bull Researcher": "상승 관점 토론",
    "Bear Researcher": "하락 관점 토론",
    "Research Manager": "토론 정리 및 투자 가설 결정",
    "Trader": "트레이더 실행 관점 검토",
    "Aggressive Analyst": "리스크 토론 — 공격적 관점",
    "Neutral Analyst": "리스크 토론 — 중립적 관점",
    "Conservative Analyst": "리스크 토론 — 보수적 관점",
    "Portfolio Manager": "최종 리스크 판단 및 신호 산출",
}


def stage_result(stage: str, result: dict[str, Any]) -> str:
    """Return the newly produced text for the named agent stage."""
    direct_fields = {
        "Disclosure Evidence Analyst": "disclosure_report",
        "Macro Evidence Analyst": "macro_report",
        "Flow Evidence Analyst": "flow_report",
        "Time-Series Forecast Evidence Analyst": "kronos_report",
        "Market Analyst": "market_report",
        "Research Manager": "investment_plan",
        "Trader": "trader_investment_plan",
        "Portfolio Manager": "final_trade_decision",
    }
    if field := direct_fields.get(stage):
        return str(result.get(field, "")).strip()

    debate = result.get("investment_debate_state", {})
    risk = result.get("risk_debate_state", {})
    debate_fields = {
        "Bull Researcher": "current_response",
        "Bear Researcher": "current_response",
    }
    risk_fields = {
        "Aggressive Analyst": "current_aggressive_response",
        "Neutral Analyst": "current_neutral_response",
        "Conservative Analyst": "current_conservative_response",
    }
    if field := debate_fields.get(stage):
        return str(debate.get(field, "")).strip()
    if field := risk_fields.get(stage):
        return str(risk.get(field, "")).strip()
    return ""


def make_progress_printer(verbose: bool):
    def print_stage(event: str, stage: str, result: dict[str, Any] | None) -> None:
        if event == "started":
            print(f"\n[진행] {STAGE_LABELS.get(stage, stage)}", flush=True)
            return
        if verbose and result:
            text = stage_result(stage, result)
            if text:
                print(f"[결과 · {stage}]\n{text}\n", flush=True)

    return print_stage


def write_evidence_manifest(
    report_path: Path, symbol: str, analysis_date: str, snapshot: str, enhanced: bool, kronos_enabled: bool
) -> Path:
    """Save every factual input supplied to the agent workflow beside its report."""
    source_list = ["KIS 일봉 OHLCV·기술지표"]
    if enhanced:
        source_list.extend(
            [
                "OpenDART 최근 공시",
                "FRED 미국 매크로(금리·CPI·국채·달러·VIX)",
                "한국은행 ECOS 보조 매크로",
                "KIS 투자자별 수급(외국인·기관계·투신·기금)",
            ]
        )
    if kronos_enabled:
        source_list.append("Kronos-base 시계열 예측(검증된 KIS 일봉 입력)")
    sources = "\n".join(f"- {item}" for item in source_list)
    text = f"""# Evidence Manifest — {symbol}

- Analysis date: {analysis_date}
- Enhanced evidence mode: {enhanced}
- This file is the immutable factual snapshot collected before any LLM analysis.

## Collected sources

{sources}

## Agent evidence path

- In enhanced mode, Disclosure / Macro / Flow Evidence Analysts each receive only their assigned snapshot sections.
- When Kronos is enabled, the Time-Series Forecast Evidence Analyst receives only the model-input and forecast section.
- Their normalized reports are saved under `1_analysts/`.
- Market Agent receives verified price/technical data plus all enabled evidence reports and produces `1_analysts/market.md`.
- Bull / Bear / Research Manager / Trader / Risk / Portfolio Manager: receive the Market Agent report and debate outputs downstream.
- No order or account API is used.

## Complete source-attributed snapshot

{snapshot}
"""
    # TradingAgents.save_reports() returns complete_report.md, not its parent
    # directory. Keep the manifest alongside that file.
    target = report_path.parent / "0_evidence.md"
    target.write_text(text, encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="KIS-based Korean stock research (no order execution).")
    parser.add_argument("symbol", help="Six-digit KRX stock code, e.g. 005930")
    parser.add_argument("--date", default=date.today().isoformat(), help="Analysis date (YYYY-MM-DD)")
    parser.add_argument("--model", help="Override the LLM used for both research and quick steps")
    parser.add_argument("--debug", action="store_true", help="Print LangGraph messages while running")
    parser.add_argument("--verbose", action="store_true", help="Print each agent's completed analysis and debate output")
    parser.add_argument("--enhanced", action="store_true", help="Require DART, FRED, ECOS, and KIS investor-flow evidence")
    parser.add_argument(
        "--kronos-mode",
        choices=("disabled", "local", "remote"),
        default=None,
        help="Kronos mode. Defaults to KRONOS_MODE in .env; remote/local failures stop the run.",
    )
    parser.add_argument(
        "--kronos-horizon",
        type=int,
        default=5,
        help="Kronos forecast horizon in business-day timestamps (1-30, default: 5)",
    )
    args = parser.parse_args()

    if not args.symbol.isdigit() or len(args.symbol) != 6:
        parser.error("symbol must be a six-digit KRX code, for example 005930")

    try:
        kronos_mode = KronosSettings.from_env(args.kronos_mode).mode
    except Exception as exc:  # noqa: BLE001 - explicit configuration must fail before market collection
        parser.exit(2, f"Kronos configuration failed; analysis was not started: {exc}\n")
    if kronos_mode != "disabled" and not args.enhanced:
        parser.error("Kronos evidence requires --enhanced so its output is normalized before debate.")
    if not 1 <= args.kronos_horizon <= 30:
        parser.error("--kronos-horizon must be between 1 and 30")

    overrides = {
        "kronos_mode": kronos_mode,
        "kronos_horizon": args.kronos_horizon,
        "enable_kronos_evidence_agent": kronos_mode != "disabled",
    }
    if args.model:
        overrides.update({"deep_think_llm": args.model, "quick_think_llm": args.model})

    try:
        # Do this before constructing/running the agent workflow.  There is no
        # fixture, cached quote, or secondary provider on this path.
        snapshot, market_bars = verify_kis_data_access_with_bars(args.symbol, args.date, overrides)
    except Exception as exc:  # noqa: BLE001 - show the live KIS failure clearly to CLI users
        parser.exit(2, f"KIS live data verification failed; analysis was not started: {exc}\n")

    latest_row = next(line for line in snapshot.splitlines() if line.startswith("- Latest trading row used:"))
    print("[진행] 1/6 KIS 실캔들 조회 및 데이터 검증 완료", flush=True)
    print(latest_row, flush=True)

    if args.enhanced:
        try:
            snapshot = enhanced_korean_evidence(
                args.symbol,
                args.date,
                snapshot,
                config=korean_stock_config(overrides),
                market_bars=market_bars,
            )
        except Exception as exc:  # noqa: BLE001 - enhanced mode is deliberately strict
            parser.exit(2, f"Enhanced evidence collection failed; analysis was not started: {exc}\n")
        print("[진행] DART·미국/한국 매크로·KIS 수급 검증 완료", flush=True)
        if kronos_mode != "disabled":
            print("[진행] Kronos 예측 수신 및 시계열 근거 검증 완료", flush=True)

    graph = create_korean_stock_graph(
        {**overrides, "enable_korean_evidence_agents": args.enhanced},
        debug=args.debug,
        progress_callback=make_progress_printer(args.verbose),
    )
    state, signal = graph.propagate(
        args.symbol,
        args.date,
        verified_market_snapshot=snapshot,
    )
    path = graph.save_reports(state, args.symbol)
    evidence_path = write_evidence_manifest(
        path, args.symbol, args.date, snapshot, args.enhanced, kronos_mode != "disabled"
    )

    print(f"Final signal: {signal}")
    print(f"Report written to: {path}")
    print(f"Evidence manifest written to: {evidence_path}")


if __name__ == "__main__":
    main()
