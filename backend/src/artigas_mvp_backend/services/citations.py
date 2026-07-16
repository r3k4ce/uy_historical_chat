from __future__ import annotations

import re

from langchain_core.documents import Document

from artigas_mvp_backend.models import Citation


class CitationProcessingError(Exception):
    """Raised when generated citation data cannot be safely normalized."""


_MARKER = re.compile(r"^\[\[S([1-9]\d*)\]\]")


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _claim_span(text: str) -> tuple[int, int]:
    end = len(text.rstrip())
    boundary = max((text.rfind(character, 0, end) for character in ".?!\n"), default=-1)
    start = boundary + 1
    while start < end and text[start].isspace():
        start += 1
    return start, end


class CitationMarkerParser:
    """Strip model citation markers while producing deterministic citation spans."""

    def __init__(self, sources: dict[str, Document]) -> None:
        self.sources = sources
        self._pending = ""
        self._text = ""
        self._citations: list[Citation] = []

    def feed(self, delta: str) -> str:
        self._pending += delta
        emitted: list[str] = []
        while self._pending:
            marker = _MARKER.match(self._pending)
            if marker:
                self._add_citation(f"S{marker.group(1)}")
                self._pending = self._pending[marker.end() :]
                continue
            if self._pending.startswith("[["):
                closing = self._pending.find("]]", 2)
                if closing < 0:
                    break
                self._pending = self._pending[closing + 2 :]
                continue
            if self._pending == "[":
                break
            character = self._pending[0]
            self._pending = self._pending[1:]
            self._text += character
            emitted.append(character)
        return "".join(emitted)

    def _add_citation(self, alias: str) -> None:
        source = self.sources.get(alias)
        if source is None:
            return
        start, end = _claim_span(self._text)
        if start == end:
            return
        title = str(source.metadata.get("title") or "Fuente documental")
        page_value = source.metadata.get("page")
        page = page_value if isinstance(page_value, int) else None
        self._citations.append(
            Citation(
                number=len(self._citations) + 1,
                title=title,
                page=page,
                supported_text=self._text[start:end],
                start_index=_utf16_length(self._text[:start]),
                end_index=_utf16_length(self._text[:end]),
            )
        )

    def finish(self) -> tuple[str, tuple[Citation, ...], str]:
        trailing = ""
        if self._pending and not self._pending.startswith("[["):
            trailing = self._pending
            self._text += trailing
        self._pending = ""
        return self._text, tuple(self._citations), trailing
