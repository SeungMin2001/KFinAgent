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

from .errors import VendorNotConfiguredError

_BASE_URL = "https://opendart.fss.or.kr/api"
_MAX_ARCHIVE_BYTES = 20_000_000


def _key() -> str:
    key = os.getenv("DART_API_KEY", "").strip()
    if not key:
        raise VendorNotConfiguredError("DART_API_KEY is required for disclosure analysis.")
    return key


def _json(path: str, *, allow_no_data: bool = False, **params) -> dict:
    response = requests.get(f"{_BASE_URL}/{path}", params={"crtfc_key": _key(), **params}, timeout=30)
    response.raise_for_status()
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
    response = requests.get(f"{_BASE_URL}/corpCode.xml", params={"crtfc_key": _key()}, timeout=60)
    response.raise_for_status()
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
    response = requests.get(
        f"{_BASE_URL}/document.xml",
        params={"crtfc_key": _key(), "rcept_no": receipt_no},
        timeout=60,
    )
    response.raise_for_status()
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


def disclosure_context(
    stock_code: str,
    as_of: str,
    *,
    lookback_days: int = 45,
    limit: int = 3,
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
        "- Every selected filing below includes its complete extracted visible text; no silent truncation is allowed.",
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
            document,
        ]
    lines += ["", "Treat the original filing text as the source of truth and distinguish facts from interpretation."]
    return "\n".join(lines)
