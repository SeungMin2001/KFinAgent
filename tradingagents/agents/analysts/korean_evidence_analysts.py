"""Source-bounded evidence analysts for the enhanced Korean-stock workflow."""

from __future__ import annotations

from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from tradingagents.agents.utils.agent_utils import get_language_instruction
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_strict,
)
from tradingagents.dataflows.korean_evidence import evidence_for_domain


class EvidenceItem(BaseModel):
    fact: str = Field(description="Observed fact, including the exact value and unit when present.")
    period: str = Field(description="Observation period or effective date; use 'not provided' if absent.")
    source: str = Field(description="Exact named source from the supplied evidence.")
    direction: Literal["positive", "neutral", "negative", "mixed", "not_applicable"]
    interpretation: str = Field(description="Minimal interpretation; do not make an investment recommendation.")


class EvidenceReport(BaseModel):
    as_of: str = Field(description="Analysis date, kept distinct from each observation's period.")
    observations: list[EvidenceItem] = Field(description="Material, non-duplicative observations only.")
    conflicts: list[str] = Field(description="Contradictions within this domain; empty when none are visible.")
    missing_data: list[str] = Field(description="Material fields not present in the supplied evidence.")
    limitations: list[str] = Field(description="Limits on inference, timing, coverage, or causality.")
    summary: str = Field(description="Objective synthesis without buy/sell, target-price, or sizing advice.")


def render_evidence_report(report: EvidenceReport) -> str:
    lines = [f"**As of**: {report.as_of}", "", "### Observations"]
    if report.observations:
        lines += [
            f"- **{item.fact}** | period: {item.period} | source: {item.source} | "
            f"direction: {item.direction} | interpretation: {item.interpretation}"
            for item in report.observations
        ]
    else:
        lines.append("- No material observation available.")
    for title, values in (
        ("Conflicts", report.conflicts),
        ("Missing data", report.missing_data),
        ("Limitations", report.limitations),
    ):
        lines += ["", f"### {title}"]
        lines += [f"- {value}" for value in values] or ["- None identified."]
    lines += ["", "### Objective summary", report.summary]
    return "\n".join(lines)


_DOMAIN_INSTRUCTIONS = {
    "disclosure": (
        "Disclosure Evidence Analyst",
        "disclosure_report",
        "Extract filing type, filing/effective dates, amounts, counterparties, periods, and correction status. "
        "Distinguish disclosed fact from possible impact. Do not label a filing simply as good or bad.",
    ),
    "macro": (
        "Macro Evidence Analyst",
        "macro_report",
        "Compare current, prior, and change values when supplied. Keep observation date, reference period, "
        "and release timing distinct. Explain only the conventional transmission channel to Korean equities; "
        "do not claim causation from correlation.",
    ),
    "flow": (
        "Flow Evidence Analyst",
        "flow_report",
        "Report investor-group cumulative net flow, window, and streak exactly as supplied. Identify agreement "
        "or divergence across foreign, institutional, investment-trust, and fund flows. Flow alone is not a price forecast.",
    ),
}


def _split_evidence(text: str, max_chars: int) -> list[str]:
    """Split text without dropping content, preferring line boundaries."""
    if max_chars < 1_000:
        raise ValueError("evidence chunk size must be at least 1,000 characters")
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in text.splitlines(keepends=True):
        while len(line) > max_chars:
            if current:
                chunks.append("".join(current))
                current, current_size = [], 0
            chunks.append(line[:max_chars])
            line = line[max_chars:]
        if current and current_size + len(line) > max_chars:
            chunks.append("".join(current))
            current, current_size = [], 0
        current.append(line)
        current_size += len(line)
    if current:
        chunks.append("".join(current))
    return chunks or [text]


def _evidence_prompt(
    *,
    agent_name: str,
    domain_instruction: str,
    analysis_date: str,
    evidence: str,
    part_label: str = "",
):
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are {agent_name}. You normalize verified evidence for a downstream Market Analyst. "
                "You are not an investment-decision agent. {no_tools} "
                "Use no fact that is absent from the evidence. Never calculate a new statistic mentally; "
                "only repeat deterministic calculations already present. Every observation must preserve its "
                "value, unit, period/date, and named source. Mark missing information instead of estimating it. "
                "Do not issue buy/sell/hold, portfolio weights, price targets, or trade instructions. "
                "Preserve conflicting facts and timing limitations. {domain_instruction} {part_label}"
                "{language_instruction}\n\nAnalysis date: {analysis_date}\n\nVerified domain evidence:\n{evidence}",
            )
        ]
    ).format_messages(
        agent_name=agent_name,
        no_tools=NO_EXTERNAL_TOOLS,
        domain_instruction=domain_instruction,
        part_label=part_label,
        language_instruction=get_language_instruction(),
        analysis_date=analysis_date,
        evidence=evidence,
    )


def _create_evidence_analyst(llm, domain: str, max_chunk_chars: int = 60_000):
    agent_name, report_key, domain_instruction = _DOMAIN_INSTRUCTIONS[domain]
    structured_llm = bind_structured(llm, EvidenceReport, agent_name)

    def node(state):
        snapshot = state.get("verified_market_snapshot", "")
        evidence = evidence_for_domain(snapshot, domain)
        if not evidence:
            raise RuntimeError(f"{agent_name} received no verified {domain} evidence section")

        chunks = _split_evidence(evidence, max_chunk_chars) if domain == "disclosure" else [evidence]
        partial_reports = []
        for index, chunk in enumerate(chunks, start=1):
            part_label = ""
            if len(chunks) > 1:
                part_label = (
                    f"This is part {index} of {len(chunks)} of one complete disclosure corpus. "
                    "Analyze every fact in this part, but do not claim something is absent from the entire corpus "
                    "merely because it is absent from this part."
                )
            prompt = _evidence_prompt(
                agent_name=agent_name,
                domain_instruction=domain_instruction,
                analysis_date=state["trade_date"],
                evidence=chunk,
                part_label=part_label,
            )
            partial_reports.append(
                invoke_structured_strict(structured_llm, prompt, render_evidence_report, agent_name)
            )

        report = partial_reports[0]
        if len(partial_reports) > 1:
            combined = "\n\n".join(
                f"## Partial report {index}/{len(partial_reports)}\n{text}"
                for index, text in enumerate(partial_reports, start=1)
            )
            synthesis_prompt = _evidence_prompt(
                agent_name=agent_name,
                domain_instruction=(
                    "Consolidate the partial reports below into one complete report. Deduplicate exact repeats, "
                    "preserve all material facts and source references, carry forward conflicts and limitations, "
                    "and do not introduce facts absent from the partial reports."
                ),
                analysis_date=state["trade_date"],
                evidence=combined,
            )
            report = invoke_structured_strict(
                structured_llm, synthesis_prompt, render_evidence_report, agent_name
            )
        return {report_key: report}

    return node


def create_disclosure_evidence_analyst(llm, max_chunk_chars: int = 60_000):
    return _create_evidence_analyst(llm, "disclosure", max_chunk_chars=max_chunk_chars)


def create_macro_evidence_analyst(llm):
    return _create_evidence_analyst(llm, "macro")


def create_flow_evidence_analyst(llm):
    return _create_evidence_analyst(llm, "flow")
