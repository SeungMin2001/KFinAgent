"""Collect each historical global snapshot once; never invoke an LLM or GPU."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from tradingagents.dataflows.evidence_snapshot import collect_snapshot  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--dates", nargs="+")
    selection.add_argument(
        "--suite",
        type=Path,
        help="Existing suite.json with actual KIS bars_source; derive unique decision dates",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dates = args.dates
    if args.suite:
        import pandas as pd

        from tradingagents.benchmark import decision_dates

        suite = json.loads(args.suite.read_text())
        source = Path(suite["bars_source"])
        manifest = json.loads((source / "manifest.json").read_text())
        path = source / "005930_bars.csv"
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["input_sha256"][path.name]:
            parser.error("Source KIS bars checksum mismatch")
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        dates = {
            str(d.date())
            for j in suite["jobs"]
            for d in decision_dates(frame, j["start"], j["end"])
        }
    for as_of in sorted(set(dates)):
        print(f"[근거 준비] {as_of}", flush=True)
        try:
            print(collect_snapshot(args.output, as_of), flush=True)
        except Exception as exc:
            response = getattr(exc, "response", None)
            detail = type(exc).__name__
            if response is not None:
                detail += f" HTTP {response.status_code} {urlparse(response.url).hostname}"
            parser.exit(
                2, f"근거 준비 중단: {detail}. 해당 날짜를 대체하거나 생략하지 않았습니다.\n"
            )


if __name__ == "__main__":
    main()
