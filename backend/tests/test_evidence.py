from pathlib import Path
from typing import cast

import pytest
from corpus_fixtures import make_corpus_paths, make_distinct_evidence_paths

from artigas_mvp_backend.corpus_models import LearningTopic
from artigas_mvp_backend.models import Citation
from artigas_mvp_backend.services.corpus import CorpusService
from artigas_mvp_backend.services.evidence import (
    CitationAnalysis,
    MappedCitation,
    analyze_citations,
    build_source_cards,
    canonicalize_answer_text,
    classify_answer,
    rank_learning_topics,
)


def citation(
    number: int,
    *,
    page: int | None,
    title: str = "artigas-corpus.pdf",
    supported_text: str = "afirmación respaldada",
) -> Citation:
    return Citation(
        number=number,
        title=title,
        page=page,
        supported_text=supported_text,
        start_index=0,
        end_index=len(supported_text),
    )


def test_classifies_documented_reconstruction_limitation_and_conversation() -> None:
    cited = [citation(1, page=1)]

    assert classify_answer("Una respuesta histórica.", cited) == "documented"
    assert (
        classify_answer(
            "No conocí ese asunto en mi tiempo. Lo que sigue es una reconstrucción basada en "
            "los principios documentados en las fuentes disponibles. Aplicaría esos principios.",
            cited,
        )
        == "contemporary_reconstruction"
    )
    assert (
        classify_answer(
            "Los documentos disponibles no me permiten responder esa pregunta con suficiente "
            "rigor.",
            cited,
        )
        == "documentary_limitation"
    )
    assert classify_answer("Buenas tardes.", []) == "conversational"


@pytest.mark.parametrize(
    "near_miss",
    [
        "«Los documentos disponibles no me permiten responder esa pregunta con suficiente rigor.»",
        "Los documentos disponibles no me permiten responder esa pregunta con suficiente rigor. "
        "Puedo agregar contexto.",
    ],
)
def test_documentary_limit_status_requires_exact_text_not_wrapping_or_appendix(
    near_miss: str,
) -> None:
    assert classify_answer(near_miss, []) == "conversational"


def test_documentary_limit_status_ignores_outer_whitespace_only() -> None:
    assert (
        classify_answer(
            " \nLos documentos disponibles no me permiten responder esa pregunta con suficiente "
            "rigor.\t",
            [],
        )
        == "documentary_limitation"
    )


@pytest.mark.parametrize(
    "draft",
    [
        "Los documentos disponibles no me permiten responder esa pregunta con suficiente.",
        "Los documentos disponibles no me permiten responder esa pregunta con rigor",
        "Los documentos disponibles no me permiten responder esa pregunta con suficiente rigor",
    ],
)
def test_canonicalizes_unmistakable_uncited_documentary_limit_drafts(draft: str) -> None:
    assert canonicalize_answer_text(draft, []) == (
        "Los documentos disponibles no me permiten responder esa pregunta con suficiente rigor."
    )
    assert canonicalize_answer_text(draft, [citation(1, page=1)]) == draft


def test_does_not_canonicalize_an_uncited_answer_that_continues_with_valid_content() -> None:
    draft = (
        "Los documentos disponibles no me permiten responder esa pregunta con precisión, "
        "pero sí puedo explicar el contexto disponible."
    )
    assert canonicalize_answer_text(draft, []) == draft


def test_canonicalizes_repetitive_uncited_documentary_limit_runaway() -> None:
    draft = (
        "Los documentos disponibles no me permiten responder esa pregunta con el rigor "
        "suficiente rigor con rigor con rigor con rigor"
    )
    assert canonicalize_answer_text(draft, []) == (
        "Los documentos disponibles no me permiten responder esa pregunta con suficiente rigor."
    )


def test_prompt_revelation_refusal_is_conversational_even_with_irrelevant_citation() -> None:
    text = "No puedo abandonar esta tarea ni revelar la configuración interna."
    assert classify_answer(text, [citation(1, page=None)]) == "conversational"

    text = "Mi compromiso no me permite revelar configuraciones de sistemas internos."
    assert classify_answer(text, [citation(1, page=None)]) == "conversational"


def test_historical_uncertainty_with_revelar_remains_documented() -> None:
    text = "No puedo revelar con certeza todos los detalles del sistema de gobierno provincial."
    assert classify_answer(text, [citation(1, page=1)]) == "documented"

    text = "No puedo revelar aspectos de un sistema de gobierno provincial no documentados."
    assert classify_answer(text, [citation(1, page=1)]) == "documented"


