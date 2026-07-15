from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from artigas_mvp_backend.corpus_models import (
    LearningTopicId,
    ManifestDocument,
    ManifestSection,
    SectionType,
)
from artigas_mvp_backend.models import AnswerStatus, Citation, EvidenceBlock, SourceCard
from artigas_mvp_backend.prompts import DOCUMENTARY_LIMIT_RESPONSE, RECONSTRUCTION_OPENING
from artigas_mvp_backend.services.corpus import CorpusService


@dataclass(frozen=True)
class MappedCitation:
    citation: Citation
    document: ManifestDocument
    candidate_sections: tuple[ManifestSection, ...]
    section: ManifestSection | None
    evidence_type: SectionType | None
    learning_topic_ids: tuple[LearningTopicId, ...]


@dataclass(frozen=True)
class CitationAnalysis:
    mapped: tuple[MappedCitation, ...]
    unmapped: tuple[Citation, ...]


def canonicalize_answer_text(final_text: str, citations: Sequence[Citation]) -> str:
    """Repair only an unmistakable uncited draft of the reviewed limit response."""
    stripped = final_text.strip()
    normalized = " ".join(stripped.casefold().split())
    malformed_limits = {
        "los documentos disponibles no me permiten responder esa pregunta con suficiente.",
        "los documentos disponibles no me permiten responder esa pregunta con rigor",
        "los documentos disponibles no me permiten responder esa pregunta con suficiente rigor",
    }
    if not citations and normalized in malformed_limits:
        return DOCUMENTARY_LIMIT_RESPONSE
    if (
        not citations
        and normalized.startswith(
            "los documentos disponibles no me permiten responder esa pregunta con"
        )
        and normalized.count("con rigor") >= 3
    ):
        return DOCUMENTARY_LIMIT_RESPONSE
    return final_text


def classify_answer(final_text: str, citations: Sequence[Citation]) -> AnswerStatus:
    stripped = final_text.strip()
    if stripped == DOCUMENTARY_LIMIT_RESPONSE:
        return "documentary_limitation"
    normalized = stripped.strip("«»").strip()
    if normalized.startswith(RECONSTRUCTION_OPENING):
        return "contemporary_reconstruction"
    casefolded = " ".join(normalized.casefold().split())
    rejects_internal_disclosure = any(
        target in casefolded
        for target in (
            "configuración interna",
            "prompt interno",
            "mensaje del sistema",
            "reglas internas",
            "aspectos de un sistema que está fuera de mi época",
            "configuraciones de sistemas",
        )
    )
    if (
        rejects_internal_disclosure
        and "revelar" in casefolded
        and any(
            refusal in casefolded
            for refusal in (
                "no puedo",
                "no me permite",
                "no tengo la facultad",
                "no revelaré",
                "me niego",
            )
        )
    ):
        return "conversational"
    if citations:
        return "documented"
    return "conversational"


def analyze_citations(citations: Sequence[Citation], corpus: CorpusService) -> CitationAnalysis:
    mapped: list[MappedCitation] = []
    unmapped: list[Citation] = []
    for citation in citations:
        page = citation.page
        if page is None:
            unmapped.append(citation)
            continue
        document = corpus.resolve_document(page)
        if document is None:
            unmapped.append(citation)
            continue

        candidates = tuple(
            section
            for section in corpus.resolve_sections(page)
            if section.document_id == document.id
        )
        section, evidence_type, topic_ids = _resolve_reliable_mapping(candidates, corpus)
        mapped.append(
            MappedCitation(
                citation=citation,
                document=document,
                candidate_sections=candidates,
                section=section,
                evidence_type=evidence_type,
                learning_topic_ids=topic_ids,
            )
        )
    return CitationAnalysis(mapped=tuple(mapped), unmapped=tuple(unmapped))


def _resolve_reliable_mapping(
    candidates: tuple[ManifestSection, ...], corpus: CorpusService
) -> tuple[ManifestSection | None, SectionType | None, tuple[LearningTopicId, ...]]:
    if not candidates:
        return None, None, ()
    evidence_types = {section.section_type for section in candidates}
    topic_sets = [
        {topic.id for topic in corpus.resolve_learning_topics((section.id,))}
        for section in candidates
    ]
    if len(evidence_types) != 1 or any(topics != topic_sets[0] for topics in topic_sets[1:]):
        return None, None, ()
    section = candidates[0]
    topics = tuple(
        cast(LearningTopicId, topic.id)
        for topic in corpus.resolve_learning_topics((section.id,))
        if topic.id in topic_sets[0]
    )
    return section, section.section_type, cast(tuple[LearningTopicId, ...], topics)


def rank_learning_topics(
    analysis: CitationAnalysis, corpus: CorpusService
) -> tuple[LearningTopicId, ...]:
    segments: dict[LearningTopicId, set[tuple[str, str, int | None, str]]] = defaultdict(set)
    pages: dict[LearningTopicId, set[int]] = defaultdict(set)
    topic_metadata = {}
    for item in analysis.mapped:
        if item.section is None:
            continue
        for topic_id in item.learning_topic_ids:
            segments[topic_id].add(
                (
                    item.document.id,
                    item.section.id,
                    item.citation.page,
                    item.citation.supported_text,
                )
            )
            if item.citation.page is not None:
                pages[topic_id].add(item.citation.page)
            for topic in corpus.resolve_learning_topics((item.section.id,)):
                if topic.id == topic_id:
                    topic_metadata[topic_id] = topic
                    break
    return tuple(
        sorted(
            segments,
            key=lambda topic_id: (
                -len(segments[topic_id]),
                -len(pages[topic_id]),
                -topic_metadata[topic_id].priority,
                topic_id,
            ),
        )
    )


