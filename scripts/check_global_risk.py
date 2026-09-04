"""Fetch free global-risk evidence without KIS, LLM, GPU or order calls."""

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from tradingagents.dataflows.global_risk import global_risk_context  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    try:
        evidence = global_risk_context(args.date)
    except Exception as exc:
        # Do not expose request URLs containing the FRED credential.
        parser.exit(
            2, f"Global-risk preflight FAILED ({type(exc).__name__}); no success report written.\n"
        )
    output = ROOT / "artifacts" / "global_risk" / args.date / "evidence.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(evidence, encoding="utf-8")
    print(f"Global-risk collection complete: {output}")
    print(
        "Historical replay remains exploratory: BOJ revisions and news coverage are not strict PIT."
    )


if __name__ == "__main__":
    main()
