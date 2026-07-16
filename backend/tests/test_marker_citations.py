from __future__ import annotations

from langchain_core.documents import Document

from artigas_mvp_backend.services.citations import CitationMarkerParser


def sources() -> dict[str, Document]:
    return {
        "S1": Document(
            page_content="evidence one",
            metadata={"title": "Instrucciones del Año XIII", "page": 26},
        ),
        "S2": Document(
            page_content="evidence two",
            metadata={"title": "Reglamento de Tierras", "page": 54},
        ),
    }


def test_parser_buffers_split_markers_and_never_emits_marker_syntax() -> None:
    parser = CitationMarkerParser(sources())

    deltas = [parser.feed(part) for part in ("Defendí la soberanía [[", "S1", "]] y la tierra.")]
    final_text, citations, trailing = parser.finish()

    assert "".join(deltas) + trailing == "Defendí la soberanía  y la tierra."
    assert final_text == "Defendí la soberanía  y la tierra."
    assert "[[" not in "".join(deltas)
    assert citations[0].title == "Instrucciones del Año XIII"
    assert citations[0].page == 26
    assert citations[0].supported_text == "Defendí la soberanía"


def test_parser_handles_multiple_repeated_and_invalid_markers_with_utf16_offsets() -> None:
    parser = CitationMarkerParser(sources())
    parser.feed("🇺🇾 Soberanía popular [[S1]][[S2]] y federalismo [[S1]]. Desconocida [[S9]].")
    final_text, citations, _ = parser.finish()

    assert "[[" not in final_text
    assert [citation.title for citation in citations] == [
        "Instrucciones del Año XIII",
        "Reglamento de Tierras",
        "Instrucciones del Año XIII",
    ]
    assert citations[0].start_index == 0
    assert citations[0].end_index == len("🇺🇾 Soberanía popular".encode("utf-16-le")) // 2


def test_parser_removes_malformed_and_unfinished_markers() -> None:
    parser = CitationMarkerParser(sources())
    parser.feed("Texto [[fuente]] y otro [[S")

    final_text, citations, _ = parser.finish()

    assert final_text == "Texto  y otro "
    assert citations == ()
