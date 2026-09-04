"""Explicit, checksummed historical evidence reuse, never an error fallback."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .global_risk import CONFLICT_QUERY, _analysis_day, global_risk_context

VERSION = "global-risk-v1"


def read_snapshot(directory, as_of):
    _analysis_day(as_of)
    path = Path(directory) / f"{as_of}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (payload.get("version"), payload.get("as_of"), payload.get("query")) != (
        VERSION,
        as_of,
        CONFLICT_QUERY,
    ):
        raise ValueError("Snapshot version/date/query mismatch")
    evidence = payload["evidence"]
    digest = hashlib.sha256(evidence.encode()).hexdigest()
    if digest != payload.get("sha256"):
        raise ValueError("Evidence snapshot checksum mismatch")
    for heading in (
        "## Geopolitical news evidence",
        "## Japan monetary conditions",
        "DEXJPUS",
        "DCOILBRENTEU",
    ):
        if heading not in evidence:
            raise ValueError("Incomplete global-risk snapshot")
    datetime.fromisoformat(payload["retrieved_at"])
    # New heading ensures provenance is routed to the same macro analyst.
    return evidence + (
        "\n\n## Geopolitical news evidence — frozen snapshot provenance\n"
        f"- Analysis date: {as_of}; retrieved at: {payload['retrieved_at']}; SHA256: {digest}\n"
        "- Explicit reuse of previously collected real evidence. Not a fresh API connection check, "
        "not proof of historical publication-time availability. No fallback was attempted."
    )


def collect_snapshot(directory, as_of):
    day = _analysis_day(as_of)
    # Freeze completed dates only; a current-day snapshot could stop at now
    # and inadvertently be reused later as a complete close-time observation.
    from zoneinfo import ZoneInfo

    if day >= datetime.now(ZoneInfo("Asia/Seoul")).date():
        raise ValueError("Only completed historical dates can be frozen")
    path = Path(directory) / f"{as_of}.json"
    if path.exists():
        read_snapshot(directory, as_of)
        return path
    evidence = global_risk_context(as_of)
    payload = {
        "version": VERSION,
        "as_of": as_of,
        "query": CONFLICT_QUERY,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(evidence.encode()).hexdigest(),
        "evidence": evidence,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create keeps an existing experiment's data immutable.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    read_snapshot(directory, as_of)
    return path
