from __future__ import annotations

import io
import zipfile

import pytest

from tradingagents.dataflows import dart


class _Response:
    status_code = 200

    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


def _archive(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return output.getvalue()


@pytest.mark.unit
def test_disclosure_document_reads_every_original_file(monkeypatch):
    payload = _archive(
        {
            "main.xml": "<DOCUMENT><P>계약금액 100억원</P><TABLE><TR><TD>기간</TD><TD>3년</TD></TR></TABLE></DOCUMENT>",
            "appendix.xml": "<DOCUMENT><P>정정 전 금액 90억원</P></DOCUMENT>",
        }
    )
    monkeypatch.setenv("DART_API_KEY", "test-key")
    monkeypatch.setattr(dart.requests, "get", lambda *args, **kwargs: _Response(payload))

    text = dart.disclosure_document("20260903000001")

    assert "계약금액 100억원" in text
    assert "기간" in text and "3년" in text
    assert "정정 전 금액 90억원" in text
    assert "main.xml" in text and "appendix.xml" in text


@pytest.mark.unit
def test_disclosure_context_keeps_complete_document(monkeypatch):
    monkeypatch.setattr(
        dart,
        "recent_disclosures",
        lambda *args, **kwargs: [
            {
                "receipt_no": "20260903000001",
                "date": "20260903",
                "title": "공급계약",
                "filer": "회사",
                "url": "https://dart.example/1",
            }
        ],
    )
    monkeypatch.setattr(dart, "disclosure_document", lambda _receipt: "전체본문")

    text = dart.disclosure_context("005930", "2026-09-03")
    assert "전체본문" in text
