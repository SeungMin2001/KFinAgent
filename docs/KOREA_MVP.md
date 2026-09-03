# Korean Stock Research MVP

This is the first Korean-market adaptation of TradingAgents. It is a
**research-only** workflow: it retrieves adjusted domestic daily OHLCV from
Korea Investment & Securities (KIS), lets the existing market/research/risk
agents form an opinion, and writes a report. It has no order, balance, or
account tools.

## What changed

- Added the `kis` data vendor for the official domestic daily-chart endpoint.
- Maps KIS fields into `date, open, high, low, close, volume, amount`.
- Calculates SMA, EMA, MACD, RSI, Bollinger Bands, ATR, and VWMA from KIS bars.
- The base mode enables only the Market Analyst. `--enhanced` inserts three
  source-bounded Evidence Analysts for OpenDART disclosures, FRED/ECOS macro,
  and KIS investor flow before the Market Analyst.
- Disables yfinance-based company-identity lookup and reflection memory, so the
  workflow's market data stays KIS-only.

## Setup

```bash
bash scripts/bootstrap_local_env.sh
cp .env.example .env
```

The bootstrap requires Python 3.12 and creates a machine-specific environment
under `~/.virtualenvs/`, outside the iCloud-synchronised project. Override the
interpreter with `PYTHON_BIN` or the parent directory with `STOCK_VENV_ROOT`.
Never sync or reuse a virtual environment between the iMac and MacBook: venv
launchers contain absolute paths to the Python installation that created them.
Use `bash scripts/bootstrap_local_env.sh --print-path` to show the environment
path selected for the current Mac.

Set `KIS_APP_KEY`, `KIS_APP_SECRET`, and an LLM key in `.env`. `KIS_ENV=demo`
uses the KIS virtual-investment host; `real` uses the production host. The KIS
credentials must have access to domestic-stock quotation APIs.

## Run

```bash
~/.virtualenvs/stock-<Mac-name>-py312/bin/python scripts/korean_stock_research.py 005930 --date 2026-09-02 --enhanced
```

The output is a research rating such as `Buy`, `Hold`, or `Sell`, plus a
Markdown report under `~/.tradingagents/logs/reports/`. It is not an order.

## Verification without credentials

The KIS provider has mocked HTTP tests that validate token authentication,
official response-field mapping, chronological sorting, and Korean-only config.

```bash
~/.virtualenvs/stock-<Mac-name>-py312/bin/pytest tests/test_kis_provider.py -q
```

Use `--verbose` with the research script to print every completed analyst and
debate output to the terminal as the workflow runs. Without it, the script
prints only concise stage progress; the full report is still saved to disk.

Every completed research run writes `0_evidence.md` beside `complete_report.md`.
It records the immutable source-attributed snapshot collected before LLM work.
In enhanced mode each Evidence Analyst receives only its assigned source
sections; the Market Analyst receives verified prices/indicators plus their
normalized reports. These reports are saved as `disclosure.md`, `macro.md`,
and `flow.md` under `1_analysts/`.

Those tests are only unit tests. The executable does not use their fake
responses: it first fetches a real KIS market-data snapshot and exits before
the agent starts if KIS authentication, network access, or market data fails.

## Next: disclosure depth and Kronos

The enhanced workflow is being added with three additional credential scopes:
`DART_API_KEY` for official filings, `ECOS_API_KEY` for Bank of Korea macro
statistics, and `KRONOS_API_URL` / `KRONOS_API_KEY` for the separately hosted
Kronos GPU service. See [Kronos on RunPod](KRONOS_RUNPOD.md) before configuring
the model service.

## Known limits

- KIS daily quotations are fetched in 90-calendar-day windows because the
  official endpoint limits a response to roughly 100 observations.
- Current functionality is daily-bar research only; intraday and live-streaming
  data are not part of this MVP.
- OpenDART original-document ZIP/XML files are downloaded for the ten selected
  filings. All extracted visible text is processed; large disclosure corpora
  are split into configurable 60,000-character chunks, normalized separately,
  and consolidated into one Disclosure Evidence report without silently
  dropping a filing.
- ECOS observations are bounded by the analysis date, but ECOS does not expose
  historical data vintages. Revised values can therefore still leak into a
  strict historical backtest unless daily source snapshots are archived.
- This is not a backtest or a trading system. A future phase will connect
  Kronos as a separate forecast tool, then evaluate its signal out of sample.
