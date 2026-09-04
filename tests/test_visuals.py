import pandas as pd

from tradingagents.visuals import build_visual_summary, write_market_overview_svg


def _bars():
    return pd.DataFrame(
        {
            "Date": pd.date_range("2026-01-01", periods=40, freq="B"),
            "Open": range(100, 140),
            "High": range(101, 141),
            "Low": range(99, 139),
            "Close": range(100, 140),
            "Volume": [1_000] * 40,
            "Amount": [100_000] * 40,
        }
    )


def test_visual_summary_and_svg_use_verified_bars(tmp_path):
    bars = _bars()
    summary = build_visual_summary(bars)
    snapshot = summary + "\n\n### Median forecast path\n| Timestamp | Open | High | Low | Close | Volume |\n|---|---:|---:|---:|---:|---:|\n| 2026-02-27T00:00:00 | 140 | 142 | 138 | 141 | 1000 |\n\n- Final-return range (p10 / p50 / p90): -2.0000% / 1.0000% / 4.0000%"
    path = write_market_overview_svg(tmp_path, bars, snapshot)

    assert "Latest close: 139.00" in summary
    assert path.name == "market_overview.svg"
    chart = path.read_text(encoding="utf-8")
    assert "Kronos median forecast" in chart
    assert "Observed and forecast daily trading volume" in chart
    assert "class=\"forecast-volume\"" in chart
    assert "Volume is a median path only" in chart
    assert "FORECAST WINDOW" in chart
    assert ">Feb 25</text>" in chart
    assert ">Feb 27</text>" in chart
