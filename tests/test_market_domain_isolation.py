from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.agents.analysts.market_analyst import create_market_analyst


def test_korean_market_role_does_not_receive_raw_fundamentals():
    captured = []

    def invoke(prompt):
        captured.append(prompt.to_string())
        return AIMessage(content="market report")

    analyst = create_market_analyst(
        RunnableLambda(invoke), preload_verified_snapshot=True, market_only_snapshot=True
    )
    analyst(
        {
            "trade_date": "2026-08-19",
            "company_of_interest": "005930",
            "messages": [],
            "verified_market_snapshot": "## Verified market data snapshot\nPRICE_EVIDENCE\n## OpenDART periodic fundamentals\nFINANCIAL_CORPUS\n## Geopolitical news evidence\nCONFLICT_CORPUS",
        }
    )
    assert "PRICE_EVIDENCE" in captured[0]
    assert "FINANCIAL_CORPUS" not in captured[0]
    assert "CONFLICT_CORPUS" not in captured[0]
