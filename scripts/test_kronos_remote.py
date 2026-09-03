"""Send verified live KIS daily bars to the configured remote Kronos API.

This is a serving smoke test only: it places no orders and writes no model
inputs outside the normal HTTP request.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from tradingagents.dataflows.kis import get_kis_ohlcv_frame  # noqa: E402
from tradingagents.dataflows.kronos import forecast_kronos  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Live KIS-to-remote-Kronos serving smoke test")
    parser.add_argument("symbol", nargs="?", default="005930", help="Six-digit KRX code (default: 005930)")
    parser.add_argument("--date", default=date.today().isoformat(), help="KIS end date, YYYY-MM-DD")
    parser.add_argument("--horizon", type=int, default=5, help="Forecast trading-day horizon (1-30)")
    args = parser.parse_args()

    end = date.fromisoformat(args.date)
    start = end - timedelta(days=365)
    print(f"[1/3] KIS 일봉 조회: {args.symbol}, {start} ~ {end}", flush=True)
    bars = get_kis_ohlcv_frame(args.symbol, start.isoformat(), end.isoformat())
    print(f"[2/3] 검증된 {len(bars)}개 일봉을 Kronos API로 전송", flush=True)
    result = forecast_kronos(args.symbol, bars, horizon=args.horizon, mode="remote")
    print("[3/3] Kronos GPU 예측 응답 검증 완료", flush=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
