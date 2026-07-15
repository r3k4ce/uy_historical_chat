from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from artigas_mvp_backend.models import Citation

logger = logging.getLogger(__name__)


class CitationProcessingError(Exception):
    """Raised when provider citation offsets cannot be safely normalized."""


@dataclass(frozen=True)
class RawFileCitation:
    source_identity: str | None
    file_name: str | None
    page_number: int | None
    byte_start: int
    byte_end: int


def _value(annotation: object, *names: str) -> Any:
    for name in names:
        if isinstance(annotation, dict) and name in annotation:
            return annotation[name]
        value = getattr(annotation, name, None)
        if value is not None:
            return value
    return None


def _to_raw(annotation: object) -> RawFileCitation | None:
    if isinstance(annotation, RawFileCitation):
        return annotation
    kind = _value(annotation, "type", "annotation_type")
    if kind not in {"file_citation", "file_search_citation"}:
        logger.debug("Ignoring non-file citation annotation type")
        return None
    start = _value(annotation, "start_index", "start", "start_offset")
    end = _value(annotation, "end_index", "end", "end_offset")
    if not isinstance(start, int) or not isinstance(end, int):
        raise CitationProcessingError("Citation offsets are missing or invalid")
    source = _value(annotation, "source_id", "file_id", "source", "uri")
    name = _value(annotation, "file_name", "filename", "title")
    page = _value(annotation, "page_number", "page")
    if page is not None and not isinstance(page, int):
        page = None
    return RawFileCitation(
        str(source) if source else None,
        str(name) if name is not None else None,
        page,
        start,
        end,
    )


def normalize_citations(final_text: str, annotations: Iterable[object]) -> tuple[Citation, ...]:
    indexed: list[tuple[RawFileCitation, int]] = []
    for provider_order, annotation in enumerate(annotations):
        raw = _to_raw(annotation)
        if raw is not None:
            indexed.append((raw, provider_order))
    indexed.sort(key=lambda item: (item[0].byte_start, item[0].byte_end, item[1]))

    final_bytes = final_text.encode("utf-8")
    seen: set[tuple[str, int | None, int, int]] = set()
    result: list[Citation] = []
    for raw, _ in indexed:
        if not 0 <= raw.byte_start <= raw.byte_end <= len(final_bytes):
            raise CitationProcessingError("Citation offsets are outside the response")
        normalized_name = (raw.file_name or "").strip()
        identity = raw.source_identity or normalized_name
        physical_page = (
            raw.page_number + 1 if raw.page_number is not None and raw.page_number >= 0 else None
        )
        key = (identity, physical_page, raw.byte_start, raw.byte_end)
        if key in seen:
            continue
        seen.add(key)
        try:
            start_text = final_bytes[: raw.byte_start].decode("utf-8", errors="strict")
            end_text = final_bytes[: raw.byte_end].decode("utf-8", errors="strict")
            supported_text = final_bytes[raw.byte_start : raw.byte_end].decode(
                "utf-8", errors="strict"
            )
        except UnicodeDecodeError as exc:
            raise CitationProcessingError("Citation offset splits a UTF-8 character") from exc
        result.append(
            Citation(
                number=len(result) + 1,
                title=normalized_name or "Fuente documental",
                page=physical_page,
                supported_text=supported_text,
                start_index=len(start_text.encode("utf-16-le")) // 2,
                end_index=len(end_text.encode("utf-16-le")) // 2,
            )
        )
    return tuple(result)
