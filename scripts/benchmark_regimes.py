"""Reproducible two-regime suite. Defaults to a dry plan, never sends orders."""

import argparse
import html
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tradingagents.benchmark import BASELINES, STRATEGY_LABELS  # noqa: E402


def plan(end, strategies, costs, exposures, repeats, policies):
    if not date(2026, 7, 1) < date.fromisoformat(end) < date.today():
        raise ValueError("Use a completed end date after 2026-07-01 and before today")
    if any(not 0 <= x <= 1 for x in exposures) or any(not 0 <= c < 10000 for c in costs):
        raise ValueError("Invalid cost or initial exposure")
    if repeats < 1:
        raise ValueError("repeats must be positive")
    jobs = []
    for regime, start, finish in (("A", "2026-01-01", "2026-06-22"), ("B", "2026-07-01", end)):
        for cost in costs:
            for exposure in exposures:
                for policy in policies:
                    for repeat in range(1, repeats + 1):
                        jobs.append(
                            {
                                "regime": regime,
                                "start": start,
                                "end": finish,
                                "cost": cost,
                                "exposure": exposure,
                                "policy": policy,
                                "repeat": repeat,
                                "strategies": strategies,
                            }
                        )
    return jobs


def run_child(arguments):
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts/benchmark_korean_stock.py"), *arguments],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = None
    for line in process.stdout:
        print(line, end="", flush=True)
        if line.startswith("결과 디렉터리: "):
            output = Path(line.split(": ", 1)[1].strip())
    if process.wait() != 0 or output is None:
        raise RuntimeError("Child evaluation failed; no complete suite report will be published")
    if json.loads((output / "manifest.json").read_text()).get("status") != "complete":
        raise ValueError("Incomplete child experiment")
    return output


