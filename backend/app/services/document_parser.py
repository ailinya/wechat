"""Web/document to Markdown parsing service (task 3.6).

Self-contained (stdlib only): HTML via html.parser, DOCX via zipfile+XML,
PDF via FlateDecode stream text-operator extraction. Unsupported or damaged
files raise ParseError with a stable code so callers can record a readable
failure reason while keeping the original file/link.
"""

from __future__ import annotations

import html
import io
import json
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from importlib.metadata import version
from html.parser import HTMLParser
from xml.etree import ElementTree

import trafilatura
from bs4 import BeautifulSoup
from trafilatura.metadata import extract_metadata

HTML_TYPES = {"text/html", "application/xhtml+xml"}
TEXT_TYPES = {"text/plain", "text/markdown", "application/markdown"}
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_TYPE = "application/pdf"
DOCUMENT_PARSER_VERSION = "document_parser/1"
SUPPORTED_TYPES = HTML_TYPES | TEXT_TYPES | {DOCX_TYPE, PDF_TYPE}

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ParseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class ParsedDocument:
    content_markdown: str
    detected_type: str
    title: str | None = None
    warnings: list[str] = field(default_factory=list)
    published_at: str | None = None
    description: str | None = None
    extractor_version: str | None = None


# --- HTML -> Markdown ---


