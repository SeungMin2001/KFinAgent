"""Chronological, long/cash research benchmark. Never submits broker orders."""

from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

BASELINES = ("buy_hold", "sma", "macd", "rsi")
STRATEGY_LABELS = {
    "buy_hold": "매수 후 보유",
    "sma": "SMA 20/60",
    "macd": "MACD",
    "rsi": "RSI 14",
    "kronos": "Kronos 단독",
    "agents": "한국형 Agents",
    "agents_kronos": "Agents + Kronos",
}
SYMBOL_LABELS = {"005930": "삼성전자 (005930)", "000660": "SK하이닉스 (000660)"}


def validate_bars(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index)
    required = ["open", "high", "low", "close", "volume", "amount"]
    if frame.empty or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("Bars must be nonempty and have unique increasing dates")
    values = frame[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (frame[required[:4]] <= 0).any().any():
        raise ValueError("Bars contain missing/nonfinite/nonpositive prices")
    if (frame[["volume", "amount"]] < 0).any().any():
        raise ValueError("Negative volume/amount")
    if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (
        frame.low > frame[["open", "close"]].min(axis=1)
    ).any():
        raise ValueError("Inconsistent OHLC candle")
    return frame


def baseline_target(name: str, history: pd.DataFrame, current: float) -> float:
    close = history.close
    if name == "buy_hold":
        return 1.0
    if len(close) < 60:
        raise ValueError("At least 60 warm-up sessions required")
    if name == "sma":
        return float(close.tail(20).mean() > close.tail(60).mean())
    if name == "macd":
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        return float(macd.iloc[-1] > macd.ewm(span=9, adjust=False).mean().iloc[-1])
    if name == "rsi":
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
        loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
        rsi = 50 if gain == loss == 0 else 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
        return 1.0 if rsi < 30 else 0.0 if rsi > 70 else current
    raise ValueError(f"Unknown baseline: {name}")


def rating_target(signal: str, current: float) -> float:
    if signal.lower() in {"buy", "overweight"}:
        return 1.0
    if signal.lower() in {"sell", "underweight"}:
        return 0.0
    if signal.lower() == "hold":
        return current
    raise ValueError(f"Untradeable agent signal: {signal!r}; benchmark stopped")


def simulate(
    frame: pd.DataFrame,
    start: str,
    end: str,
    decide,
    *,
    capital=1_000_000.0,
    cost_bps=10.0,
    cadence=12,
):
    """Decision after t close, execution at next observed session open.

    Independent equal-capital sleeves; fractional adjusted-price units. A
    zero-volume day is not executable. Final NAV is marked, not liquidated.
    """
    frame = validate_bars(frame)
    if capital <= 0 or not np.isfinite(capital) or not 0 <= cost_bps < 10000 or cadence < 1:
        raise ValueError("Invalid simulation parameters")
    indices = [i for i, day in enumerate(frame.index) if start <= day.strftime("%Y-%m-%d") <= end]
    if len(indices) < 2 or indices[0] < 60:
        raise ValueError("Need >=2 evaluation sessions and >=60 prior warm-up sessions")
    cash, units, pending, prior_target = capital, 0.0, None, 0.0
    records, orders = [], []
    # All strategies make their first decision on the previous session close.
    decision_indices = {indices[0] - 1} | set(indices[cadence - 1 : -1 : cadence])
    for i in range(indices[0] - 1, indices[-1] + 1):
        day = frame.index[i]
        row = frame.iloc[i]
        if i in indices:
            if pending is not None and row.volume > 0:
                equity_open = cash + units * row.open
                desired_units = pending * equity_open / row.open
                delta = desired_units - units
                cost = cost_bps / 10000
                if delta > 0:
                    delta = min(delta, cash / (row.open * (1 + cost)))
                notional = abs(delta) * row.open
                fee = notional * cost
                cash -= delta * row.open + fee
                units += delta
                if notional > 1e-8:
                    orders.append(
                        {
                            "date": str(day.date()),
                            "units": float(delta),
                            "price": float(row.open),
                            "cost": float(fee),
                            "notional": float(notional),
                        }
                    )
                prior_target = pending
                pending = None
            equity = cash + units * row.close
            records.append(
                {
                    "date": str(day.date()),
                    "equity": float(equity),
                    "cash": float(cash),
                    "units": float(units),
                    "exposure": float(units * row.close / equity),
                }
            )
        if i in decision_indices:
            # Copies stop a strategy from reaching later prices through a view.
            history = frame.iloc[: i + 1].copy()
            context = {
                "cash": float(cash),
                "units": float(units),
                "equity": float(cash + units * row.close),
                "target": prior_target,
            }
            pending = float(decide(history, context))
            if not np.isfinite(pending) or not 0 <= pending <= 1:
                raise ValueError("Strategy target must be finite and in [0,1]")
    return pd.DataFrame(records).set_index("date"), orders


def metrics(equity: pd.Series, capital: float) -> dict:
    values = np.r_[capital, equity.to_numpy(dtype=float)]
    returns = values[1:] / values[:-1] - 1
    volatility = returns.std(ddof=1)
    return {
        "return_pct": float((values[-1] / capital - 1) * 100),
        "annualized_return_pct": float(((values[-1] / capital) ** (252 / len(returns)) - 1) * 100),
        "sharpe_rf0": float(np.sqrt(252) * returns.mean() / volatility)
        if volatility > 1e-12
        else None,
        "max_drawdown_pct": float((values / np.maximum.accumulate(values) - 1).min() * 100),
        "sessions": len(returns),
    }


def excess_interval(equity: pd.Series, baseline: pd.Series, capital: float) -> list[float]:
    """Seeded paired circular 12-session block bootstrap, mean daily excess bps."""
    left = np.diff(np.log(np.r_[capital, equity.to_numpy()]))
    right = np.diff(np.log(np.r_[capital, baseline.to_numpy()]))
    diff = left - right
    rng = np.random.default_rng(20260904)
    starts = rng.integers(0, len(diff), size=(2000, int(np.ceil(len(diff) / 12))))
    indices = (starts[..., None] + np.arange(12)) % len(diff)
    means = diff[indices.reshape(2000, -1)[:, : len(diff)]].mean(axis=1) * 10000
    return np.quantile(means, [0.025, 0.975]).tolist()


def write_report(
    directory: Path,
    curves: dict[str, pd.DataFrame],
    trades: dict,
    manifest: dict,
    capital: float,
    symbol_results: dict | None = None,
) -> dict:
    """Only complete, aligned runs reach this function."""
    if len({tuple(frame.index) for frame in curves.values()}) != 1:
        raise ValueError("Unaligned evaluation calendars; refusing an unfair comparison")
    summary = {}
    for name, curve in curves.items():
        summary[name] = metrics(curve.equity, capital)
        summary[name]["trades"] = len(trades[name])
        summary[name]["cost_paid"] = sum(t["cost"] for t in trades[name])
        summary[name]["mean_exposure_pct"] = float(curve.exposure.mean() * 100)
        summary[name]["mean_daily_log_excess_bps_ci95"] = excess_interval(
            curve.equity, curves["buy_hold"].equity, capital
        )
        curve.to_csv(directory / f"{name}_equity.csv")
    (directory / "metrics.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    (directory / "trades.json").write_text(json.dumps(trades, indent=2, allow_nan=False))
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    palette = ["#64748b", "#2563eb", "#16a34a", "#d97706", "#9333ea", "#0891b2", "#dc2626"]

    def chart(drawdown=False):
        arrays = {}
        for name, frame in curves.items():
            a = np.r_[capital, frame.equity.to_numpy()]
            arrays[name] = (
                (a / np.maximum.accumulate(a) - 1) * 100 if drawdown else (a / capital - 1) * 100
            )
        low = min(float(a.min()) for a in arrays.values())
        high = max(float(a.max()) for a in arrays.values())
        spread = max(high - low, 1)
        heading = "Drawdown (%)" if drawdown else "Cumulative net return (%)"
        lines = [f'<text x="60" y="16" font-size="14">{heading}</text>']
        for tick in np.linspace(low, high if high != low else high + 1, 5):
            y = 245 - (tick - low) / spread * 215
            lines.append(
                f'<line x1="60" y1="{y}" x2="920" y2="{y}" stroke="#e2e8f0"/><text x="5" y="{y}" font-size="12">{tick:.1f}%</text>'
            )
        for j, (name, a) in enumerate(arrays.items()):
            points = " ".join(
                f"{60 + i / (len(a) - 1) * 860:.1f},{245 - (v - low) / spread * 215:.1f}"
                for i, v in enumerate(a)
            )
            lines.append(
                f'<polyline fill="none" stroke="{palette[j]}" stroke-width="2" points="{points}"><title>{html.escape(name)}</title></polyline>'
            )
        dates = next(iter(curves.values())).index
        lines.append(f'<text x="60" y="265" font-size="12">{html.escape(str(dates[0]))}</text>')
        lines.append(
            f'<text x="920" y="265" text-anchor="end" font-size="12">{html.escape(str(dates[-1]))}</text>'
        )
        for j, name in enumerate(curves):
            lx, ly = 60 + (j % 4) * 215, 295 + (j // 4) * 25
            lines.append(
                f'<line x1="{lx}" y1="{ly}" x2="{lx + 20}" y2="{ly}" stroke="{palette[j]}" stroke-width="2"/><text x="{lx + 26}" y="{ly + 4}" font-size="12">{html.escape(name)}</text>'
            )
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 345" role="img"><rect width="960" height="345" fill="white"/>'
            + "".join(lines)
            + "</svg>"
        )

    rows = []
    for name, result in summary.items():
        sharpe = "N/A" if result["sharpe_rf0"] is None else f"{result['sharpe_rf0']:.2f}"
        rows.append(
            f"<tr><td>{html.escape(STRATEGY_LABELS.get(name, name))}</td><td>{result['return_pct']:+.2f}%</td><td>{result['annualized_return_pct']:+.2f}%</td><td>{sharpe}</td><td>{result['max_drawdown_pct']:.2f}%</td><td>{result['trades']}</td><td>{result['mean_exposure_pct']:.1f}%</td></tr>"
        )
    for filename, is_drawdown in (("equity.svg", False), ("drawdown.svg", True)):
        (directory / filename).write_text(chart(is_drawdown), encoding="utf-8")
    symbol_table = ""
    if symbol_results:
        cells = []
        for symbol, results in symbol_results.items():
            for strategy, result in results.items():
                cells.append(
                    f"<tr><td>{html.escape(SYMBOL_LABELS.get(symbol, symbol))}</td><td>{html.escape(STRATEGY_LABELS.get(strategy, strategy))}</td><td>{result['return_pct']:+.2f}%</td><td>{result['max_drawdown_pct']:.2f}%</td></tr>"
                )
        symbol_table = (
            "<section><h2>종목별 순수익률과 낙폭</h2><table><tr><th>종목</th><th>전략</th><th>순수익률</th><th>MDD</th></tr>"
            + "".join(cells)
            + "</table></section>"
        )
    page = f"""<!doctype html><meta charset="utf-8"><title>Korean STOCK benchmark</title>
<style>body{{font:16px system-ui;background:#f8fafc;color:#0f172a;max-width:1100px;margin:40px auto;padding:24px}}section{{background:white;padding:24px;margin:20px 0;border:1px solid #e2e8f0;border-radius:12px;overflow-x:auto}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:right;padding:12px;border-bottom:1px solid #e2e8f0}}td:first-child,th:first-child{{text-align:left}}p{{line-height:1.6}}svg{{width:100%}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style>
<h1>Korean STOCK · Historical benchmark</h1><p>{html.escape(manifest["start"])} → {html.escape(manifest["end"])} · {html.escape(", ".join(SYMBOL_LABELS.get(s, s) for s in manifest["symbols"]))}</p>
<p>탐색적 과거 평가 · 미래 실적 검증 아님 · 비용 편도 {manifest["cost_bps"]}bp · 다음 거래일 시가 체결 · 현금 수익률 0</p>
<section><table><tr><th>전략</th><th>순수익률</th><th>연환산*</th><th>Sharpe (rf=0)</th><th>최대낙폭</th><th>체결 수</th><th>평균 노출</th></tr>{"".join(rows)}</table><p>*252거래일 기준 연환산. 짧은 구간에서는 불안정함. 배당 제외 조정가격 기준, 비용은 실제 세율이 아닌 명시적 가정.</p></section>
<section><h2>누적 순수익률</h2>{chart()}</section>
<section><h2>고점 대비 하락률</h2>{chart(True)}</section>
{symbol_table}
<section><h2>재현 정보와 한계</h2><details><summary>실험 설정·출처·제한사항 펼치기</summary><pre>{html.escape(json.dumps(manifest, indent=2, ensure_ascii=False))}</pre></details><p>원시 결과: metrics.json · trades.json · 전략별 equity.csv. paired block bootstrap 신뢰구간은 metrics.json에 저장.</p></section>"""
    (directory / "BENCHMARK.html").write_text(page, encoding="utf-8")
    return summary
