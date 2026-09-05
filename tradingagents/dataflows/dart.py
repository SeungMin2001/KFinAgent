"""Minimal strict client for official OpenDART disclosure metadata and documents."""

from __future__ import annotations

import io
import os
import re
import zipfile
from datetime import date, timedelta
from html import unescape
from xml.etree import ElementTree

import requests

from .dart_compact import archive_content, compact_document, financial_context
from .errors import VendorNotConfiguredError

_BASE_URL = "https://opendart.fss.or.kr/api"
_MAX_ARCHIVE_BYTES = 20_000_000


def _get(path: str, *, timeout: int = 30, **params):
    try:
        response = requests.get(
            f"{_BASE_URL}/{path}", params={"crtfc_key": _key(), **params}, timeout=timeout
        )
        response.raise_for_status()
        return response
    except requests.RequestException:
        # Requests exceptions contain the authentication key in their URL.
        raise RuntimeError(f"OpenDART transport failed: {path}") from None


def _key() -> str:
    key = os.getenv("DART_API_KEY", "").strip()
    if not key:
        raise VendorNotConfiguredError("DART_API_KEY is required for disclosure analysis.")
    return key


def _json(path: str, *, allow_no_data: bool = False, **params) -> dict:
    response = _get(path, **params)
    payload = response.json()
    if allow_no_data and payload.get("status") == "013":
        return payload
    if payload.get("status") != "000":
        raise RuntimeError(f"OpenDART request failed ({payload.get('status')}): {payload.get('message')}")
    return payload


def resolve_corp_code(stock_code: str) -> str:
    """Resolve a six-digit KRX code through OpenDART's official corp-code file."""
    if not re.fullmatch(r"\d{6}", stock_code):
        raise ValueError("stock_code must be six digits")
    response = _get("corpCode.xml", timeout=60)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        xml = archive.read(archive.namelist()[0]).decode("utf-8", errors="replace")
    root = ElementTree.fromstring(xml)
    for item in root.findall("list"):
        if (item.findtext("stock_code") or "").strip() == stock_code:
            corp_code = (item.findtext("corp_code") or "").strip()
            if re.fullmatch(r"\d{8}", corp_code):
                return corp_code
    raise LookupError(f"OpenDART has no listed-company mapping for {stock_code}")


def recent_disclosures(stock_code: str, as_of: str, lookback_days: int = 45, limit: int = 8) -> list[dict]:
    end = date.fromisoformat(as_of)
    corp_code = resolve_corp_code(stock_code)
    payload = _json(
        "list.json",
        allow_no_data=True,
        corp_code=corp_code,
        bgn_de=(end - timedelta(days=lookback_days)).strftime("%Y%m%d"),
        end_de=end.strftime("%Y%m%d"),
        page_count=limit,
    )
    return [
        {
            "receipt_no": item["rcept_no"],
            "date": item["rcept_dt"],
            "title": item["report_nm"],
            "filer": item.get("flr_nm", ""),
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item['rcept_no']}",
        }
        for item in payload.get("list", [])
    ]


def disclosure_document(receipt_no: str) -> str:
    """Download and return all visible text in an OpenDART original-document ZIP.

    OpenDART's ``document.xml`` endpoint returns a ZIP containing one or more
    XML documents. We read every regular member and never silently truncate a
    filing. Oversized or malformed archives fail the strict enhanced workflow.
    """
    if not re.fullmatch(r"\d{14}", receipt_no):
        raise ValueError("OpenDART receipt_no must be 14 digits")
    response = _get("document.xml", rcept_no=receipt_no, timeout=60)
    try:
        archive = zipfile.ZipFile(io.BytesIO(response.content))
    except zipfile.BadZipFile as exc:
        detail = response.content[:500].decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenDART original document is not a ZIP: {detail}") from exc

    members = [item for item in archive.infolist() if not item.is_dir()]
    if not members:
        raise RuntimeError(f"OpenDART original document ZIP is empty: {receipt_no}")
    total_size = sum(item.file_size for item in members)
    if total_size > _MAX_ARCHIVE_BYTES:
        raise RuntimeError(
            f"OpenDART original document exceeds {_MAX_ARCHIVE_BYTES:,} bytes: {receipt_no}"
        )

    archive_content(receipt_no, "original.zip", response.content)

    documents = []
    for item in members:
        raw = archive.read(item)
        markup = raw.decode("utf-8-sig", errors="replace")
        # DART XML is presentation-oriented. Preserve all visible text nodes
        # and table-cell boundaries as lines while removing markup/scripts.
        markup = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
        markup = re.sub(r"(?i)</?(?:tr|p|div|section|title|h[1-6])\b[^>]*>", "\n", markup)
        markup = re.sub(r"(?i)</?(?:td|th)\b[^>]*>", " | ", markup)
        text = unescape(re.sub(r"(?s)<[^>]+>", " ", markup))
        lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip(" | ") for line in text.splitlines()]
        visible = "\n".join(line for line in lines if line)
        if visible:
            documents.append(f"#### Original file: {item.filename}\n\n{visible}")
    if not documents:
        raise RuntimeError(f"OpenDART original document has no visible text: {receipt_no}")
    return "\n\n".join(documents)


