"""Run the read-only, account-aware Korean-stock TradingAgents workflow.

Example:
    python scripts/korean_stock_research.py 005930 --date 2026-09-02

It never creates orders. KIS is used for market data and an optional read-only
domestic-stock balance lookup.
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
from tradingagents.dataflows.kis import get_kis_account_snapshot  # noqa: E402, I001
from tradingagents.report_history import load_prior_report_context  # noqa: E402, I001
from tradingagents.visuals import (  # noqa: E402, I001
    append_visual_section,
    build_visual_summary,
    write_market_overview_svg,
)
from tradingagents.reporting import write_final_brief  # noqa: E402, I001


STAGE_LABELS = {
    "Disclosure Evidence Analyst": "공시·KIS 시황 헤드라인 근거 정규화",
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
    report_path: Path,
    symbol: str,
    analysis_date: str,
    snapshot: str,
    enhanced: bool,
    kronos_enabled: bool,
    account_enabled: bool,
    account_snapshot: str,
    historical_report_context: str,
) -> Path:
    """Save every factual input supplied to the agent workflow beside its report."""
    source_list = ["KIS 일봉 OHLCV·기술지표"]
    if enhanced:
        source_list.extend(
            [
                "OpenDART 최근 공시",
                "KIS 종합 시황/공시 제목(종목 연관 헤드라인)",
                "FRED 미국 매크로(금리·CPI·국채·달러·VIX)",
                "한국은행 ECOS 보조 매크로",
                "KIS 투자자별 수급(외국인·기관계·투신·기금)",
            ]
        )
    if kronos_enabled:
        source_list.append("Kronos-base 시계열 예측(검증된 KIS 일봉 입력)")
    if account_enabled:
        source_list.append("KIS 국내주식 잔고조회(계좌번호 비식별 요약)")
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
- All debate and decision agents receive the read-only account context. Its target-position constraint distinguishes a true Hold from a no-position Watch / No entry.
- No order API is used. The account endpoint only reads balance data.

## Read-only account context

{account_snapshot if account_enabled else "- Account-aware mode disabled; this report contains no live account data."}

## Prior report references consulted before debate

{historical_report_context}

## Visual evidence

- [KIS market overview and Kronos forecast](visuals/market_overview.svg)
- The chart is rendered from the same verified KIS candles and Kronos output used in this snapshot.

## Complete source-attributed snapshot

{snapshot}
"""
    # TradingAgents.save_reports() returns complete_report.md, not its parent
    # directory. Keep the manifest alongside that file.
    target = report_path.parent / "0_evidence.md"
    target.write_text(text, encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="KIS-based Korean stock research with read-only account context (no order execution).")
    parser.add_argument("symbol", help="Six-digit KRX stock code, e.g. 005930")
    parser.add_argument("--date", default=date.today().isoformat(), help="Analysis date (YYYY-MM-DD)")
    parser.add_argument("--model", help="Override the LLM used for both research and quick steps")
    parser.add_argument("--debug", action="store_true", help="Print LangGraph messages while running")
    parser.add_argument("--verbose", action="store_true", help="Print each agent's completed analysis and debate output")
    parser.add_argument("--enhanced", action="store_true", help="Require DART, FRED, ECOS, and KIS investor-flow evidence")
    parser.add_argument(
        "--account-mode",
        choices=("required", "disabled"),
        default="required",
        help="Require a live, read-only KIS domestic-stock balance snapshot (default: required).",
    )
    parser.add_argument(
        "--kronos-mode",
        choices=("disabled", "local", "remote"),
        default=None,
        help="Kronos mode. Defaults to KRONOS_MODE in .env; remote/local failures stop the run.",
    )
    parser.add_argument(
        "--kronos-horizon",
        type=int,
        default=12,
        help="Kronos forecast horizon in business-day timestamps (1-30, default: 12; paper daily protocol)",
    )
    parser.add_argument(
        "--kronos-lookback",
        type=int,
        default=40,
        help="Historical daily K-lines sent to Kronos (30-512, default: 40; paper daily protocol)",
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
    if not 30 <= args.kronos_lookback <= 512:
        parser.error("--kronos-lookback must be between 30 and 512")
    if args.account_mode == "required" and args.date != date.today().isoformat():
        parser.error(
            "Account-aware research only supports today's --date because KIS balance lookup is live, not historical. "
            "Use today's date or pass --account-mode disabled for retrospective research."
        )

    overrides = {
        "kronos_mode": kronos_mode,
        "kronos_horizon": args.kronos_horizon,
        "kronos_lookback": args.kronos_lookback,
        "enable_kronos_evidence_agent": kronos_mode != "disabled",
    }
    if args.model:
        overrides.update({"deep_think_llm": args.model, "quick_think_llm": args.model})

    try:
        # Do this before constructing/running the agent workflow.  There is no
        # fixture, cached quote, or secondary provider on this path.
        snapshot, market_bars = verify_kis_data_access_with_bars(args.symbol, args.date, overrides)
        snapshot = f"{snapshot}\n\n{build_visual_summary(market_bars)}"
    except Exception as exc:  # noqa: BLE001 - show the live KIS failure clearly to CLI users
        parser.exit(2, f"KIS live data verification failed; analysis was not started: {exc}\n")

    latest_row = next(line for line in snapshot.splitlines() if line.startswith("- Latest trading row used:"))
    print("[진행] 1/7 KIS 실캔들 조회 및 데이터 검증 완료", flush=True)
    print(latest_row, flush=True)

    account_snapshot = ""
    if args.account_mode == "required":
        try:
            account_snapshot = get_kis_account_snapshot(args.symbol)
        except Exception as exc:  # noqa: BLE001 - account-aware mode is deliberately strict
            parser.exit(2, f"KIS live account-balance verification failed; analysis was not started: {exc}\n")
        target_line = next(line for line in account_snapshot.splitlines() if "Target " in line and "current holding" in line)
        print("[진행] 2/7 KIS 실계좌 잔고조회 및 보유상태 검증 완료", flush=True)
        print(target_line, flush=True)

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
        print("[진행] 3/7 DART·KIS 헤드라인·미국/한국 매크로·KIS 수급 검증 완료", flush=True)
        if kronos_mode != "disabled":
            print("[진행] Kronos 예측 수신 및 시계열 근거 검증 완료", flush=True)

    historical_report_context, prior_reports = load_prior_report_context(
        PROJECT_ROOT / "artifacts" / "reports", args.symbol, args.date
    )
    if prior_reports:
        dates = ", ".join(report.analysis_date for report in prior_reports)
        print(f"[진행] 이전 {args.symbol} 리포트 {len(prior_reports)}건 참고: {dates}", flush=True)
    else:
        print(f"[진행] 이전 {args.symbol} 리포트 없음 (현재 분석일 이전 기준)", flush=True)

    graph = create_korean_stock_graph(
        {**overrides, "enable_korean_evidence_agents": args.enhanced},
        debug=args.debug,
        progress_callback=make_progress_printer(args.verbose),
    )
    state, signal = graph.propagate(
        args.symbol,
        args.date,
        verified_market_snapshot=snapshot,
        account_snapshot=account_snapshot,
        historical_report_context=historical_report_context,
    )
    path = graph.save_reports(state, args.symbol)
    visual_path = write_market_overview_svg(path.parent / "visuals", market_bars, snapshot)
    append_visual_section(path, visual_path)
    evidence_path = write_evidence_manifest(
        path,
        args.symbol,
        args.date,
        snapshot,
        args.enhanced,
        kronos_mode != "disabled",
        args.account_mode == "required",
        account_snapshot,
        historical_report_context,
    )
    brief_path = write_final_brief(path, state, args.symbol, visual_path=visual_path)

    print(f"Final signal: {signal}")
    print(f"Report written to: {path}")
    print(f"Evidence manifest written to: {evidence_path}")
    print(f"Visual evidence written to: {visual_path}")
    print(f"Final decision brief written to: {brief_path}")


if __name__ == "__main__":
    main()
