from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from artigas_mvp_backend.corpus_models import (
    LearningAction,
    ManifestDocument,
    ManifestSection,
)
from artigas_mvp_backend.models import ChatRequest, Citation, LearningState
from artigas_mvp_backend.services.education import (
    advance_learning_state,
    normalize_learning_state,
    select_educational_actions,
)
from artigas_mvp_backend.services.evidence import CitationAnalysis, MappedCitation

FEDERALISM = "federalism-and-provincial-autonomy"
SOVEREIGNTY = "sovereignty-and-legitimacy"


def _action(
    action_id: str,
    *,
    topic_id: str = FEDERALISM,
    depth: str,
    review_status: str = "reviewed",
    active: bool = True,
    priority: int = 10,
    comparison_topic_id: str | None = None,
) -> LearningAction:
    comparative = depth == "comparative"
    return LearningAction.model_validate(
        {
            "id": action_id,
            "topic_id": topic_id,
            "depth": depth,
            "type": "compare" if comparative else "deepen",
            "label": "Contrastar" if comparative else "Profundizar",
            "question": f"¿Pregunta revisada {action_id}?",
            "document_ids": ("ART-001",),
            "section_ids": ("ART-001-primary",),
            "concepts": ("federalismo",),
            "comparison_topic_id": (comparison_topic_id or SOVEREIGNTY if comparative else None),
            "priority": priority,
            "review_status": review_status,
            "active": active,
        }
    )


class StubCorpus:
    def __init__(self) -> None:
        actions = (
            _action("intro", depth="introductory"),
            _action("intro-priority", depth="introductory", priority=20),
            _action("deeper", depth="deeper"),
            _action(
                "compare",
                depth="comparative",
                comparison_topic_id=FEDERALISM,
            ),
            _action(
                "compare-secondary",
                depth="comparative",
                priority=5,
                comparison_topic_id=SOVEREIGNTY,
            ),
            _action("sovereignty-intro", topic_id=SOVEREIGNTY, depth="introductory"),
            _action("inactive", depth="introductory", active=False),
            _action("draft", depth="introductory", review_status="draft"),
        )
        self._actions = {action.id: action for action in actions}
        self.learning_map = SimpleNamespace(
            topics=(
                SimpleNamespace(id=FEDERALISM, priority=20),
                SimpleNamespace(id=SOVEREIGNTY, priority=10),
            ),
            actions=actions,
        )

    def validate_action_id(self, action_id: str) -> LearningAction | None:
        action = self._actions.get(action_id)
        if action is None or not action.active or action.review_status != "reviewed":
            return None
        return action

    def resolve_learning_topics(self, section_ids):
        if "federal-section" not in section_ids:
            return ()
        return tuple(self.learning_map.topics)

    def pdf_url(self, page: int) -> str:
        return f"/api/corpus/artigas#page={page}"


def _document(*, priority: int = 30) -> ManifestDocument:
    return ManifestDocument.model_validate(
        {
            "id": "ART-001",
            "title": "Documento",
            "display_title": "Documento",
            "date": "1813",
            "date_precision": "year",
            "place": "Banda Oriental",
            "document_type": "Oficio",
            "historical_period": "Revolución",
            "issuing_authority": "José Artigas",
            "recipient": None,
            "authorship_classification": "dictated_or_signed_by_artigas",
            "relationship_to_artigas": "Firmado por Artigas.",
            "provenance_summary": "Copia.",
            "textual_confidence": "high",
            "page_start": 1,
            "page_end": 4,
            "documentary_topics": ("Federalismo",),
            "learning_topics": (FEDERALISM,),
            "priority": priority,
            "review_status": "reviewed",
            "section_ids": ("federal-section",),
        }
    )


def _section(*, priority: int = 40) -> ManifestSection:
    return ManifestSection.model_validate(
        {
            "id": "federal-section",
            "document_id": "ART-001",
            "corpus_parent": None,
            "page_start": 1,
            "page_end": 4,
            "section_type": "primary_text",
            "documentary_topics": ("Federalismo",),
            "learning_topics": (FEDERALISM, SOVEREIGNTY),
            "priority": priority,
            "review_status": "reviewed",
        }
    )