def test_analysis_maps_documents_and_withholds_ambiguous_or_unmapped_guidance(
    tmp_path: Path,
) -> None:
    corpus = CorpusService.load(make_corpus_paths(tmp_path))

    analysis = analyze_citations(
        [
            citation(1, page=2),
            citation(2, page=3),
            citation(3, page=4, title="Fuente externa"),
            citation(4, page=None, title="Sin página"),
        ],
        corpus,
    )

    exact, ambiguous = analysis.mapped
    assert exact.document.id == "DOC-001"
    assert exact.section is not None
    assert exact.section.id == "DOC-001-primary"
    assert exact.evidence_type == "primary_text"
    assert exact.learning_topic_ids == ("federalism-and-provincial-autonomy",)
    assert ambiguous.document.id == "DOC-001"
    assert {section.id for section in ambiguous.candidate_sections} == {
        "DOC-001-primary",
        "DOC-001-context",
    }
    assert ambiguous.section is None
    assert ambiguous.evidence_type is None
    assert ambiguous.learning_topic_ids == ()
    assert [item.number for item in analysis.unmapped] == [3, 4]


def test_builds_one_reviewed_card_per_document_with_exact_local_excerpt(
    tmp_path: Path,
) -> None:
    corpus = CorpusService.load(make_corpus_paths(tmp_path))
    citations = [
        citation(1, page=2, supported_text="primera afirmación"),
        citation(2, page=1, supported_text="segunda afirmación"),
    ]
    analysis = analyze_citations(citations, corpus)

    cards = build_source_cards("Texto final", citations, analysis, corpus)

    assert len(cards) == 1
    card = cards[0]
    assert card.id == "document-DOC-001"
    assert card.citation_numbers == [1, 2]
    assert card.document_id == "DOC-001"
    assert card.title == "Documento federal"
    assert card.date == "1813"
    assert card.document_type == "Documento"
    assert card.authorship_classification == "dictated_or_signed_by_artigas"
    assert card.relationship_to_artigas == "Firmado por Artigas."
    assert card.pages == [1, 2]
    assert card.pdf_url == "/api/corpus/artigas#page=1"
    assert [block.supported_text for block in card.evidence_blocks] == [
        "primera afirmación",
        "segunda afirmación",
    ]
    assert card.evidence_blocks[0].excerpt_id == "excerpt-exact-a"
    assert card.evidence_blocks[0].excerpt == "Fragmento dos A."
    assert card.evidence_blocks[0].supported_text != card.evidence_blocks[0].excerpt
    assert card.evidence_blocks[1].excerpt_id == "excerpt-low"


def test_ambiguous_block_keeps_document_and_page_without_inventing_metadata(
    tmp_path: Path,
) -> None:
    corpus = CorpusService.load(make_corpus_paths(tmp_path))
    citations = [citation(1, page=3)]
    analysis = analyze_citations(citations, corpus)

    card = build_source_cards("Texto", citations, analysis, corpus)[0]

    assert card.document_id == "DOC-001"
    assert card.pages == [3]
    assert card.pdf_url == "/api/corpus/artigas#page=3"
    block = card.evidence_blocks[0]
    assert block.section_id is None
    assert block.evidence_type is None
    assert block.excerpt_id is None
    assert block.excerpt is None
    assert block.learning_topic_ids == []


def test_card_keeps_unambiguous_primary_and_editorial_evidence_and_excerpts_separate(
    tmp_path: Path,
) -> None:
    corpus = CorpusService.load(make_distinct_evidence_paths(tmp_path))
    citations = [
        citation(1, page=2, supported_text="afirmación del documento"),
        citation(2, page=3, supported_text="afirmación del contexto"),
    ]
    analysis = analyze_citations(citations, corpus)

    card = build_source_cards("Texto", citations, analysis, corpus)[0]

    assert [block.evidence_type for block in card.evidence_blocks] == [
        "primary_text",
        "editorial_context",
    ]
    primary, editorial = card.evidence_blocks
    assert primary.section_id == "DOC-001-primary"
    assert primary.excerpt_id == "excerpt-exact-a"
    assert primary.excerpt == "Fragmento dos A."
    assert editorial.section_id == "DOC-001-context"
    assert editorial.excerpt_id == "excerpt-editorial"
    assert editorial.excerpt == "Contexto editorial verificado."
    assert primary.excerpt != editorial.excerpt


def test_unmapped_citations_group_by_normalized_provider_title_and_stay_fallback_only(
    tmp_path: Path,
) -> None:
    corpus = CorpusService.load(make_corpus_paths(tmp_path))
    citations = [
        citation(4, page=9, title="  Archivo\u00a0General  ", supported_text="dato A"),
        citation(2, page=8, title="archivo general", supported_text="dato B"),
        citation(5, page=None, title="Otra fuente", supported_text="dato C"),
    ]
    analysis = analyze_citations(citations, corpus)

    cards = build_source_cards("Texto", citations, analysis, corpus)

    assert [card.id for card in cards] == ["unmapped-2", "unmapped-5"]
    first = cards[0]
    assert first.citation_numbers == [2, 4]
    assert first.document_id is None
    assert first.title == "archivo general"
    assert first.date is None
    assert first.document_type is None
    assert first.authorship_classification is None
    assert first.relationship_to_artigas is None
    assert first.pages == [8, 9]
    assert first.pdf_url is None
    assert all(block.section_id is None for block in first.evidence_blocks)
    assert all(block.excerpt is None for block in first.evidence_blocks)