def render(results):
    figures = []
    for item in results:
        job = item["job"]
        if job["cost"] == 10 and job["exposure"] == 0 and job["repeat"] == 1 and item.get("run"):
            chart = (Path(item["run"]) / "equity.svg").read_text()
            figures.append(f"<section><h2>{html.escape(job['regime'])} · 현금 시작 / 10bp / 누적 순수익률</h2>{chart}</section>")
    sections, markdown = (
        [],
        ["# 두 구간 기준선 평가", "", "탐색적 가격 기반 과거 평가. AI 성과를 의미하지 않는다.", ""],
    )
    for item in results:
        job, metrics = item["job"], item["metrics"]
        title = (
            f"{job['regime']} · {job['start']}~{job['end']} · "
            f"초기 보유 {job['exposure']:.0%} · 비용 {job['cost']:g}bp · {job['policy']} · 반복 {job['repeat']}"
        )
        rows = []
        for strategy, m in metrics.items():
            label = STRATEGY_LABELS.get(strategy, strategy)
            sharpe = "N/A" if m["sharpe_rf0"] is None else f"{m['sharpe_rf0']:.2f}"
            rows.append(
                f"<tr><td>{html.escape(label)}</td><td>{m['return_pct']:+.2f}%</td><td>{m['excess_buy_hold_pp']:+.2f}pp</td><td>{m['max_drawdown_pct']:.2f}%</td><td>{sharpe}</td><td>{m['trades']}</td><td>{m['mean_exposure_pct']:.1f}%</td></tr>"
            )
        sections.append(
            f"<section><h2>{html.escape(title)}</h2><p>{next(iter(metrics.values()))['sessions']}거래일</p><table><tr><th>전략</th><th>순수익률</th><th>매수보유 대비</th><th>MDD</th><th>Sharpe</th><th>체결</th><th>평균 노출</th></tr>{''.join(rows)}</table></section>"
        )
        if job["cost"] == 10:
            markdown.extend(
                [
                    f"## {title}",
                    "",
                    "| 전략 | 순수익률 | 매수보유 대비 | MDD | 체결 |",
                    "|---|---:|---:|---:|---:|",
                ]
            )
            for strategy, m in metrics.items():
                markdown.append(
                    f"| {STRATEGY_LABELS.get(strategy, strategy)} | {m['return_pct']:+.2f}% | {m['excess_buy_hold_pp']:+.2f}pp | {m['max_drawdown_pct']:.2f}% | {m['trades']} |"
                )
            markdown.append("")
    page = (
        """<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Two-regime benchmark</title>
<style>body{font:15px system-ui;max-width:1100px;margin:32px auto;padding:20px;color:#182538;background:#f5f7fb}h1{font-size:30px}h2{font-size:17px}section{background:white;border:1px solid #dce2e9;border-radius:10px;padding:22px;margin:20px 0;overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}td,th{padding:10px;text-align:right;border-bottom:1px solid #eee}td:first-child,th:first-child{text-align:left}p{line-height:1.7}</style>
<h1>상승장 · 하락장 분리 평가</h1><p>1/1~6/22와 7/1~종료일을 분리. 6/23~6/30 제외. 두 종목 독립 계좌 합산.<br>미래 성과·한국 시장 전체 대표성·AI 우월성을 입증하지 않습니다. 동일 조건 안에서만 전략을 비교하세요.<br>비용은 편도 가정치이며 배당 제외. 초기 보유는 평가 전날 종가 기준의 동일 자산 부여입니다.</p>"""
        + "".join(figures)
        + "".join(sections)
        + "</html>"
    )
    return page, "\n".join(markdown)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    parser.add_argument("--symbols", nargs="+", default=["005930", "196170"])
    parser.add_argument("--cadence", type=int, default=21)
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=[*BASELINES, "kronos", "agents", "agents_kronos"],
        default=list(BASELINES),
    )
    parser.add_argument("--costs", nargs="+", type=float, default=[10])
    parser.add_argument("--exposures", nargs="+", type=float, default=[0])
    parser.add_argument("--policies", nargs="+", choices=["step", "binary", "tier"], default=["tier"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-total-agent-calls", type=int, default=0)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--max-evidence-chars", type=int, default=300_000)
    parser.add_argument("--bars-from", type=Path)
    parser.add_argument("--global-risk-from", type=Path, help="Prepared global snapshots shared across conditions")
    parser.add_argument(
        "--global-risk",
        action="store_true",
        help="Use only with --global-risk-from containing every decision date",
    )
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.global_risk and not args.global_risk_from:
        parser.error("--global-risk requires complete frozen snapshots via --global-risk-from")
    if args.global_risk_from and not args.global_risk:
        parser.error("--global-risk-from requires --global-risk")
    strategies = list(dict.fromkeys(["buy_hold", "cash", *args.strategies]))
    jobs = plan(args.end, strategies, args.costs, args.exposures, args.repeats, args.policies)
    # Calendar-day bound deliberately overestimates graph count before loading bars.
    graphs = sum(
        ((date.fromisoformat(j["end"]) - date.fromisoformat(j["start"])).days // args.cadence + 1)
        * len(args.symbols)
        * sum(s.startswith("agents") for s in strategies)
        for j in jobs
    )
    suite = {
        "status": "planned",
        "symbols": args.symbols,
        "cadence_sessions": args.cadence,
        "jobs": jobs,
        "agent_graph_calls_upper_bound": graphs,
        "note": "Graph count excludes internal LLM chunk calls. No token or dollar guarantee.",
        "max_output_tokens_per_response": args.max_output_tokens,
        "max_evidence_chars_per_decision": args.max_evidence_chars,
    }
    if not args.run:
        print(json.dumps(suite, indent=2, ensure_ascii=False))
        return
    if graphs > args.max_total_agent_calls:
        parser.error(
            f"Estimated graph upper bound {graphs} exceeds explicit total cap {args.max_total_agent_calls}"
        )
    output = (
        ROOT / "artifacts/benchmarks" / ("regimes_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    )
    output.mkdir(parents=True)
    suite.update(status="running", results=[])

    def save():
        (output / "suite.json").write_text(json.dumps(suite, indent=2, ensure_ascii=False))

    save()
    try:
        bars_source = args.bars_from or run_child(
            ["--start", "2026-01-01", "--end", args.end, "--symbols", *args.symbols,
             "--strategies", "buy_hold", "cash", "balanced_50", "--cadence", str(args.cadence)]
        )
        suite["bars_source"] = str(bars_source)
        if args.global_risk_from and any(s.startswith("agents") for s in strategies):
            import pandas as pd

            from tradingagents.benchmark import decision_dates
            from tradingagents.dataflows.evidence_snapshot import read_snapshot
            frame = pd.read_csv(bars_source / "005930_bars.csv", index_col=0, parse_dates=True)
            required = sorted({str(d.date()) for j in jobs for d in decision_dates(frame, j["start"], j["end"])})
            # Validate the WHOLE suite before the first paid model call.
            for day in required:
                read_snapshot(args.global_risk_from, day)
            suite["global_snapshot_dates"] = required
        for i, job in enumerate(jobs, 1):
            print(f"[Suite {i}/{len(jobs)}] {job}", flush=True)
            command = [
                "--start",
                job["start"],
                "--end",
                job["end"],
                "--symbols",
                *args.symbols,
                "--strategies",
                *strategies,
                "--cost-bps",
                str(job["cost"]),
                "--initial-exposure",
                str(job["exposure"]),
                "--allocation-policy",
                job["policy"],
                "--cadence",
                str(args.cadence),
                "--bars-from",
                str(bars_source),
            ]
            if any(s.startswith("agents") for s in strategies):
                command += [
                    "--max-agent-calls",
                    str(args.max_total_agent_calls),
                    "--max-output-tokens",
                    str(args.max_output_tokens),
                    "--max-evidence-chars",
                    str(args.max_evidence_chars),
                ]
                if args.global_risk:
                    command += ["--global-risk"]
                    if args.global_risk_from:
                        command += ["--global-risk-from", str(args.global_risk_from)]
            run = run_child(command)
            suite["results"].append(
                {
                    "job": job,
                    "run": str(run),
                    "metrics": json.loads((run / "metrics.json").read_text()),
                }
            )
            save()
        page, markdown = render(suite["results"])
        (output / "SUITE.html").write_text(page, encoding="utf-8")
        (output / "RESULTS.md").write_text(markdown, encoding="utf-8")
        suite["status"] = "complete"
        save()
        print(f"완료: {output / 'SUITE.html'}", flush=True)
    except Exception as exc:
        suite.update(status="failed", error_type=type(exc).__name__)
        save()
        raise SystemExit("Suite failed; no final suite leaderboard published") from None


if __name__ == "__main__":
    main()
