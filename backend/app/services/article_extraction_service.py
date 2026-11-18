"""Article body extraction and deterministic time/keyword filtering."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import text

from app.errors import ApiError
from app.services import document_parser


@dataclass
class ArticleExtraction:
    status: str
    title: str | None = None
    markdown: str | None = None
    content_hash: str | None = None
    extractor_version: str | None = None
    published_at: datetime | None = None
    date_evidence: dict | None = None
    reason: str | None = None
    error_code: str | None = None


def _parse_date(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed_date = date.fromisoformat(raw[:10])
            except ValueError:
                return None
            parsed = datetime.combine(parsed_date, time.min)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _phrase(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def extract_article(
    raw_content: str,
    *,
    url: str,
    content_type: str = "text/html",
    status_code: int = 200,
    provider_published_at: str | datetime | None = None,
    run_started_at: datetime,
    time_range_days: int,
    keywords: list[str] | None = None,
) -> ArticleExtraction:
    """Extract one response and classify it without inventing missing dates."""
    if not 200 <= status_code < 300:
        return ArticleExtraction("failed", reason=f"HTTP {status_code}", error_code="http_error")
    try:
        if (content_type or "").split(";", 1)[0].strip().lower() in {
            "text/html", "application/xhtml+xml", ""
        }:
            parsed = document_parser.parse_article_html(raw_content, url)
        else:
            parsed = document_parser.parse_bytes(raw_content.encode("utf-8"), content_type)
    except document_parser.ParseError as exc:
        return ArticleExtraction("failed", reason=exc.message, error_code=exc.code)

    metadata_date = _parse_date(parsed.published_at)
    provider_date = _parse_date(provider_published_at)
    date_evidence = {
        "metadata": parsed.published_at,
        "provider": provider_published_at.isoformat() if isinstance(provider_published_at, datetime)
        else provider_published_at,
    }
    if metadata_date and provider_date and metadata_date.date() != provider_date.date():
        return ArticleExtraction(
            "review_required", parsed.title, parsed.content_markdown,
            hashlib.sha256(parsed.content_markdown.encode("utf-8")).hexdigest(),
            parsed.extractor_version, None, date_evidence, "date_conflict", "date_conflict",
        )
    published_at = metadata_date or provider_date
    if not published_at:
        return ArticleExtraction(
            "review_required", parsed.title, parsed.content_markdown,
            hashlib.sha256(parsed.content_markdown.encode("utf-8")).hexdigest(),
            parsed.extractor_version, None, date_evidence, "date_unknown", "date_unknown",
        )

    started = run_started_at.replace(tzinfo=timezone.utc) if run_started_at.tzinfo is None else run_started_at.astimezone(timezone.utc)
    if not 1 <= time_range_days <= 365:
        raise ValueError("time_range_days must be between 1 and 365")
    window_start = started - timedelta(days=time_range_days)
    if not window_start <= published_at <= started:
        return ArticleExtraction(
            "filtered", parsed.title, parsed.content_markdown,
            hashlib.sha256(parsed.content_markdown.encode("utf-8")).hexdigest(),
            parsed.extractor_version, published_at, date_evidence,
            "outside_time_window", "outside_time_window",
        )

    normalized_text = _phrase(f"{parsed.title or ''}\n{parsed.content_markdown}")
    normalized_keywords = [_phrase(item) for item in (keywords or []) if _phrase(item)]
    if normalized_keywords and not any(term in normalized_text for term in normalized_keywords):
        return ArticleExtraction(
            "filtered", parsed.title, parsed.content_markdown,
            hashlib.sha256(parsed.content_markdown.encode("utf-8")).hexdigest(),
            parsed.extractor_version, published_at, date_evidence,
            "keyword_mismatch", "keyword_mismatch",
        )
    return ArticleExtraction(
        "parsed", parsed.title, parsed.content_markdown,
        hashlib.sha256(parsed.content_markdown.encode("utf-8")).hexdigest(),
        parsed.extractor_version, published_at, date_evidence,
    )


def persist_candidate_extraction(
    conn,
    candidate_id,
    raw_content: str,
    extraction: ArticleExtraction,
) -> None:
    """Persist immutable source/extraction evidence and the candidate decision."""
    row = conn.execute(
        text("SELECT id FROM collection_candidates WHERE id=:id FOR UPDATE"),
        {"id": str(candidate_id)},
    ).first()
    if not row:
        raise ApiError(404, "candidate_not_found", "采集候选不存在")
    conn.execute(
        text(
            "INSERT INTO collection_snapshots "
            "(candidate_id, raw_content, markdown, content_hash, extractor_version, title, date_evidence) "
            "VALUES (:candidate, :raw, :markdown, :hash, :version, :title, :date)"
        ),
        {
            "candidate": str(candidate_id), "raw": raw_content,
            "markdown": extraction.markdown, "hash": extraction.content_hash,
            "version": extraction.extractor_version, "title": extraction.title,
            "date": json.dumps(extraction.date_evidence, ensure_ascii=False),
        },
    )
    conn.execute(
        text(
            "UPDATE collection_candidates SET status=:status, title=COALESCE(:title, title), "
            "provider_published_at=COALESCE(:published, provider_published_at), error=:error, updated_at=now() "
            "WHERE id=:id"
        ),
        {
            "status": extraction.status,
            "title": extraction.title,
            "published": extraction.published_at,
            "error": extraction.reason,
            "id": str(candidate_id),
        },
    )