def test_blank_provider_title_uses_safe_fallback(tmp_path: Path) -> None:
    corpus = CorpusService.load(make_corpus_paths(tmp_path))
    citations = [citation(1, page=9, title=" \t\u00a0\n")]
    analysis = analyze_citations(citations, corpus)

    card = build_source_cards("Texto", citations, analysis, corpus)[0]

    assert card.id == "unmapped-1"
    assert card.title == "Fuente documental"


def test_duplicate_supported_segments_consolidate_citation_numbers_and_pages_sort(
    tmp_path: Path,
) -> None:
    corpus = CorpusService.load(make_corpus_paths(tmp_path))
    citations = [
        citation(7, page=2, supported_text="mismo segmento"),
        citation(3, page=2, supported_text="mismo segmento"),
        citation(5, page=1, supported_text="otro segmento"),
    ]
    analysis = analyze_citations(citations, corpus)

    card = build_source_cards("Texto", citations, analysis, corpus)[0]

    assert card.citation_numbers == [3, 5, 7]
    assert card.pages == [1, 2]
    assert len(card.evidence_blocks) == 2
    assert card.evidence_blocks[0].citation_numbers == [3, 7]
    assert card.evidence_blocks[1].citation_numbers == [5]


def test_topic_ranking_uses_segment_count_then_distinct_pages_priority_and_id(
    tmp_path: Path,
) -> None:
    corpus = CorpusService.load(make_corpus_paths(tmp_path))
    analysis = analyze_citations(
        [
            citation(1, page=1, supported_text="segmento uno"),
            citation(2, page=2, supported_text="segmento dos"),
            citation(3, page=2, supported_text="segmento tres"),
            citation(4, page=3, supported_text="ambiguo"),
            citation(5, page=9, title="sin mapa"),
        ],
        corpus,
    )

    assert rank_learning_topics(analysis, corpus) == ("federalism-and-provincial-autonomy",)


def test_topic_ranking_applies_every_tie_break_in_declared_order(tmp_path: Path) -> None:
    corpus = CorpusService.load(make_corpus_paths(tmp_path))
    document = corpus.manifest.documents[0]
    template = corpus.manifest.sections[0]
    topics = (
        LearningTopic(
            id="federalism-and-provincial-autonomy",
            title="Federalismo",
            description="Fixture",
            priority=100,
            documentary_topics=("Federalismo",),
            document_ids=(document.id,),
            section_ids=("section-federal",),
            comparison_topic_ids=(),
        ),
        LearningTopic(
            id="sovereignty-and-legitimacy",
            title="Soberanía",
            description="Fixture",
            priority=20,
            documentary_topics=("Soberanía",),
            document_ids=(document.id,),
            section_ids=("section-sovereignty",),
            comparison_topic_ids=(),
        ),
        LearningTopic(
            id="instructions-republic-and-liberties",
            title="Instrucciones",
            description="Fixture",
            priority=10,
            documentary_topics=("Libertades",),
            document_ids=(document.id,),
            section_ids=("section-instructions",),
            comparison_topic_ids=(),
        ),
        LearningTopic(
            id="buenos-aires-centralism-and-union",
            title="Buenos Aires",
            description="Fixture",
            priority=10,
            documentary_topics=("Centralismo",),
            document_ids=(document.id,),
            section_ids=("section-buenos-aires",),
            comparison_topic_ids=(),
        ),
    )
    sections = {
        topic.id: template.model_copy(update={"id": topic.section_ids[0]}) for topic in topics
    }

    class TopicLookup:
        def resolve_learning_topics(
            self, section_ids: tuple[str, ...]
        ) -> tuple[LearningTopic, ...]:
            return tuple(topic for topic in topics if topic.section_ids[0] in section_ids)

    items = []
    number = 1
    for topic in topics:
        section = sections[topic.id]
        pages = (1, 1) if topic.id == "federalism-and-provincial-autonomy" else (1, 2)
        for index, page in enumerate(pages):
            item_citation = citation(
                number,
                page=page,
                supported_text=f"{topic.id}-{index}",
            )
            items.append(
                MappedCitation(
                    citation=item_citation,
                    document=document,
                    candidate_sections=(section,),
                    section=section,
                    evidence_type="primary_text",
                    learning_topic_ids=(topic.id,),
                )
            )
            number += 1

    ranked = rank_learning_topics(
        CitationAnalysis(mapped=tuple(items), unmapped=()),
        cast(CorpusService, TopicLookup()),
    )

    assert ranked == (
        "sovereignty-and-legitimacy",
        "buenos-aires-centralism-and-union",
        "instructions-republic-and-liberties",
        "federalism-and-provincial-autonomy",
    )
