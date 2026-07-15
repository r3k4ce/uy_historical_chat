from types import SimpleNamespace

import pytest

from artigas_mvp_backend.services.citations import (
    CitationProcessingError,
    RawFileCitation,
    normalize_citations,
)


def raw(
    start: int,
    end: int,
    *,
    source: str | None = "file-1",
    name: str | None = " corpus.pdf ",
    page: int | None = 3,
) -> RawFileCitation:
    return RawFileCitation(source, name, page, start, end)


def test_normalizes_order_deduplication_and_distinct_segments() -> None:
    text = "uno dos tres"
    citations = normalize_citations(
        text,
        [raw(8, 12), raw(0, 3), raw(0, 3), raw(4, 7)],
    )
    assert [(item.number, item.supported_text) for item in citations] == [
        (1, "uno"),
        (2, "dos"),
        (3, "tres"),
    ]


def test_preserves_nullable_page_and_uses_fallback_title() -> None:
    citation = normalize_citations("texto", [raw(0, 5, source=None, name=" ", page=None)])[0]
    assert citation.page is None
    assert citation.title == "Fuente documental"


def test_converts_utf8_offsets_to_javascript_utf16_offsets() -> None:
    text = "á😀 nación"
    encoded = text.encode("utf-8")
    start = encoded.index("nación".encode())
    end = start + len("nación".encode())
    citation = normalize_citations(text, [raw(start, end)])[0]
    assert citation.supported_text == "nación"
    assert (citation.start_index, citation.end_index) == (4, 10)


@pytest.mark.parametrize(("start", "end"), [(-1, 1), (0, 50), (3, 2)])
def test_rejects_out_of_range_offsets(start: int, end: int) -> None:
    with pytest.raises(CitationProcessingError):
        normalize_citations("abc", [raw(start, end)])


def test_rejects_offset_that_splits_utf8_character() -> None:
    with pytest.raises(CitationProcessingError):
        normalize_citations("á", [raw(1, 2)])


def test_extracts_file_citation_annotations_and_ignores_other_types() -> None:
    annotation = SimpleNamespace(
        type="file_citation",
        source_id="opaque",
        file_name="fuente.pdf",
        page_number=7,
        start_index=0,
        end_index=5,
    )
    ignored = SimpleNamespace(type="url_citation", start_index=0, end_index=5)
    citations = normalize_citations("texto", [ignored, annotation])
    assert len(citations) == 1
    assert citations[0].page == 8


@pytest.mark.parametrize(
    ("provider_page", "physical_page"),
    [(0, 1), (25, 26), (53, 54), (-1, None), (None, None)],
)
def test_normalizes_provider_pages_to_physical_pages(
    provider_page: int | None, physical_page: int | None
) -> None:
    citation = normalize_citations("texto", [raw(0, 5, page=provider_page)])[0]

    assert citation.page == physical_page


def test_empty_annotations_are_valid() -> None:
    assert normalize_citations("respuesta", []) == ()