class _MarkdownHTMLParser(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}
    HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    BLOCK_TAGS = {"p", "div", "section", "article", "header", "footer", "figure", "figcaption"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.tokens: list[str] = []
        self.prefix = ""
        self.skip_depth = 0
        self.in_pre = False
        self.pre_buffer: list[str] = []
        self.list_stack: list[tuple[str, int]] = []
        self._link_href: str | None = None
        self.title_parts: list[str] = []
        self._in_title = False

    def _flush(self) -> None:
        text = "".join(self.tokens).strip()
        self.tokens = []
        if not text:
            self.prefix = ""
            return
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped:
                self.lines.append(f"{self.prefix}{stripped}")
        self.prefix = ""

    def _emit(self, line: str) -> None:
        self._flush()
        if line.strip():
            self.lines.append(line)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
            return
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in self.HEADINGS:
            self._flush()
            self.prefix = "#" * int(tag[1]) + " "
        elif tag in self.BLOCK_TAGS:
            self._flush()
        elif tag == "br":
            self._flush()
        elif tag in ("ul", "ol"):
            self._flush()
            self.list_stack.append((tag, 0))
        elif tag == "li":
            self._flush()
            if self.list_stack:
                kind, count = self.list_stack[-1]
                count += 1
                self.list_stack[-1] = (kind, count)
                self.prefix = "- " if kind == "ul" else f"{count}. "
        elif tag == "blockquote":
            self._flush()
            self.prefix = "> "
        elif tag == "pre" or (tag == "code" and "pre" in str(attrs_dict.get("class", ""))):
            self._flush()
            self.in_pre = True
            self.pre_buffer = []
        elif tag == "a":
            self._link_href = attrs_dict.get("href")
            self.tokens.append("[")
        elif tag in ("strong", "b"):
            self.tokens.append("**")
        elif tag in ("em", "i"):
            self.tokens.append("*")
        elif tag == "img":
            alt = attrs_dict.get("alt") or ""
            src = attrs_dict.get("src") or ""
            self.tokens.append(f"![{alt}]({src})")
        elif tag == "hr":
            self._emit("---")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            return
        if tag in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in self.HEADINGS or tag in self.BLOCK_TAGS:
            self._flush()
        elif tag in ("ul", "ol"):
            self._flush()
            if self.list_stack:
                self.list_stack.pop()
        elif tag == "li":
            self._flush()
        elif tag == "blockquote":
            self._flush()
        elif tag == "pre" or tag == "code":
            if self.in_pre:
                code = "".join(self.pre_buffer).strip("\n")
                self.in_pre = False
                self.pre_buffer = []
                self._emit("```\n" + code + "\n```")
        elif tag == "a":
            self.tokens.append(f"]({self._link_href or ''})")
            self._link_href = None
        elif tag in ("strong", "b"):
            self.tokens.append("**")
        elif tag in ("em", "i"):
            self.tokens.append("*")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
            return
        if self.skip_depth:
            return
        if self.in_pre:
            self.pre_buffer.append(data)
            return
        self.tokens.append(data)


def parse_html(source: str) -> ParsedDocument:
    parser = _MarkdownHTMLParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - malformed HTML should still yield text
        raise ParseError("html_parse_failed", f"HTML 解析失败: {type(exc).__name__}") from exc
    parser._flush()
    title = "".join(parser.title_parts).strip() or None
    markdown = "\n\n".join(parser.lines).strip()
    if not markdown:
        raise ParseError("empty_document", "网页无可读正文")
    return ParsedDocument(
        content_markdown=markdown, detected_type="text/html", title=title,
        extractor_version=DOCUMENT_PARSER_VERSION,
    )


def parse_article_html(source: str, url: str | None = None) -> ParsedDocument:
    """Extract article body and metadata without treating page chrome as content."""
    title_parser = _MarkdownHTMLParser()
    try:
        title_parser.feed(source)
        title_parser.close()
        metadata = extract_metadata(source, default_url=url, extensive=False).as_dict()
        markdown = trafilatura.extract(
            source,
            url=url,
            output_format="markdown",
            with_metadata=False,
            include_comments=False,
            include_tables=True,
            include_links=False,
            favor_precision=True,
        )
    except Exception as exc:  # noqa: BLE001 - parser failures must have a stable code
        raise ParseError("html_parse_failed", f"HTML 解析失败: {type(exc).__name__}") from exc
    markdown = (markdown or "").strip()
    if not markdown:
        raise ParseError("empty_document", "网页无可读正文")
    description = (metadata.get("description") or "").strip() or None
    if description and _normalize_text(markdown) == _normalize_text(description):
        raise ParseError("low_quality_extraction", "网页只提取到站点描述，未提取到文章正文")
    metadata_title = _clean_metadata_title(metadata.get("title"))
    fallback_title = "".join(title_parser.title_parts).strip() or None
    fallback_title = _clean_metadata_title(fallback_title)
    published_at = _explicit_published_date(source)
    return ParsedDocument(
        content_markdown=markdown,
        detected_type="text/html",
        title=metadata_title or fallback_title,
        published_at=published_at,
        description=description,
        extractor_version=f"trafilatura/{version('trafilatura')}",
    )


def _explicit_published_date(source: str) -> str | None:
    soup = BeautifulSoup(source, "html.parser")
    publication_keys={'article:published_time','og:published_time','date','pubdate','publishdate','publish_date','publication_date','datepublished','dc.date','dc.date.issued','dc.date.created'}
    for element in soup.find_all('meta'):
        key=str(element.get('property') or element.get('name') or element.get('itemprop') or '').casefold()
        value=element.get('content')
        if key in publication_keys and value and str(value).strip():
            return str(value).strip()[:128]
    for selector in (
        'meta[property="article:published_time"]',
        'meta[property="og:published_time"]',
        'meta[name="date"]',
        'meta[name="pubdate"]',
        'meta[name="publishdate"]',
        'meta[itemprop="datePublished"]',
        "time[datetime]",
    ):
        element = soup.select_one(selector)
        if element:
            value = element.get("content") or element.get("datetime")
            if value and str(value).strip():
                return str(value).strip()[:128]
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                value = item.get("datePublished") or item.get("dateCreated")
                if isinstance(value, str) and value.strip():
                    return value.strip()[:128]
                stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
    return None


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _clean_metadata_title(value: str | None) -> str | None:
    if not value:
        return None
    candidate = " ".join(value.split())
    if re.search(r"\b(?:var|let|const)\s+\w+\s*=|document\.write\s*\(", candidate, re.I):
        return None
    return candidate[:512] or None


# --- DOCX -> Markdown ---


def _docx_paragraph(paragraph: ElementTree.Element) -> str | None:
    text = "".join(node.text or "" for node in paragraph.iter(f"{W_NS}t")).strip()
    if not text:
        return None
    style = paragraph.find(f"{W_NS}pPr/{W_NS}pStyle")
    style_val = (style.get(f"{W_NS}val") if style is not None else "") or ""
    match = re.match(r"Heading([1-6])", style_val, re.IGNORECASE)
    if match:
        level = int(match.group(1))
        return f"{'#' * level} {text}"
    if style_val.lower() in ("title", "doctitle"):
        return f"# {text}"
    return text


def parse_docx(data: bytes) -> ParsedDocument:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ParseError("docx_parse_failed", "DOCX 文件损坏或不是有效的 Word 文档") from exc
    body = root.find(f"{W_NS}body")
    if body is None:
        raise ParseError("docx_parse_failed", "DOCX 文档缺少正文")

    blocks: list[str] = []
    for child in body:
        if child.tag == f"{W_NS}p":
            paragraph = _docx_paragraph(child)
            if paragraph:
                blocks.append(paragraph)
        elif child.tag == f"{W_NS}tbl":
            rows: list[list[str]] = []
            for tr in child.findall(f"{W_NS}tr"):
                cells = []
                for tc in tr.findall(f"{W_NS}tc"):
                    cell_text = " ".join(
                        value for p in tc.findall(f"{W_NS}p")
                        if (value := _docx_paragraph(p))
                    ).strip()
                    cells.append(cell_text.replace("|", "\\|"))
                if cells:
                    rows.append(cells)
            if rows:
                width = max(len(row) for row in rows)
                header = "| " + " | ".join(rows[0] + [""] * (width - len(rows[0]))) + " |"
                blocks.append(header)
                blocks.append("| " + " | ".join(["---"] * width) + " |")
                for row in rows[1:]:
                    blocks.append("| " + " | ".join(row + [""] * (width - len(row))) + " |")

    markdown = "\n\n".join(blocks).strip()
    if not markdown:
        raise ParseError("empty_document", "Word 文档无可读正文")
    return ParsedDocument(
        content_markdown=markdown, detected_type=DOCX_TYPE,
        extractor_version=DOCUMENT_PARSER_VERSION,
    )


# --- PDF -> Markdown (best-effort text extraction) ---


def _decode_pdf_string(raw: bytes) -> str:
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _unescape_literal(raw: bytes) -> bytes:
    result = bytearray()
    index = 0
    simple = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
    while index < len(raw):
        byte = raw[index]
        if byte == ord("\\") and index + 1 < len(raw):
            following = raw[index + 1]
            if following in simple:
                result.append(simple[following])
                index += 2
                continue
            if 48 <= following <= 55:  # octal escape
                octal = raw[index + 1:index + 4]
                result.append(int(octal, 8) & 0xFF)
                index += 1 + len(octal)
                continue
            if following in (10, 13):  # line continuation
                index += 2
                continue
            result.append(following)
            index += 2
            continue
        result.append(byte)
        index += 1
    return bytes(result)


_TEXT_OPS = re.compile(
    rb"(?:\(((?:\\.|[^\\)])*)\)|<([0-9A-Fa-f\s]+)>)\s*Tj|"
    rb"\[((?:\\.|[^\]])*)\]\s*TJ",
    re.DOTALL,
)
_ARRAY_STRING = re.compile(rb"\(((?:\\.|[^\\)])*)\)|<([0-9A-Fa-f\s]+)>", re.DOTALL)


def parse_pdf(data: bytes) -> ParsedDocument:
    if not data.startswith(b"%PDF-"):
        raise ParseError("pdf_parse_failed", "不是有效的 PDF 文件")
    texts: list[str] = []
    for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL):
        try:
            content = zlib.decompress(stream)
        except zlib.error:
            content = stream  # some PDFs leave streams uncompressed
        for match in _TEXT_OPS.finditer(content):
            literal, hexadecimal, array = match.groups()
            if array is not None:
                for piece in _ARRAY_STRING.finditer(array):
                    lit, hexa = piece.groups()
                    raw = _unescape_literal(lit) if lit is not None else bytes.fromhex(hexa.decode())
                    texts.append(_decode_pdf_string(raw))
            elif literal is not None:
                texts.append(_decode_pdf_string(_unescape_literal(literal)))
            elif hexadecimal is not None:
                cleaned = re.sub(rb"\s+", b"", hexadecimal)
                if len(cleaned) % 2:
                    cleaned += b"0"
                texts.append(_decode_pdf_string(bytes.fromhex(cleaned.decode())))
    readable = [text.strip() for text in texts if text.strip()]
    if not readable:
        raise ParseError("no_extractable_text", "PDF 无可读文本（可能为扫描件或加密文档）")
    return ParsedDocument(
        content_markdown="\n".join(readable), detected_type=PDF_TYPE,
        extractor_version=DOCUMENT_PARSER_VERSION,
    )


# --- dispatch ---


def parse_bytes(data: bytes, content_type: str, filename: str | None = None) -> ParsedDocument:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if not normalized and filename:
        suffix = filename.rsplit(".", 1)[-1].lower()
        normalized = {
            "html": "text/html", "htm": "text/html", "txt": "text/plain",
            "md": "text/markdown", "pdf": PDF_TYPE, "docx": DOCX_TYPE,
        }.get(suffix, "")
    if normalized in HTML_TYPES:
        return parse_html(data.decode("utf-8", errors="replace"))
    if normalized in TEXT_TYPES:
        text = data.decode("utf-8", errors="replace").strip()
        if not text:
            raise ParseError("empty_document", "文档无可读正文")
        return ParsedDocument(
            content_markdown=text, detected_type=normalized or "text/plain",
            extractor_version=DOCUMENT_PARSER_VERSION,
        )
    if normalized == DOCX_TYPE:
        return parse_docx(data)
    if normalized == PDF_TYPE:
        return parse_pdf(data)
    raise ParseError("unsupported_type", f"不支持的文档类型: {normalized or 'unknown'}")