def _mapped(
    number: int,
    page: int,
    *,
    topics: tuple[str, ...] = (FEDERALISM,),
    section_priority: int = 40,
    document_priority: int = 30,
) -> MappedCitation:
    citation = Citation(
        number=number,
        title="corpus.pdf",
        page=page,
        supported_text=f"segmento {number}",
        start_index=0,
        end_index=9,
    )
    section = _section(priority=section_priority)
    return MappedCitation(
        citation=citation,
        document=_document(priority=document_priority),
        candidate_sections=(section,),
        section=section,
        evidence_type="primary_text",
        learning_topic_ids=topics,  # type: ignore[arg-type]
    )


def test_learning_state_defaults_are_isolated_and_chat_requests_accept_omission() -> None:
    first = LearningState()
    second = LearningState()

    first.shown_action_ids.append("intro")
    first.topic_depths[FEDERALISM] = "deeper"

    assert second == LearningState()
    assert ChatRequest(message="Pregunta", turn_number=1).learning_state == LearningState()


def test_learning_state_discards_unknown_topic_ids_before_validation() -> None:
    state = LearningState.model_validate(
        {"topic_depths": {FEDERALISM: "deeper", "stale-topic": "comparative"}}
    )

    assert state.topic_depths == {FEDERALISM: "deeper"}


def test_normalize_discards_unknown_actions_deduplicates_and_sorts(caplog) -> None:
    corpus = StubCorpus()
    state = LearningState(
        shown_action_ids=["stale", "deeper", "intro", "deeper"],
        selected_action_ids=["compare", "unknown", "intro", "compare"],
        submitted_action_id="unknown-submission",
        topic_depths={SOVEREIGNTY: "introductory", FEDERALISM: "deeper"},
    )

    with caplog.at_level(logging.INFO, logger="artigas_mvp.education"):
        normalized = normalize_learning_state(state, corpus)  # type: ignore[arg-type]

    assert normalized == LearningState(
        shown_action_ids=["deeper", "intro"],
        selected_action_ids=["compare", "intro"],
        topic_depths={FEDERALISM: "deeper", SOVEREIGNTY: "introductory"},
    )
    assert "stale" not in caplog.text
    assert "unknown" not in caplog.text
    assert "Pregunta revisada" not in caplog.text


def test_normalize_discards_inactive_or_draft_actions() -> None:
    corpus = StubCorpus()
    state = LearningState(
        shown_action_ids=["inactive", "draft", "intro"],
        selected_action_ids=["draft"],
        submitted_action_id="inactive",
    )

    normalized = normalize_learning_state(state, corpus)  # type: ignore[arg-type]

    assert normalized.shown_action_ids == ["intro"]
    assert normalized.selected_action_ids == []
    assert normalized.submitted_action_id is None


def test_introductory_submission_advances_only_its_topic() -> None:
    state = LearningState(
        submitted_action_id="intro",
        topic_depths={SOVEREIGNTY: "comparative"},
    )

    advanced = advance_learning_state(state, StubCorpus())  # type: ignore[arg-type]

    assert advanced.selected_action_ids == ["intro"]
    assert advanced.submitted_action_id is None
    assert advanced.topic_depths == {
        FEDERALISM: "deeper",
        SOVEREIGNTY: "comparative",
    }


def test_deeper_submission_advances_to_comparative() -> None:
    advanced = advance_learning_state(
        LearningState(submitted_action_id="deeper"),
        StubCorpus(),  # type: ignore[arg-type]
    )

    assert advanced.topic_depths == {FEDERALISM: "comparative"}


def test_comparative_submission_directly_sets_comparative_depth() -> None:
    advanced = advance_learning_state(
        LearningState(submitted_action_id="compare"),
        StubCorpus(),  # type: ignore[arg-type]
    )

    assert advanced.topic_depths == {FEDERALISM: "comparative"}


def test_submission_never_regresses_existing_comparative_depth() -> None:
    advanced = advance_learning_state(
        LearningState(submitted_action_id="intro", topic_depths={FEDERALISM: "comparative"}),
        StubCorpus(),  # type: ignore[arg-type]
    )

    assert advanced.topic_depths == {FEDERALISM: "comparative"}


