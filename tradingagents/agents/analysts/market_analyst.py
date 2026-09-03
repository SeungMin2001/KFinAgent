from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_indicators,
    get_instrument_context_from_state,
    get_language_instruction,
    get_stock_data,
    get_verified_market_snapshot,
)
from tradingagents.dataflows.korean_evidence import evidence_for_domain


def create_market_analyst(
    llm,
    preload_verified_snapshot: bool = False,
    use_korean_evidence_reports: bool = False,
    use_kronos_evidence_report: bool = False,
):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        # The Korean KIS workflow preloads this deterministically before the
        # LLM sees the task.  That makes a live market-data failure fatal rather
        # than trusting the model to decide whether it should call a tool.
        # Other configurations retain the original tool-driven behaviour.
        verified_snapshot = ""
        if preload_verified_snapshot:
            verified_snapshot = state.get("verified_market_snapshot", "")
            if not verified_snapshot:
                # Programmatic callers that did not preflight still fail
                # loudly on a live KIS request; they never receive fixture or
                # fallback data.
                verified_snapshot = get_verified_market_snapshot.invoke(
                    {"symbol": state["company_of_interest"], "curr_date": current_date}
                )
            if use_korean_evidence_reports:
                market_only = evidence_for_domain(verified_snapshot, "market")
                if not market_only:
                    raise RuntimeError("Market Analyst received no verified market evidence section")
                verified_snapshot = market_only

        # KIS mode already fetched a deterministic, live snapshot before the
        # LLM runs. Do not let the model fan out into duplicate indicator
        # requests (the upstream tool node executes calls concurrently), which
        # can trip the broker API while adding no new source data.
        tools = [] if preload_verified_snapshot else [
            get_stock_data,
            get_indicators,
            get_verified_market_snapshot,
        ]

        system_message = (
            """You are a trading assistant tasked with analyzing financial markets. Your role is to select the **most relevant indicators** for a given market condition or trading strategy from the following list. The goal is to choose up to **8 indicators** that provide complementary insights without redundancy. Categories and each category's indicators are:

Moving Averages:
- close_50_sma: 50 SMA: A medium-term trend indicator. Usage: Identify trend direction and serve as dynamic support/resistance. Tips: It lags price; combine with faster indicators for timely signals.
- close_200_sma: 200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend and identify golden/death cross setups. Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries.
- close_10_ema: 10 EMA: A responsive short-term average. Usage: Capture quick shifts in momentum and potential entry points. Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals.

MACD Related:
- macd: MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and divergence as signals of trend changes. Tips: Confirm with other indicators in low-volatility or sideways markets.
- macds: MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD line to trigger trades. Tips: Should be part of a broader strategy to avoid false positives.
- macdh: MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize momentum strength and spot divergence early. Tips: Can be volatile; complement with additional filters in fast-moving markets.

Momentum Indicators:
- rsi: RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis.

Volatility Indicators:
- boll: Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: Acts as a dynamic benchmark for price movement. Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals.
- boll_ub: Bollinger Upper Band: Typically 2 standard deviations above the middle line. Usage: Signals potential overbought conditions and breakout zones. Tips: Confirm signals with other tools; prices may ride the band in strong trends.
- boll_lb: Bollinger Lower Band: Typically 2 standard deviations below the middle line. Usage: Indicates potential oversold conditions. Tips: Use additional analysis to avoid false reversal signals.
- atr: ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust position sizes based on current market volatility. Tips: It's a reactive measure, so use it as part of a broader risk management strategy.

Volume-Based Indicators:
- vwma: VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price action with volume data. Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses.

- Select indicators that provide diverse and complementary information. Avoid redundancy (e.g., do not select both rsi and stochrsi). Also briefly explain why they are suitable for the given market context.

Write a very detailed and nuanced report of the trends you observe. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."""
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
        )
        if preload_verified_snapshot:
            system_message += (
                "\nA verified source-attributed market snapshot is already included in this prompt. "
                "Do not call any data tools; all required data was collected before this node. "
                "Use only supplied verified evidence for numerical claims; do not invent missing data. "
                "State conflicts between evidence sources explicitly."
            )
        else:
            system_message += (
                "\nCall get_stock_data first, then get_indicators using exact indicator names. "
                "Before the final report, call get_verified_market_snapshot and treat it as the source "
                "of truth for exact OHLCV, price-level, and indicator-value claims. If outputs conflict, "
                "flag the discrepancy rather than inventing a reconciled number."
            )
        evidence_reports = ""
        if use_korean_evidence_reports:
            required = {
                "Disclosure Evidence Analyst": state.get("disclosure_report", ""),
                "Macro Evidence Analyst": state.get("macro_report", ""),
                "Flow Evidence Analyst": state.get("flow_report", ""),
            }
            if use_kronos_evidence_report:
                required["Time-Series Forecast Evidence Analyst"] = state.get("kronos_report", "")
            missing = [name for name, report in required.items() if not report]
            if missing:
                raise RuntimeError(
                    "Market Analyst is missing required evidence reports: " + ", ".join(missing)
                )
            evidence_reports = "\n\n".join(
                f"## {name} report\n{report}" for name, report in required.items()
            )
            system_message += (
                "\nSource-bounded Evidence Analysts have normalized disclosures, macro, flows, and any configured "
                "time-series model output below. "
                "Treat their reports as inputs, not final opinions. Reconcile them with verified price/technical "
                "evidence, preserve conflicts, and do not silently replace their dates, units, sources, missing-data "
                "flags, or limitations.\n" + evidence_reports
            )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}\n"
                    "{verified_snapshot}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)
        prompt = prompt.partial(verified_snapshot=verified_snapshot)

        chain = prompt | (llm.bind_tools(tools) if tools else llm)

        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "market_report": report,
        }

    return market_analyst_node
