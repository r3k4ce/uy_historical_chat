from __future__ import annotations

import logging

from artigas_mvp_backend.corpus_models import LearningAction, LearningTopicId, TopicDepth
from artigas_mvp_backend.models import AnswerStatus, EducationalAction, LearningState
from artigas_mvp_backend.services.corpus import CorpusService
from artigas_mvp_backend.services.evidence import (
    CitationAnalysis,
    rank_learning_topics,
    select_strongest_citation,
)

logger = logging.getLogger("artigas_mvp.education")

_DEPTH_RANK: dict[TopicDepth, int] = {
    "introductory": 0,
    "deeper": 1,
    "comparative": 2,
}
_NEXT_DEPTH: dict[TopicDepth, TopicDepth] = {
    "introductory": "deeper",
    "deeper": "comparative",
    "comparative": "comparative",
}


def normalize_learning_state(state: LearningState, corpus: CorpusService) -> LearningState:
    def valid_ids(action_ids: list[str]) -> list[str]:
        return sorted(
            {action_id for action_id in action_ids if corpus.validate_action_id(action_id)}
        )

    shown_action_ids = valid_ids(state.shown_action_ids)
    selected_action_ids = valid_ids(state.selected_action_ids)
    submitted_action = (
        corpus.validate_action_id(state.submitted_action_id)
        if state.submitted_action_id is not None
        else None
    )
    known_topic_ids: set[LearningTopicId] = {topic.id for topic in corpus.learning_map.topics}
    topic_depths: dict[LearningTopicId, TopicDepth] = {
        topic_id: state.topic_depths[topic_id]
        for topic_id in sorted(state.topic_depths)
        if topic_id in known_topic_ids
    }
    discarded_count = (
        len(state.shown_action_ids)
        - len(shown_action_ids)
        + len(state.selected_action_ids)
        - len(selected_action_ids)
        + int(state.submitted_action_id is not None and submitted_action is None)
        + len(state.topic_depths)
        - len(topic_depths)
    )
    logger.info(
        "learning_state_normalized shown=%d selected=%d discarded=%d submitted_valid=%s",
        len(shown_action_ids),
        len(selected_action_ids),
        discarded_count,
        submitted_action is not None,
    )
    return LearningState(
        shown_action_ids=shown_action_ids,
        selected_action_ids=selected_action_ids,
        submitted_action_id=submitted_action.id if submitted_action is not None else None,
        topic_depths=topic_depths,
    )


def advance_learning_state(state: LearningState, corpus: CorpusService) -> LearningState:
    normalized = normalize_learning_state(state, corpus)
    if normalized.submitted_action_id is None:
        return normalized

    action = corpus.validate_action_id(normalized.submitted_action_id)
    if action is None:
        return normalized.model_copy(update={"submitted_action_id": None})

    selected_action_ids = sorted({*normalized.selected_action_ids, action.id})
    topic_depths = dict(normalized.topic_depths)
    next_depth = _NEXT_DEPTH[action.depth]
    current_depth = topic_depths.get(action.topic_id, "introductory")
    if _DEPTH_RANK[next_depth] > _DEPTH_RANK[current_depth]:
        topic_depths[action.topic_id] = next_depth

    logger.info(
        "learning_action_advanced action_id=%s selected=%d topic_depth=%s",
        action.id,
        len(selected_action_ids),
        topic_depths.get(action.topic_id, current_depth),
    )
    return LearningState(
        shown_action_ids=normalized.shown_action_ids,
        selected_action_ids=selected_action_ids,
        submitted_action_id=None,
        topic_depths={topic_id: topic_depths[topic_id] for topic_id in sorted(topic_depths)},
    )


def select_educational_actions(
    *,
    answer_status: AnswerStatus,
    analysis: CitationAnalysis,
    state: LearningState,
    corpus: CorpusService,
) -> tuple[EducationalAction, ...]:
    if answer_status in {"conversational", "documentary_limitation"}:
        return ()

    ranked_topics = rank_learning_topics(analysis, corpus)
    if not ranked_topics:
        return ()
    primary_topic_id = ranked_topics[0]
    excluded_ids = {*state.shown_action_ids, *state.selected_action_ids}
    reviewed_actions = tuple(
        action
        for action in corpus.learning_map.actions
        if corpus.validate_action_id(action.id) is not None
    )

    selected: list[EducationalAction] = []
    deepen = _select_deepen_action(
        reviewed_actions,
        primary_topic_id,
        state.topic_depths.get(primary_topic_id, "introductory"),
        excluded_ids,
    )
    if deepen is not None:
        selected.append(_question_action(deepen))
        excluded_ids.add(deepen.id)

    secondary_topic_id = ranked_topics[1] if len(ranked_topics) > 1 else None
    comparison = _select_comparison_action(
        reviewed_actions,
        primary_topic_id,
        secondary_topic_id,
        excluded_ids,
    )
    if comparison is not None:
        selected.append(_question_action(comparison))

    strongest = select_strongest_citation(analysis, primary_topic_id)
    if strongest is not None and strongest.citation.page is not None:
        selected.append(
            EducationalAction(
                type="source",
                label="Examinar la fuente",
                url=corpus.pdf_url(strongest.citation.page),
            )
        )

    shown_ids = {
        *state.shown_action_ids,
        *(action.action_id for action in selected if action.action_id is not None),
    }
    state.shown_action_ids = sorted(shown_ids)
    return tuple(selected)


def _select_deepen_action(
    actions: tuple[LearningAction, ...],
    topic_id: LearningTopicId,
    depth: TopicDepth,
    excluded_ids: set[str],
) -> LearningAction | None:
    return min(
        (
            action
            for action in actions
            if action.topic_id == topic_id
            and action.depth == depth
            and action.type == "deepen"
            and action.id not in excluded_ids
        ),
        key=lambda action: (-action.priority, action.id),
        default=None,
    )


def _select_comparison_action(
    actions: tuple[LearningAction, ...],
    topic_id: LearningTopicId,
    secondary_topic_id: LearningTopicId | None,
    excluded_ids: set[str],
) -> LearningAction | None:
    candidates = tuple(
        action
        for action in actions
        if action.topic_id == topic_id
        and action.depth == "comparative"
        and action.type == "compare"
        and action.id not in excluded_ids
    )
    return min(
        candidates,
        key=lambda action: (
            action.comparison_topic_id != secondary_topic_id
            if secondary_topic_id is not None
            else False,
            -action.priority,
            action.id,
        ),
        default=None,
    )


def _question_action(action: LearningAction) -> EducationalAction:
    action_type = "compare" if action.type == "compare" else "deepen"
    return EducationalAction(
        type=action_type,
        label="Contrastar" if action_type == "compare" else "Profundizar",
        action_id=action.id,
        question=action.question,
    )
