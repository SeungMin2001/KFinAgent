"""Auditable DART excerpts and receipt-matched structured financial statements."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def archive_content(receipt: str, kind: str, content: str | bytes) -> str:
    data = content.encode("utf-8") if isinstance(content, str) else content
    digest = hashlib.sha256(data).hexdigest()
    directory = Path(__file__).resolve().parents[2] / "artifacts" / "dart_sources" / receipt
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{kind}_{digest}"
    if not path.exists():
        path.write_bytes(data)
    return f"{path.relative_to(directory.parents[1])}; sha256={digest}"


def compact_document(receipt: str, document: str, budget: int = 12_000) -> str:
    """Keep complete source lines and context, explicitly accounting for omissions."""
    source = archive_content(receipt, "visible.txt", document)
    lines = document.splitlines()
    keywords = re.compile(
        r"매출|영업이익|순이익|현금흐름|부채|자본|계약|수주|위험|소송|우발|"
        r"정정|취소|해지|철회|증자|감자|배당|자기주식|사업의 내용|주요 제품|연구개발"
    )
    candidates = set(range(min(12, len(lines))))
    for index, line in enumerate(lines):
        if keywords.search(line):
            candidates.update(range(max(0, index - 2), min(len(lines), index + 3)))
    # Spread the budget across the filing instead of taking only its beginning.
    ordered = sorted(candidates)
    selected = {}
    used = 0
    while ordered:
        next_round = []
        for index in ordered[::2]:
            entry = f"L{index + 1}: {lines[index]}"
            if used + len(entry) + 1 <= budget:
                selected[index] = entry
                used += len(entry) + 1
        next_round.extend(ordered[1::2])
        ordered = next_round
    if not selected:
        raise RuntimeError("DART source lines exceed excerpt budget; manual review required")
    return "\n".join([
        f"- Full source archive: {source}",
        f"- Selection policy: keyword-context-v1; {len(document)} source characters; "
        f"{len(selected)}/{len(lines)} source lines shown; {len(lines) - len(selected)} omitted.",
        "- Excerpts are incomplete. Gaps in line numbers are omissions, not adjacent table rows. "
        "Do not infer that an unselected fact is absent from the filing. "
        "Use the structured financial rows for amounts and periods; excerpts may lack table headers.",
        *[selected[index] for index in sorted(selected)],
    ])


def financial_context(corp_code: str, period: tuple[int, int], receipt: str, request) -> str:
    codes = {3: "11013", 6: "11012", 9: "11014", 12: "11011"}
    if period[1] not in codes:
        raise ValueError("Unsupported fiscal month for DART structured financials")
    statements = []
    for scope in ("CFS", "OFS"):
        payload = request(
            "fnlttSinglAcntAll.json", allow_no_data=True,
            corp_code=corp_code, bsns_year=str(period[0]), reprt_code=codes[period[1]], fs_div=scope,
        )
        archive = archive_content(receipt, f"financial_{scope}.json", json.dumps(
            {"retrieved_at": datetime.now(timezone.utc).isoformat(), "payload": payload},
            ensure_ascii=False,
        ))
        rows = payload.get("list", [])
        if not rows:
            if payload.get("status") != "013":
                raise RuntimeError("DART financial response unexpectedly empty")
            statements.append(f"- {scope}: official no-data response (013); archive: {archive}")
            continue
        for row in rows:
            if (row.get("rcept_no") != receipt or row.get("corp_code") != corp_code
                    or row.get("bsns_year") != str(period[0])
                    or row.get("reprt_code") != codes[period[1]]):
                raise RuntimeError("DART financial receipt/period mismatch; historical analysis stopped")
        # Keep every value while encoding repeated field names only once.
        shared = {"rcept_no", "corp_code", "bsns_year", "reprt_code"}
        columns = sorted({key for row in rows for key in row} - shared)
        encoded = {
            "receipt": receipt, "year": str(period[0]), "report_code": codes[period[1]],
            "columns": columns,
            "rows": [[row.get(key) for key in columns] for row in rows],
        }
        statements.extend([
            f"### Structured financial statements: {scope}; archive: {archive}",
            json.dumps(encoded, ensure_ascii=False, separators=(",", ":")),
        ])
    return "\n\n".join([
        "- Source: OpenDART fnlttSinglAcntAll.json; receipt must match selected historical filing.",
        "- CFS=consolidated, OFS=separate. Do not mix accounts or currencies. "
        "thstrm_amount on interim IS/CIS is the three-month amount; thstrm_add_amount is cumulative. "
        "Keep comparative period labels; missing fields are unknown. No ratios were calculated. "
        "Receipt matching does not guarantee a historical data vintage.",
        *statements,
    ])
