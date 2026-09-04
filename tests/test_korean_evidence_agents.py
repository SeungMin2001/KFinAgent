from types import SimpleNamespace

import pytest

from tradingagents.agents.analysts.korean_evidence_analysts import (
    EvidenceReport,
    create_disclosure_evidence_analyst,
)
from tradingagents.dataflows.korean_evidence import evidence_for_domain

SNAPSHOT = """## Verified market data snapshot for 005930
- Close: 70,000 KRW

## OpenDART disclosures (official metadata)
- 2026-09-01 | 공급계약 | 100 KRW

## US macro snapshot (FRED; primary macro context for Korean equities)

## FRED: Federal Funds Effective Rate (FEDFUNDS)
- Latest: 4.0 percent

## Bank of Korea ECOS macro snapshot (official)
- Base rate: 2.5 percent

## KIS investor flow snapshot (official)
- 외국인: 최근 5일 누적 순매수 1,000주
"""


@pytest.mark.unit
def test_domain_splitter_prevents_cross_domain_evidence_leakage():
    disclosure = evidence_for_domain(SNAPSHOT, "disclosure")
    macro = evidence_for_domain(SNAPSHOT, "macro")
    flow = evidence_for_domain(SNAPSHOT, "flow")

    assert "공급계약" in disclosure and "Fed funds" not in disclosure
    assert "Federal Funds" in macro and "Base rate" in macro and "외국인" not in macro
    assert "외국인" in flow and "Close" not in flow


class _StructuredInvoker:
    def __init__(self, owner):
        self.owner = owner

    def invoke(self, prompt):
        self.owner.prompt = prompt
        self.owner.prompts = getattr(self.owner, "prompts", []) + [prompt]
        return EvidenceReport(
            as_of="2026-09-02",
            observations=[],
            conflicts=[],
            missing_data=[],
            limitations=["metadata only"],
            summary="No investment recommendation.",
        )


class _FakeLLM:
    def with_structured_output(self, _schema):
        return _StructuredInvoker(self)

    def invoke(self, _prompt):
        return SimpleNamespace(content="fallback")


class _FailingStructuredLLM(_FakeLLM):
    def with_structured_output(self, _schema):
        return self

    def invoke(self, _prompt):
        raise ValueError("invalid schema response")


@pytest.mark.unit
def test_disclosure_agent_sees_only_disclosure_section_and_returns_report():
    llm = _FakeLLM()
    state = {
        "trade_date": "2026-09-02",
        "verified_market_snapshot": SNAPSHOT,
    }
    result = create_disclosure_evidence_analyst(llm)(state)
    rendered_prompt = "\n".join(message.content for message in llm.prompt)

    assert "공급계약" in rendered_prompt
    assert "Fed funds" not in rendered_prompt
    assert "외국인" not in rendered_prompt
    assert "No investment recommendation." in result["disclosure_report"]


@pytest.mark.unit
def test_evidence_agent_treats_prior_report_as_non_factual_context():
    llm = _FakeLLM()
    state = {
        "trade_date": "2026-09-02",
        "verified_market_snapshot": SNAPSHOT,
        "historical_report_context": "Prior report says a hypothetical 999 KRW result.",
    }

    create_disclosure_evidence_analyst(llm)(state)
    rendered_prompt = "\n".join(message.content for message in llm.prompt)

    assert "999 KRW" in rendered_prompt
    assert "not a factual source" in rendered_prompt


@pytest.mark.unit
def test_evidence_agent_fails_when_its_verified_section_is_missing():
    with pytest.raises(RuntimeError, match="no verified disclosure evidence"):
        create_disclosure_evidence_analyst(_FakeLLM())(
            {"trade_date": "2026-09-02", "verified_market_snapshot": "## unrelated\n- x"}
        )


@pytest.mark.unit
def test_evidence_agent_does_not_fallback_to_unstructured_text():
    with pytest.raises(RuntimeError, match="structured output failed"):
        create_disclosure_evidence_analyst(_FailingStructuredLLM())(
            {"trade_date": "2026-09-02", "verified_market_snapshot": SNAPSHOT}
        )


@pytest.mark.unit
def test_long_disclosure_is_fully_chunked_then_synthesized():
    llm = _FakeLLM()
    body = "".join(f"line-{index:04d} detail\n" for index in range(300))
    snapshot = "## OpenDART disclosures (official metadata and original document text)\n" + body

    create_disclosure_evidence_analyst(llm, max_chunk_chars=1_000)(
        {"trade_date": "2026-09-02", "verified_market_snapshot": snapshot}
    )

    # Multiple map calls plus one final synthesis call.
    assert len(llm.prompts) > 2
    mapped = "\n".join(
        message.content
        for prompt in llm.prompts[:-1]
        for message in prompt
    )
    assert "line-0000 detail" in mapped
    assert "line-0299 detail" in mapped
