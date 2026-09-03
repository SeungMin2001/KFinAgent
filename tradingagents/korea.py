"""Korean-stock configuration built on the TradingAgents workflow.

The first-stage integration is quotation-only: it uses KIS for daily market
data and technical indicators, runs the existing market/research/risk debate,
and never exposes an order tool.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.market_data_validator import build_verified_market_snapshot
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


def korean_stock_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    project_root = Path(__file__).resolve().parents[1]
    config.update(
        {
            "output_language": "Korean",
            "instrument_identity_provider": "none",
            # Disable the yfinance-based reflection path in this KIS-only MVP.
            "memory_log_path": None,
            "data_cache_dir": str(project_root / ".cache"),
            "results_dir": str(project_root / "artifacts"),
            "data_vendors": {
                **config["data_vendors"],
                "core_stock_apis": "kis",
                "technical_indicators": "kis",
            },
        }
    )
    if overrides:
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
    return config


def create_korean_stock_graph(
    config_overrides: dict[str, Any] | None = None,
    debug: bool = False,
    progress_callback: Callable[[str, str, dict | None], None] | None = None,
) -> TradingAgentsGraph:
    """Create a KIS-only Korean-market research graph.

    The standard Korean path enables only the Market Analyst. Setting
    ``enable_korean_evidence_agents`` in ``config_overrides`` inserts the
    source-bounded Disclosure, Macro, and Flow analysts used by enhanced mode.
    """
    return TradingAgentsGraph(
        selected_analysts=("market",),
        config=korean_stock_config(config_overrides),
        debug=debug,
        progress_callback=progress_callback,
    )


def verify_kis_data_access(
    symbol: str,
    analysis_date: str,
    config_overrides: dict[str, Any] | None = None,
) -> str:
    """Require a live KIS response before any LLM/agent work begins.

    This is deliberately not a health-check stub.  It downloads real KIS daily
    bars for the requested KRX symbol and builds the same deterministic market
    snapshot that the market analyst receives.  Any authentication, network,
    rate-limit, invalid-symbol, or empty-data error is allowed to stop the run.
    """
    requested = date.fromisoformat(analysis_date)
    if requested > date.today():
        raise ValueError("analysis_date cannot be in the future.")

    # The validator consults the shared router configuration. Set the Korean
    # KIS-only configuration before touching it, so it cannot select yfinance.
    config = korean_stock_config(config_overrides)
    set_config(config)

    # The snapshot downloads the required historical bars from KIS itself and
    # computes the deterministic indicator set. It is intentionally the sole
    # verification request: no cached or fixture data is accepted here.
    return build_verified_market_snapshot(
        symbol,
        analysis_date,
        look_back_days=int(config["korean_market_lookback_days"]),
        indicators=config["korean_snapshot_indicators"],
    )
