"""Run auditable historical comparisons; no broker orders or live balance reads."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import pandas as pd  # noqa: E402
import requests  # noqa: E402

from tradingagents.benchmark import (  # noqa: E402
    BASELINES,
    baseline_target,
    decision_dates,
    execution_action,
    rating_target,
    simulate,
    write_report,
)


def enforce_evidence_budget(evidence: str, limit: int) -> int:
    """Stop before a paid graph call when source material is unexpectedly large."""
    size = len(evidence)
    if size > limit:
        raise ValueError(
            f"Verified evidence is {size:,} characters, above the explicit {limit:,} limit. "
            "Review the corpus and raise --max-evidence-chars deliberately; this is not a token cap."
        )
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["005930", "000660"])
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-08-31")
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=[*BASELINES, "kronos", "agents", "agents_kronos"],
        default=list(BASELINES),
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=10,
        help="All-in per-side cost assumption, not a tax schedule",
    )
    parser.add_argument("--cadence", type=int, default=12)
    parser.add_argument("--model", help="Explicit LLM model for both reasoning and quick stages")
    parser.add_argument(
        "--bars-from",
        type=Path,
        help="Explicitly reuse checksum-verified KIS bars from a previous run",
    )
    parser.add_argument("--max-agent-calls", type=int, default=120)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=4096,
        help="Per LLM response safety cap; this does not cap total input or billed tokens",
    )
    parser.add_argument(
        "--max-evidence-chars",
        type=int,
        default=300_000,
        help="Pre-LLM character guard per symbol/date; deliberately raise after reviewing the corpus",
    )
    parser.add_argument("--global-risk-from", type=Path, help="Explicit directory of prepared dated real global snapshots; never falls back to live")
    parser.add_argument("--allocation-policy", choices=["step", "binary"], default="step")
    parser.add_argument(
        "--initial-exposure",
        type=float,
        default=0,
        help="Identical prior-close stock endowment for every strategy, 0..1",
    )
    parser.add_argument(
        "--global-risk",
        action="store_true",
        help="Include free global-risk evidence in both Agent variants (exploratory, not strict PIT)",
    )
    parser.add_argument(
        "--plan", action="store_true", help="No API calls; print intended experiment"
    )
    args = parser.parse_args()
    if args.global_risk_from and not args.global_risk:
        parser.error("--global-risk-from requires --global-risk")
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if start >= end or end >= date.today():
        parser.error("Use a completed historical period: start < end < today")
    if args.cadence < 1 or not 0 <= args.cost_bps < 10000:
        parser.error("cadence >=1 and cost-bps in [0,10000) required")
    if args.max_output_tokens < 256:
        parser.error("max-output-tokens must be >=256")
    if args.max_evidence_chars < 10_000:
        parser.error("max-evidence-chars must be >=10000")
    if not 0 <= args.initial_exposure <= 1:
        parser.error("initial-exposure must be in [0,1]")
    if len(set(args.symbols)) != len(args.symbols) or any(
        len(s) != 6 or not s.isdigit() for s in args.symbols
    ):
        parser.error("Use unique six-digit KRX symbols")
    strategies = list(dict.fromkeys(["buy_hold", *args.strategies]))
    manifest = {
        "start": args.start,
        "end": args.end,
        "symbols": args.symbols,
        "strategies": strategies,
        "cost_bps": args.cost_bps,
        "cadence_sessions": args.cadence,
        "capital_per_symbol": 1_000_000,
        "model_override": args.model,
        "global_risk": args.global_risk,
        "global_risk_source": (
            "disabled"
            if not args.global_risk
            else "frozen_snapshot" if args.global_risk_from else "live"
        ),
        "allocation_policy": args.allocation_policy,
        "initial_exposure": args.initial_exposure,
        "periodic_fundamentals": True,
        "dart_evidence_policy": "structured-financials-keyword-context-v1",
        "max_output_tokens_per_response": args.max_output_tokens,
        "max_evidence_chars_per_decision": args.max_evidence_chars,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "git_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
        ),
        "limitations": [
            "Exploratory historical replay, NOT proven point-in-time or out-of-sample performance",
            "ECOS revisions, DART amendments, historical headline coverage and LLM training contamination remain risks",
            "Fixed convenience universe, not a survivorship-free KRX universe",
            "Adjusted-price fractional units; no dividends, liquidity/limit-up queue or partial-fill simulation",
            "No live account; separate simulated account per strategy; no external prior-report memory",
            "Close-time decision, next available session open; zero-volume execution deferred",
            "Step sizing: Buy +50pp / Overweight +25pp / Underweight -25pp / Sell 0; binary optional; Hold preserves units; REVIEW stops",
            "Kronos: 40 candles ->12 weekdays, T=.6 top_p=.9 10 independent paths; KRX holidays not modeled by service",
            "Every strategy uses the same decision cadence; this is a controlled ablation, not optimized rule trading",
            "No winner selection or parameter tuning on this evaluation window; short pilot does not support superiority claims",
        ],
    }
    if args.global_risk:
        manifest["limitations"].append(
            "Global-risk: BOJ overnight market rates are latest revisions, NOT policy targets or historical vintages; GDELT titles/first-seen times are incomplete and not verified event/publication times"
        )
    if args.plan:
        estimate = len(pd.bdate_range(start, end)) // args.cadence + 1
        manifest["agent_graph_calls_upper_estimate"] = (
            estimate * len(args.symbols) * sum(s.startswith("agents") for s in strategies)
        )
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return
    output = ROOT / "artifacts" / "benchmarks" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True)
    manifest["source_sha256"] = {}
    sources = [Path(__file__), *sorted((ROOT / "tradingagents").rglob("*.py"))]
    for source in sources:
        content = source.read_text()
        relative = source.relative_to(ROOT)
        destination = output / "source" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
        manifest["source_sha256"][str(relative)] = hashlib.sha256(content.encode()).hexdigest()
    (output / "manifest.json").write_text(
        json.dumps({**manifest, "status": "running"}, indent=2, ensure_ascii=False)
    )
    print(f"결과 디렉터리: {output}", flush=True)
    try:
        execute(args, strategies, manifest, output)
    except (Exception, KeyboardInterrupt) as exc:
        # Third-party exceptions can embed account URLs or auth data. Persist
        # only the exception class here; no partial leaderboard is produced.
        failure = {"status": "failed", "error_type": type(exc).__name__}
        response = getattr(exc, "response", None)
        if response is not None:
            from urllib.parse import urlparse
            parsed = urlparse(response.url)
            failure.update(http_status=response.status_code, provider=parsed.hostname, path=parsed.path)
        (output / "FAILED.json").write_text(json.dumps(failure))
        manifest.update(failure)
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        print(
            f"평가 중단: {json.dumps(failure)}. 부분 결과를 최종 성과로 집계하지 않았습니다.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


def execute(args, strategies, manifest, output):
    from tradingagents.dataflows.kis import _default_client

    class PacedSession(requests.Session):
        last_call = 0.0

        def request(self, *a, **kw):
            time.sleep(max(0, 1.1 - (time.monotonic() - self.last_call)))
            self.last_call = time.monotonic()
            return super().request(*a, **kw)

    client = None
    source_manifest = None
    if args.bars_from:
        source_manifest = json.loads((args.bars_from / "manifest.json").read_text())
        if args.start < source_manifest["start"] or args.end > source_manifest["end"]:
            raise ValueError("Requested dates extend outside the recorded source experiment")
        manifest["bars_source_run"] = str(args.bars_from)
    else:
        client = _default_client()
        client.session = PacedSession()
    if source_manifest is not None and any(s.startswith("agents") for s in strategies):
        _default_client().session = PacedSession()
    frames = {}
    for symbol in args.symbols:
        print(f"[수집] {symbol} 실제 KIS 캔들", flush=True)
        if source_manifest is not None:
            source = args.bars_from / f"{symbol}_bars.csv"
            digest = source_manifest["input_sha256"].get(source.name)
            if digest != hashlib.sha256(source.read_bytes()).hexdigest():
                raise ValueError("Stored KIS bar checksum mismatch")
            frames[symbol] = pd.read_csv(source, index_col=0, parse_dates=True)
        else:
            frames[symbol] = client.daily_ohlcv(
                symbol, (date.fromisoformat(args.start) - timedelta(days=400)).isoformat(), args.end
            )
        path = output / f"{symbol}_bars.csv"
        frames[symbol].to_csv(path)
        manifest.setdefault("input_sha256", {})[path.name] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    sessions = [tuple(f.loc[args.start : args.end].index) for f in frames.values()]
    if not sessions[0] or any(s != sessions[0] for s in sessions):
        raise ValueError(
            "Missing/unaligned symbol calendars; resolve source coverage before comparing"
        )
    call_count = (
        ((len(sessions[0]) - 1) // args.cadence + 1)
        * len(args.symbols)
        * sum(s.startswith("agents") for s in strategies)
    )
    if call_count > args.max_agent_calls:
        print(
            f"필요 Agent 실행 {call_count}회 > 상한 {args.max_agent_calls}. --max-agent-calls로 명시하세요.",
            flush=True,
        )
        raise ValueError("Agent budget cap exceeded")
    if args.global_risk_from and any(s.startswith("agents") for s in strategies):
        from tradingagents.dataflows.evidence_snapshot import read_snapshot
        reference = next(iter(frames.values()))
        dates = decision_dates(reference, args.start, args.end, args.cadence)
        manifest["global_snapshot_sha256"] = {}
        for stamp in dates:
            day = str(stamp.date())
            read_snapshot(args.global_risk_from, day)
            path = args.global_risk_from / f"{day}.json"
            manifest["global_snapshot_sha256"][day] = hashlib.sha256(path.read_bytes()).hexdigest()
    if any("kronos" in s for s in strategies):
        from tradingagents.dataflows.kronos import KronosSettings

        settings = KronosSettings.from_env("remote")
        response = requests.get(
            settings.api_url.removesuffix("/v1/forecast") + "/healthz", timeout=15
        )
        if response.status_code != 200:
            print(f"RunPod 응답 HTTP {response.status_code}: Pod/URL 확인 필요", flush=True)
            raise RuntimeError("Kronos unavailable")
        manifest["kronos_health"] = response.json()
    if any(s.startswith("agents") for s in strategies):
        from tradingagents.korea import korean_stock_config

        cfg = korean_stock_config()
        manifest["llm_config"] = {
            k: cfg.get(k)
            for k in (
                "llm_provider",
                "deep_think_llm",
                "quick_think_llm",
                "max_debate_rounds",
                "max_risk_discuss_rounds",
                "temperature",
                "max_tokens",
                "openai_reasoning_effort",
            )
        }
        if args.model:
            manifest["llm_config"].update(deep_think_llm=args.model, quick_think_llm=args.model)
        manifest["llm_config"]["max_tokens"] = args.max_output_tokens
    shared_evidence, forecasts = {}, {}
    curves, all_trades = {}, {}
    for strategy in strategies:
        sleeves, trade_rows = [], []
        for symbol, frame in frames.items():

            def decide(history, account, strategy=strategy, symbol=symbol):
                as_of = str(history.index[-1].date())
                if strategy in BASELINES:
                    target = baseline_target(strategy, history, account["target"])
                    return None if abs(target - account["target"]) < 1e-10 else target
                print(f"[판단] {strategy} {symbol} {as_of}", flush=True)
                key = (symbol, as_of)
                if "kronos" in strategy and key not in forecasts:
                    from tradingagents.dataflows.korean_evidence import kronos_forecast_context

                    bars = history.reset_index()
                    bars.columns = ["Date"] + [c.capitalize() for c in history.columns]
                    forecasts[key] = kronos_forecast_context(symbol, bars, mode="remote")
                    (output / f"{symbol}_{as_of}_kronos.md").write_text(forecasts[key])
                if strategy == "kronos":
                    import re

                    match = re.search(r"Median-path expected return: ([-+0-9.]+)%", forecasts[key])
                    if match is None:
                        raise ValueError("Missing Kronos expected return")
                    return float(float(match[1]) > 2 * args.cost_bps / 100)
                from tradingagents.dataflows.korean_evidence import enhanced_korean_evidence
                from tradingagents.korea import (
                    create_korean_stock_graph,
                    verify_kis_data_access_with_bars,
                )

                if key not in shared_evidence:
                    snapshot, bars = verify_kis_data_access_with_bars(symbol, as_of)
                    # Detect price changes between the replay dataset and the
                    # fresh evidence query (e.g. an intervening corporate action).
                    if (
                        not abs(float(bars.Close.iloc[-1]) / float(history.close.iloc[-1]) - 1)
                        < 1e-8
                    ):
                        raise ValueError("KIS snapshot/replay price mismatch")
                    shared_evidence[key] = enhanced_korean_evidence(
                        symbol,
                        as_of,
                        snapshot,
                        config={"kronos_mode": "disabled", "enable_global_risk": args.global_risk,
                                "global_risk_snapshot_dir": args.global_risk_from},
                        market_bars=bars,
                    )
                    manifest.setdefault("evidence_chars", {})[f"{symbol}_{as_of}"] = (
                        enforce_evidence_budget(shared_evidence[key], args.max_evidence_chars)
                    )
                    (output / f"{symbol}_{as_of}_evidence.md").write_text(shared_evidence[key])
                snapshot = shared_evidence[key] + (
                    "\n\n" + forecasts[key] if strategy == "agents_kronos" else ""
                )
                overrides = {
                    "enable_korean_evidence_agents": True,
                    "enable_kronos_evidence_agent": strategy == "agents_kronos",
                    "kronos_mode": "remote" if strategy == "agents_kronos" else "disabled",
                    "results_dir": str(output / "agent_logs" / strategy),
                    "max_tokens": args.max_output_tokens,
                }
                if args.model:
                    overrides.update(deep_think_llm=args.model, quick_think_llm=args.model)

                def progress(event, stage, result=None):
                    if event == "started":
                        print(f"  [Agent] {stage}", flush=True)

                graph = create_korean_stock_graph(overrides, progress_callback=progress)
                sizing_rule = (
                    "Buy increases exposure by 50 percentage points; Overweight by 25; "
                    "Underweight reduces it by 25; Sell exits. Targets are clipped to [0%,100%]."
                    if args.allocation_policy == "step"
                    else "Buy/Overweight enters full long; Underweight/Sell exits."
                )
                from langchain_core.callbacks import get_usage_metadata_callback
                with get_usage_metadata_callback() as usage:
                    state, signal = graph.propagate(
                        symbol,
                        as_of,
                        verified_market_snapshot=snapshot,
                        account_snapshot="SIMULATED benchmark account at decision close: "
                        + json.dumps(account)
                        + "; fractional adjusted units. "
                        + sizing_rule
                        + " Hold places no order: WAIT if flat, HOLD_POSITION if invested. No shorting. "
                        "Separate market outlook from executable account action. A bearish view while flat "
                        "does not require shorting. Do not force trades or require all evidence to agree.",
                        historical_report_context="Benchmark isolated run: no external historical reports.",
                    )
                graph.save_reports(state, symbol)
                target = rating_target(signal, account["target"], args.allocation_policy)
                (output / f"{strategy}_{symbol}_{as_of}_decision.json").write_text(
                    json.dumps(
                        {
                            "signal": signal,
                            "target": target,
                            "execution_action": execution_action(account["target"], target),
                            "allocation_policy": args.allocation_policy,
                            "llm_usage_by_model": usage.usage_metadata,
                            "account": account,
                            "final_trade_decision": state["final_trade_decision"],
                            "fundamentals_report": state.get("fundamentals_report", ""),
                            "investment_plan": state.get("investment_plan", ""),
                            "snapshot_sha256": hashlib.sha256(snapshot.encode()).hexdigest(),
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
                return None if abs(target - account["target"]) < 1e-10 else target

            curve, trades = simulate(
                frame,
                args.start,
                args.end,
                decide,
                cost_bps=args.cost_bps,
                cadence=args.cadence,
                initial_exposure=args.initial_exposure,
            )
            curve.to_csv(output / f"{strategy}_{symbol}_equity.csv")
            sleeves.append(curve)
            trade_rows.extend({**trade, "symbol": symbol} for trade in trades)
        total = pd.DataFrame(index=sleeves[0].index)
        total["equity"] = sum(s.equity for s in sleeves)
        total["exposure"] = sum(s.exposure * s.equity for s in sleeves) / total.equity
        curves[strategy], all_trades[strategy] = total, trade_rows
    manifest["status"] = "complete"
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["agent_graph_calls"] = call_count
    summary = write_report(output, curves, all_trades, manifest, len(args.symbols) * 1_000_000)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"보고서: {output / 'BENCHMARK.html'}", flush=True)


if __name__ == "__main__":
    main()