def periodic_fundamentals_context(stock_code: str, as_of: str, *, compact: bool = False) -> str:
    """Select a periodic filing independently of the recent-disclosure quota.

    Exclude the analysis date because list.json supplies dates, not intraday
    publication times. Never use today's final-report flag in a past replay.
    """
    end = date.fromisoformat(as_of) - timedelta(days=1)
    corp_code = resolve_corp_code(stock_code)
    payload = _json(
        "list.json", allow_no_data=True, corp_code=corp_code,
        bgn_de=(end - timedelta(days=550)).strftime("%Y%m%d"),
        end_de=end.strftime("%Y%m%d"), pblntf_ty="A", last_reprt_at="N",
        sort="date", sort_mth="desc", page_count=100,
    )
    if int(payload.get("total_page", 1)) > 1:
        raise RuntimeError("DART periodic filing selection requires pagination; stopping rather than truncating")
    rows = payload.get("list", [])
    candidates = []
    for row in rows:
        submitted = date.fromisoformat(f"{row['rcept_dt'][:4]}-{row['rcept_dt'][4:6]}-{row['rcept_dt'][6:8]}")
        if submitted > end:
            raise ValueError("DART returned a future periodic filing")
        match = re.search(r"\((\d{4})\.(\d{2})\)", row["report_nm"])
        if not match:
            raise ValueError("DART periodic report has no recognizable fiscal period")
        period = (int(match[1]), int(match[2]))
        if not 1 <= period[1] <= 12 or period > (end.year, end.month):
            raise ValueError("Invalid DART fiscal period")
        candidates.append((period, row["rcept_dt"], row["rcept_no"], row))
    if not candidates:
        raise RuntimeError("No periodic DART filing available; fundamentals collection stopped")
    period, _, receipt, selected = max(candidates, key=lambda x: x[:3])
    document = disclosure_document(receipt)
    content = (
        financial_context(corp_code, period, receipt, _json)
        + "\n\n### Selected original passages\n"
        + compact_document(receipt, document)
        if compact else document
    )
    return "\n\n".join([
        "## OpenDART periodic fundamentals (separate financial-report selection)",
        f"- Analysis date: {as_of}; filing cutoff: {end}; fiscal period: {period[0]}-{period[1]:02d}",
        f"- Selected report: {selected['report_nm']}; received: {selected['rcept_dt']}",
        f"- Source: https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
        "- Latest fiscal period, then latest submission within cutoff. "
        + ("Structured financial rows plus explicitly selected passages; full source archived."
           if compact else "Full extracted text, not a computed financial ratio feed."),
        "- Preserve consolidated versus separate accounts, reporting periods and units. Do not infer missing figures. "
        "Correction-only attachments may not contain complete statements; disclose this rather than assume completeness. "
        "The API does not prove the original document was never revised after retrieval-date cutoff.",
        content,
    ])


def disclosure_context(
    stock_code: str,
    as_of: str,
    *,
    lookback_days: int = 45,
    limit: int = 3,
    compact: bool = False,
) -> str:
    """Render metadata plus complete visible text for selected recent filings."""
    disclosures = recent_disclosures(stock_code, as_of, lookback_days=lookback_days, limit=limit)
    if not disclosures:
        return "## OpenDART disclosures\n\nNo disclosures were returned in the requested lookback window."
    lines = [
        "## OpenDART disclosures (official metadata and original document text)",
        "",
        f"- Window: {lookback_days} days ending {as_of}",
        f"- Selected filings: {len(disclosures)} (limit {limit})",
        ("- Selected passages only; full source archives and omitted-line counts are recorded."
         if compact else "- Every selected filing below includes its complete extracted visible text; no silent truncation is allowed."),
    ]
    for item in disclosures:
        document = disclosure_document(item["receipt_no"])
        lines += [
            "",
            f"### {item['date']} | {item['title']}",
            f"- Receipt: {item['receipt_no']}",
            f"- Filer: {item['filer']}",
            f"- Source: {item['url']}",
            "",
            compact_document(item["receipt_no"], document) if compact else document,
        ]
    lines += ["", "Treat the original filing text as the source of truth and distinguish facts from interpretation."]
    return "\n".join(lines)
