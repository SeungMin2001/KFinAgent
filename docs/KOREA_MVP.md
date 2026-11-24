# Korean stock research

Follow the Quickstart in the repository README to create a Python 3.12
environment and configure your own provider credentials.

## Research modes

- Basic mode uses KIS daily bars and computed indicators.
- Enhanced mode also collects KIS investor flows and headlines, OpenDART
  filings and periodic financial evidence, and ECOS and FRED macro data.
- The optional Kronos forecast uses the same verified KIS history. The default
  sends 40 daily bars and samples 10 paths over a 12-bar forecast horizon.
- The Quickstart disables read-only balance lookup with
  `--account-mode disabled`. The workflow never places orders.

Check the selected configuration before making a request:

```bash
python scripts/korean_stock_research.py 005930 --account-mode disabled --kronos-mode disabled --check-config
```

Add `--enhanced` to include its credential checks. This command checks local
configuration only. Use `--verbose` with an actual run to see analyst stages.

## Reports

Completed runs write `0_evidence.md`, `complete_report.md`, `FINAL_BRIEF.md`,
and `visuals/market_overview.svg` under `artifacts/reports/`. The evidence file
records the data and as-of dates that the LLM received. Forecast observations
are stored separately from filings and macro inputs in the analyst reports.

## Limits

- Research uses daily bars and the latest finalized investor-flow rows
  available to KIS. Trading days in a Kronos forecast are currently weekdays
  and can differ from the KRX calendar.
- ECOS supplies observation dates without historical vintages. Later revisions
  can affect historical analysis.
- Recorded backtests are case studies. They do not establish forecast or
  investment performance on future data.
