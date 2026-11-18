"""Tests for the document-to-Markdown parser (task 3.6).

Fixtures are generated in-memory so Chinese HTML/DOCX/PDF samples are
reproducible without external files or dependencies.
"""

from __future__ import annotations

import io
import zipfile
import zlib
from xml.sax.saxutils import escape

import pytest

from app.services import document_parser as parser

DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx_fixture(paragraphs: list[tuple[str | None, str]]) -> bytes:
    body = ""
    for style, text in paragraphs:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body += (
            f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
        )
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{DOCX_NS}"><w:body>{body}</w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def _pdf_fixture(text: str) -> bytes:
    encoded = b"\xfe\xff" + text.encode("utf-16-be")
    literal = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    content = b"BT /F1 12 Tf 72 720 Td (" + literal + b") Tj ET\n"
    compressed = zlib.compress(content)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        b"<< /Length " + str(len(compressed)).encode() + b" >>\nstream\n" + compressed + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    ).encode()
    return bytes(out)


HTML = """<!doctype html><html><head><title>固件发布说明</title>
<style>.x{color:red}</style></head><body>
<h1>固件 2.1 发布说明</h1>
<p>本次更新修复了 <strong>中文输入</strong> 问题，详见 <a href="https://example.com/detail">公告</a>。</p>
<h2>更新要点</h2>
<ul><li>修复中文输入</li><li>提升稳定性</li></ul>
<p>备注：旧版本不受影响。</p>
</body></html>"""


def test_parse_chinese_html() -> None:
    result = parser.parse_html(HTML)
    assert result.title == "固件发布说明"
    assert "# 固件 2.1 发布说明" in result.content_markdown
    assert "**中文输入**" in result.content_markdown
    assert "[公告](https://example.com/detail)" in result.content_markdown
    assert "- 修复中文输入" in result.content_markdown
    assert "color:red" not in result.content_markdown  # style skipped


def test_parse_chinese_docx() -> None:
    data = _docx_fixture([
        ("Title", "行业研究报告"),
        ("Heading1", "一、市场概况"),
        (None, "中文正文段落，包含关键结论。"),
    ])
    result = parser.parse_bytes(data, parser.DOCX_TYPE)
    assert "# 行业研究报告" in result.content_markdown
    assert "# 一、市场概况" in result.content_markdown
    assert "中文正文段落" in result.content_markdown


def test_parse_chinese_pdf() -> None:
    data = _pdf_fixture("固件 2.1 修复了中文输入问题")
    result = parser.parse_bytes(data, parser.PDF_TYPE)
    assert "固件 2.1 修复了中文输入问题" in result.content_markdown


def test_plain_text_passthrough() -> None:
    result = parser.parse_bytes("这是纯文本正文".encode(), "text/plain")
    assert result.content_markdown == "这是纯文本正文"


def test_dispatch_by_filename() -> None:
    data = _docx_fixture([(None, "按文件名识别")])
    result = parser.parse_bytes(data, "", filename="report.docx")
    assert "按文件名识别" in result.content_markdown


def test_unsupported_type_reports_specific_code() -> None:
    with pytest.raises(parser.ParseError) as exc:
        parser.parse_bytes(b"data", "application/octet-stream")
    assert exc.value.code == "unsupported_type"


def test_corrupt_docx_reports_specific_code() -> None:
    with pytest.raises(parser.ParseError) as exc:
        parser.parse_bytes(b"not a zip", parser.DOCX_TYPE)
    assert exc.value.code == "docx_parse_failed"


def test_not_pdf_reports_specific_code() -> None:
    with pytest.raises(parser.ParseError) as exc:
        parser.parse_bytes(b"not a pdf", parser.PDF_TYPE)
    assert exc.value.code == "pdf_parse_failed"


def test_empty_html_reports_specific_code() -> None:
    with pytest.raises(parser.ParseError) as exc:
        parser.parse_html("<html><body></body></html>")
    assert exc.value.code == "empty_document"