def test_absent_or_invalid_submission_does_not_advance() -> None:
    corpus = StubCorpus()
    original = LearningState(selected_action_ids=["intro"], topic_depths={FEDERALISM: "deeper"})

    free_form = advance_learning_state(original, corpus)  # type: ignore[arg-type]
    stale = advance_learning_state(
        original.model_copy(update={"submitted_action_id": "stale"}),
        corpus,  # type: ignore[arg-type]
    )

    assert free_form == original
    assert stale == original


def test_selection_returns_fixed_slots_in_order_and_marks_questions_shown() -> None:
    state = LearningState()
    analysis = CitationAnalysis(
        mapped=(
            _mapped(1, 3, topics=(FEDERALISM, SOVEREIGNTY)),
            _mapped(2, 2, topics=(FEDERALISM,)),
        ),
        unmapped=(),
    )

    actions = select_educational_actions(
        answer_status="documented",
        analysis=analysis,
        state=state,
        corpus=StubCorpus(),  # type: ignore[arg-type]
    )

    assert [(action.type, action.label) for action in actions] == [
        ("deepen", "Profundizar"),
        ("compare", "Contrastar"),
        ("source", "Examinar la fuente"),
    ]
    assert actions[0].action_id == "intro-priority"
    assert actions[1].action_id == "compare-secondary"
    assert actions[2].url == "/api/corpus/artigas#page=2"
    assert actions[2].action_id is None
    assert state.shown_action_ids == ["compare-secondary", "intro-priority"]


def test_selection_uses_current_depth_and_excludes_shown_or_selected_ids() -> None:
    state = LearningState(
        shown_action_ids=["intro-priority"],
        selected_action_ids=["compare-secondary"],
        topic_depths={FEDERALISM: "deeper"},
    )

    actions = select_educational_actions(
        answer_status="documented",
        analysis=CitationAnalysis(mapped=(_mapped(1, 2),), unmapped=()),
        state=state,
        corpus=StubCorpus(),  # type: ignore[arg-type]
    )

    assert [action.action_id for action in actions] == ["deeper", "compare", None]
    assert state.shown_action_ids == ["compare", "deeper", "intro-priority"]


@pytest.mark.parametrize("status", ["conversational", "documentary_limitation"])
def test_selection_omits_actions_for_non_evidentiary_answers(status: str) -> None:
    state = LearningState()

    actions = select_educational_actions(
        answer_status=status,  # type: ignore[arg-type]
        analysis=CitationAnalysis(mapped=(_mapped(1, 2),), unmapped=()),
        state=state,
        corpus=StubCorpus(),  # type: ignore[arg-type]
    )

    assert actions == ()
    assert state == LearningState()


def test_selection_requires_reliable_mapped_evidence_even_for_reconstruction() -> None:
    ambiguous = _mapped(1, 2)
    ambiguous = MappedCitation(
        citation=ambiguous.citation,
        document=ambiguous.document,
        candidate_sections=ambiguous.candidate_sections,
        section=None,
        evidence_type=None,
        learning_topic_ids=(),
    )

    for analysis in (
        CitationAnalysis(mapped=(), unmapped=(ambiguous.citation,)),
        CitationAnalysis(mapped=(ambiguous,), unmapped=()),
    ):
        assert (
            select_educational_actions(
                answer_status="contemporary_reconstruction",
                analysis=analysis,
                state=LearningState(),
                corpus=StubCorpus(),  # type: ignore[arg-type]
            )
            == ()
        )


def test_source_ranking_prefers_topic_then_section_document_page_and_number() -> None:
    analysis = CitationAnalysis(
        mapped=(
            _mapped(1, 1, topics=(SOVEREIGNTY,), section_priority=100),
            _mapped(4, 4, section_priority=50, document_priority=10),
            _mapped(3, 3, section_priority=50, document_priority=20),
            _mapped(2, 2, section_priority=50, document_priority=20),
        ),
        unmapped=(),
    )

    actions = select_educational_actions(
        answer_status="documented",
        analysis=analysis,
        state=LearningState(),
        corpus=StubCorpus(),  # type: ignore[arg-type]
    )

    assert actions[-1].type == "source"
    assert actions[-1].url == "/api/corpus/artigas#page=2"