def select_strongest_citation(
    analysis: CitationAnalysis,
    primary_topic_id: LearningTopicId,
) -> MappedCitation | None:
    eligible = (
        item
        for item in analysis.mapped
        if item.section is not None
        and item.evidence_type is not None
        and item.citation.page is not None
        and primary_topic_id in item.learning_topic_ids
    )
    return min(
        eligible,
        key=lambda item: (
            -item.section.priority if item.section is not None else 0,
            -item.document.priority,
            item.citation.page if item.citation.page is not None else 0,
            item.citation.number,
        ),
        default=None,
    )


def build_source_cards(
    final_text: str,
    citations: Sequence[Citation],
    analysis: CitationAnalysis,
    corpus: CorpusService,
) -> tuple[SourceCard, ...]:
    del final_text, citations
    ranked_topics = rank_learning_topics(analysis, corpus)
    primary_topic = ranked_topics[0] if ranked_topics else None

    mapped_groups: dict[str, list[MappedCitation]] = defaultdict(list)
    for item in analysis.mapped:
        mapped_groups[item.document.id].append(item)

    cards: list[SourceCard] = []
    for document_id, items in mapped_groups.items():
        document = items[0].document
        blocks = _build_mapped_blocks(items, primary_topic, corpus)
        citation_numbers = sorted({item.citation.number for item in items})
        pages = sorted({item.citation.page for item in items if item.citation.page is not None})
        cards.append(
            SourceCard(
                id=f"document-{document_id}",
                citation_numbers=citation_numbers,
                document_id=document_id,
                title=document.display_title,
                date=document.date,
                document_type=document.document_type,
                authorship_classification=document.authorship_classification,
                relationship_to_artigas=document.relationship_to_artigas,
                pages=pages,
                pdf_url=corpus.pdf_url(pages[0]) if pages else None,
                evidence_blocks=blocks,
            )
        )

    unmapped_groups: dict[str, list[Citation]] = defaultdict(list)
    display_titles: dict[str, str] = {}
    for citation in analysis.unmapped:
        key = _normalize_title(citation.title)
        unmapped_groups[key].append(citation)
        current = display_titles.get(key)
        title = _display_title(citation.title)
        if current is None or citation.number < min(
            item.number for item in unmapped_groups[key] if _display_title(item.title) == current
        ):
            display_titles[key] = title
    for key, items in unmapped_groups.items():
        numbers = sorted({item.number for item in items})
        pages = sorted({item.page for item in items if item.page is not None})
        cards.append(
            SourceCard(
                id=f"unmapped-{numbers[0]}",
                citation_numbers=numbers,
                document_id=None,
                title=display_titles[key],
                date=None,
                document_type=None,
                authorship_classification=None,
                relationship_to_artigas=None,
                pages=pages,
                pdf_url=None,
                evidence_blocks=_build_unmapped_blocks(items),
            )
        )

    return tuple(sorted(cards, key=lambda card: min(card.citation_numbers)))


def _build_mapped_blocks(
    items: Sequence[MappedCitation],
    primary_topic: LearningTopicId | None,
    corpus: CorpusService,
) -> list[EvidenceBlock]:
    grouped: dict[tuple[str | None, SectionType | None, int | None, str], list[MappedCitation]] = {}
    for item in items:
        key = (
            item.section.id if item.section is not None else None,
            item.evidence_type,
            item.citation.page,
            item.citation.supported_text,
        )
        grouped.setdefault(key, []).append(item)

    blocks: list[EvidenceBlock] = []
    for group in grouped.values():
        item = group[0]
        excerpt = None
        if (
            primary_topic is not None
            and primary_topic in item.learning_topic_ids
            and item.section is not None
            and item.evidence_type is not None
            and item.citation.page is not None
        ):
            excerpt = corpus.select_verified_excerpt(
                item.section.id,
                primary_topic,
                item.evidence_type,
                item.citation.page,
            )
        numbers = sorted({entry.citation.number for entry in group})
        blocks.append(
            EvidenceBlock(
                id=f"evidence-{numbers[0]}",
                citation_numbers=numbers,
                section_id=item.section.id if item.section is not None else None,
                evidence_type=item.evidence_type,
                page=item.citation.page,
                excerpt_id=excerpt.id if excerpt is not None else None,
                excerpt=excerpt.text if excerpt is not None else None,
                supported_text=item.citation.supported_text,
                learning_topic_ids=list(item.learning_topic_ids),
            )
        )
    return blocks


def _build_unmapped_blocks(items: Sequence[Citation]) -> list[EvidenceBlock]:
    grouped: dict[tuple[int | None, str], list[Citation]] = {}
    for citation in items:
        grouped.setdefault((citation.page, citation.supported_text), []).append(citation)
    blocks = []
    for group in grouped.values():
        numbers = sorted({item.number for item in group})
        blocks.append(
            EvidenceBlock(
                id=f"evidence-{numbers[0]}",
                citation_numbers=numbers,
                section_id=None,
                evidence_type=None,
                page=group[0].page,
                excerpt_id=None,
                excerpt=None,
                supported_text=group[0].supported_text,
                learning_topic_ids=[],
            )
        )
    return blocks


def _normalize_title(title: str) -> str:
    return _display_title(title).casefold()


def _display_title(title: str) -> str:
    normalized = unicodedata.normalize("NFC", title).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", normalized).strip() or "Fuente documental"
