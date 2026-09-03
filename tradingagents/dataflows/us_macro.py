"""US-first macro context for Korean equity research, sourced from FRED."""

from .fred import get_macro_data


def us_macro_context(as_of: str, lookback_days: int = 370) -> str:
    series = ("fed_funds_rate", "cpi", "core_cpi", "2y_treasury", "10y_treasury", "dollar_index", "vix")
    parts = ["## US macro snapshot (FRED; primary macro context for Korean equities)"]
    for indicator in series:
        parts.append(get_macro_data(indicator, as_of, look_back_days=lookback_days))
    return "\n\n".join(parts)
