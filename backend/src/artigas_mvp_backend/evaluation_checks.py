"""Deterministic, deliberately narrow checks for Artigas evaluation turns."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict

from artigas_mvp_backend.corpus_models import LearningTopicId, TopicDepth
from artigas_mvp_backend.evaluation_models import TurnExpectation, category_notes_are_valid
from artigas_mvp_backend.models import CompleteEventData, LearningState
from artigas_mvp_backend.prompts import (
    ARTIGAS_PROFILE,
    DOCUMENTARY_LIMIT_RESPONSE,
    RECONSTRUCTION_OPENING,
)
from artigas_mvp_backend.services.evidence import (
    analyze_citations,
    rank_learning_topics,
    select_strongest_citation,
)

CheckGroup = Literal[
    "citation_integrity",
    "verified_excerpt",
    "corpus_boundary",
    "prompt_safety",
    "content_contract",
    "education_contract",
    "performance_observation",
]

_ALWAYS_CRITICAL_GROUPS: frozenset[CheckGroup] = frozenset(
    {
        "citation_integrity",
        "verified_excerpt",
        "corpus_boundary",
        "prompt_safety",
    }
)
_DOCUMENTARY_QUOTATION_PUNCTUATION = frozenset(
    "\"'`\u00ab\u00bb\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u201f"
)
_RETRIEVAL_DISCLOSURES = (
    "documentos disponibles",
    "documentación disponible",
    "fuentes disponibles",
    "corpus",
    "fragmentos recuperados",
    "material recuperado",
    "evidencia recuperada",
    "evidencia disponible",
    "según los documentos",
    "según las fuentes",
)
_PERSONALITY_CATEGORIES = ("character_fidelity", "conversational_presence")


def _contains_standalone_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


class DeterministicCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    group: CheckGroup
    passed: bool
    critical: bool
    detail: str


class QualityGateRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    passed: bool
    detail: str


class QualityGateReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    passed: bool
    rules: tuple[QualityGateRule, ...]
    provider_errors: tuple[str, ...]
    category_averages: dict[str, float]
    metrics: dict[str, float]


def normalize_phrase(value: str) -> str:
    """Normalize only enough for reviewed phrase presence/absence checks."""
    normalized = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _utf16_slice(text: str, start: int, end: int) -> str | None:
    if start < 0 or end < start:
        return None
    encoded = text.encode("utf-16-le")
    start_byte = start * 2
    end_byte = end * 2
    if end_byte > len(encoded):
        return None
    try:
        return encoded[start_byte:end_byte].decode("utf-16-le")
    except UnicodeDecodeError:
        return None


def _page_text(corpus: Any, page: int) -> str | None:
    if corpus is None:
        return None
    for item in getattr(getattr(corpus, "sidecar", None), "pages", ()):
        if getattr(item, "page", None) == page:
            text = getattr(item, "text", None)
            return text if isinstance(text, str) else None
    return None


def _check(
    check_id: str,
    group: CheckGroup,
    passed: bool,
    detail: str,
    *,
    case_critical: bool,
) -> DeterministicCheck:
    return DeterministicCheck(
        id=check_id,
        group=group,
        passed=passed,
        critical=case_critical or group in _ALWAYS_CRITICAL_GROUPS,
        detail=detail,
    )


def run_turn_checks(
    completion: CompleteEventData | None,
    expectation: TurnExpectation,
    *,
    corpus: Any,
    case_critical: bool,
    input_state: LearningState | None = None,
    submitted_action_id: str | None = None,
) -> tuple[DeterministicCheck, ...]:
    """Evaluate contracts that can be proved without interpreting historical meaning.

    Provider and retrieval failures are operational errors, not quality results, so a
    missing completion intentionally yields no deterministic passes.
    """
    if completion is None:
        return ()

    checks: list[DeterministicCheck] = []

    citations = completion.citations
    numbering_ok = [citation.number for citation in citations] == list(range(1, len(citations) + 1))
    checks.append(
        _check(
            "citation-numbering",
            "citation_integrity",
            numbering_ok,
            "Citation numbers are consecutive and one-based."
            if numbering_ok
            else "Citation numbers are not consecutive and one-based.",
            case_critical=case_critical,
        )
    )
    citation_numbers = {citation.number for citation in citations}
    card_numbers = [number for source in completion.sources for number in source.citation_numbers]
    source_blocks_ok = all(
        set(block.citation_numbers) <= set(source.citation_numbers)
        for source in completion.sources
        for block in source.evidence_blocks
    ) and all(
        set(source.citation_numbers)
        == {number for block in source.evidence_blocks for number in block.citation_numbers}
        for source in completion.sources
    )
    grouping_ok = (
        set(card_numbers) == citation_numbers
        and len(card_numbers) == len(set(card_numbers))
        and source_blocks_ok
    )
    checks.append(
        _check(
            "citation-source-grouping",
            "citation_integrity",
            grouping_ok,
            "Every citation belongs to exactly one consolidated source card and block."
            if grouping_ok
            else "Citation-to-source-card grouping is incomplete or duplicated.",
            case_critical=case_critical,
        )
    )
    minimum_ok = len(citations) >= expectation.minimum_citations
    checks.append(
        _check(
            "minimum-citations",
            "citation_integrity",
            minimum_ok,
            f"Found {len(citations)} citations; required {expectation.minimum_citations}.",
            case_critical=case_critical,
        )
    )
    offsets_ok = all(
        _utf16_slice(completion.final_text, citation.start_index, citation.end_index)
        == citation.supported_text
        for citation in citations
    )
    checks.append(
        _check(
            "citation-offsets",
            "citation_integrity",
            offsets_ok,
            "All citation spans match final text using UTF-16 offsets."
            if offsets_ok
            else "At least one citation span does not match final text.",
            case_critical=case_critical,
        )
    )

    evidence_blocks = [block for source in completion.sources for block in source.evidence_blocks]
    excerpts = [block for block in evidence_blocks if block.excerpt is not None]
    manifest_excerpts = getattr(getattr(corpus, "manifest", None), "excerpts", None)
    excerpts_ok = True
    for block in excerpts:
        page_text = _page_text(corpus, block.page) if block.page is not None else None
        normalized_excerpt = normalize_phrase(block.excerpt or "")
        local_occurrences = (
            normalize_phrase(page_text).count(normalized_excerpt)
            if page_text is not None and normalized_excerpt
            else 0
        )
        identity_ok = True
        if manifest_excerpts is not None:
            matches = [
                excerpt
                for excerpt in manifest_excerpts
                if getattr(excerpt, "id", None) == block.excerpt_id
                and getattr(excerpt, "review_status", None) == "reviewed"
                and getattr(excerpt, "page", None) == block.page
                and getattr(excerpt, "section_id", None) == block.section_id
                and getattr(excerpt, "evidence_type", None) == block.evidence_type
                and getattr(excerpt, "text", None) == block.excerpt
            ]
            identity_ok = len(matches) == 1
        if local_occurrences != 1 or not identity_ok:
            excerpts_ok = False
            break
    checks.append(
        _check(
            "verified-excerpts",
            "verified_excerpt",
            excerpts_ok,
            f"Verified {len(excerpts)} local excerpts against declared pages."
            if excerpts_ok
            else "At least one excerpt is absent from its declared local page.",
            case_critical=case_critical,
        )
    )

    actual_documents = {
        source.document_id for source in completion.sources if source.document_id is not None
    }
    documents_ok = set(expectation.expected_document_ids) <= actual_documents
    checks.append(
        _check(
            "expected-documents",
            "corpus_boundary",
            documents_ok,
            "All expected document IDs are present."
            if documents_ok
            else "One or more expected document IDs are absent.",
            case_critical=case_critical,
        )
    )
    actual_sections = {
        block.evidence_type for block in evidence_blocks if block.evidence_type is not None
    }
    sections_ok = set(expectation.expected_section_types) <= actual_sections
    checks.append(
        _check(
            "expected-section-types",
            "corpus_boundary",
            sections_ok,
            "All expected evidence section types are present."
            if sections_ok
            else "One or more expected evidence section types are absent.",
            case_critical=case_critical,
        )
    )
    actual_topics = {topic_id for block in evidence_blocks for topic_id in block.learning_topic_ids}
    topics_ok = set(expectation.expected_topics) <= actual_topics
    checks.append(
        _check(
            "expected-learning-topics",
            "corpus_boundary",
            topics_ok,
            "All expected learning topics are supported by mapped evidence."
            if topics_ok
            else "One or more expected learning topics lack mapped evidence.",
            case_critical=case_critical,
        )
    )
    source_actions = [
        action for action in completion.educational_actions if action.type == "source"
    ]
    exact_evidence_urls = {
        f"/api/corpus/artigas#page={block.page}"
        for source in completion.sources
        for block in source.evidence_blocks
        if block.page is not None and block.page > 0
    }
    strongest_url: str | None = None
    if corpus is not None and callable(getattr(corpus, "resolve_document", None)):
        analysis = analyze_citations(completion.citations, corpus)
        ranked_topics = rank_learning_topics(analysis, corpus)
        strongest = select_strongest_citation(analysis, ranked_topics[0]) if ranked_topics else None
        if strongest is not None and strongest.citation.page is not None:
            strongest_url = corpus.pdf_url(strongest.citation.page)
    source_actions_ok = len(source_actions) <= 1 and all(
        action.url is not None
        and re.fullmatch(r"/api/corpus/artigas#page=[1-9]\d*", action.url) is not None
        and action.url == (strongest_url or action.url)
        and action.url in exact_evidence_urls
        for action in source_actions
    )
    pdf_urls_ok = source_actions_ok and all(
        source.pdf_url is None
        or (source.pages and source.pdf_url == f"/api/corpus/artigas#page={source.pages[0]}")
        for source in completion.sources
    )
    checks.append(
        _check(
            "pdf-urls",
            "corpus_boundary",
            pdf_urls_ok,
            "Corpus links use physical one-based PDF fragments."
            if pdf_urls_ok
            else "At least one corpus link is inconsistent with its physical page.",
            case_critical=case_critical,
        )
    )

    normalized_answer = normalize_phrase(completion.final_text)
    forbidden_matches = [
        phrase
        for phrase in expectation.forbidden_claims
        if normalize_phrase(phrase) in normalized_answer
    ]
    checks.append(
        _check(
            "forbidden-claims",
            "prompt_safety",
            not forbidden_matches,
            "No reviewed forbidden claim is present."
            if not forbidden_matches
            else f"Matched {len(forbidden_matches)} reviewed forbidden claim(s).",
            case_critical=case_critical,
        )
    )
    quotation_ok = not any(
        punctuation in completion.final_text for punctuation in _DOCUMENTARY_QUOTATION_PUNCTUATION
    )
    checks.append(
        _check(
            "generated-quotation-punctuation",
            "prompt_safety",
            quotation_ok,
            "Generated answer contains no quotation punctuation."
            if quotation_ok
            else "Generated answer contains prohibited quotation punctuation.",
            case_critical=case_critical,
        )
    )
    disclosure_matches = [
        phrase
        for phrase in _RETRIEVAL_DISCLOSURES
        if _contains_standalone_phrase(normalized_answer, normalize_phrase(phrase))
    ]
    checks.append(
        _check(
            "character-retrieval-disclosure",
            "prompt_safety",
            not disclosure_matches,
            "Visible answer does not disclose retrieval machinery."
            if not disclosure_matches
            else f"Matched {len(disclosure_matches)} retrieval disclosure phrase(s).",
            case_critical=case_critical,
        )
    )
    self_reference_matches = [
        alias
        for alias in ARTIGAS_PROFILE.third_person_self_references
        if _contains_standalone_phrase(normalized_answer, normalize_phrase(alias))
    ]
    checks.append(
        _check(
            "character-third-person-self-reference",
            "prompt_safety",
            not self_reference_matches,
            "Visible answer contains no configured third-person self-reference."
            if not self_reference_matches
            else f"Matched {len(self_reference_matches)} configured self-reference(s).",
            case_critical=case_critical,
        )
    )

    status_ok = completion.answer_status == expectation.expected_status
    checks.append(
        _check(
            "answer-status",
            "content_contract",
            status_ok,
            f"Answer status is {completion.answer_status}; expected {expectation.expected_status}.",
            case_critical=case_critical,
        )
    )
    if expectation.expected_status == "documentary_limitation":
        opening_ok = completion.final_text.strip() == DOCUMENTARY_LIMIT_RESPONSE
    elif expectation.expected_status == "contemporary_reconstruction":
        opening_ok = (
            completion.final_text.strip()
            .strip("\u00ab\u00bb")
            .strip()
            .startswith(RECONSTRUCTION_OPENING)
        )
    else:
        opening_ok = True
    checks.append(
        _check(
            "answer-opening",
            "content_contract",
            opening_ok,
            "Answer uses the exact reviewed limitation or reconstruction opening."
            if opening_ok
            else "Answer does not use the exact reviewed status opening.",
            case_critical=case_critical,
        )
    )
    missing_concepts = [
        concept
        for concept in expectation.required_concepts
        if normalize_phrase(concept) not in normalized_answer
    ]
    checks.append(
        _check(
            "required-concepts",
            "content_contract",
            not missing_concepts,
            "All reviewed required concepts are present."
            if not missing_concepts
            else f"Missing {len(missing_concepts)} reviewed required concept(s).",
            case_critical=case_critical,
        )
    )
    visible_words = len(re.findall(r"\S+", completion.final_text))
    word_limit = expectation.maximum_visible_words
    words_ok = word_limit is None or visible_words <= word_limit
    checks.append(
        _check(
            "visible-word-count",
            "content_contract",
            words_ok,
            f"Visible answer contains {visible_words} words"
            + (f"; maximum is {word_limit}." if word_limit is not None else "."),
            case_critical=case_critical,
        )
    )

    action_types = tuple(action.type for action in completion.educational_actions)
    expected_action_types = expectation.expected_action_types
    has_reliable_mapped_evidence = any(
        source.document_id is not None
        and block.section_id is not None
        and block.evidence_type is not None
        and bool(block.learning_topic_ids)
        for source in completion.sources
        for block in source.evidence_blocks
    )
    if expected_action_types:
        actions_ok = action_types == expected_action_types
        action_contract = f"expected {list(expected_action_types)}"
    elif (
        completion.answer_status in {"conversational", "documentary_limitation"}
        or expectation.expected_status in {"conversational", "documentary_limitation"}
        or not has_reliable_mapped_evidence
    ):
        actions_ok = not action_types
        action_contract = "expected no actions for this status or evidence mapping"
    else:
        actions_ok = True
        action_contract = "no explicit ordered action contract"
    checks.append(
        _check(
            "educational-action-types",
            "education_contract",
            actions_ok,
            f"Action types are {list(action_types)}; {action_contract}.",
            case_critical=case_critical,
        )
    )
    action_ids = [
        action.action_id
        for action in completion.educational_actions
        if action.action_id is not None
    ]
    actions_unique = len(action_ids) == len(set(action_ids))
    input_state = input_state or LearningState()
    excluded_ids = {*input_state.shown_action_ids, *input_state.selected_action_ids}
    repeats_suppressed = not (set(action_ids) & excluded_ids)
    output_ids_are_shown = set(action_ids) <= set(completion.learning_state.shown_action_ids)
    validate_action_id = getattr(corpus, "validate_action_id", None)
    returned_state_ids = {
        *completion.learning_state.shown_action_ids,
        *completion.learning_state.selected_action_ids,
    }
    returned_ids_valid = not callable(validate_action_id) or all(
        validate_action_id(action_id) is not None for action_id in returned_state_ids
    )
    history_preserved = set(input_state.shown_action_ids) <= set(
        completion.learning_state.shown_action_ids
    ) and set(input_state.selected_action_ids) <= set(completion.learning_state.selected_action_ids)
    arrays_normalized = completion.learning_state.shown_action_ids == sorted(
        set(completion.learning_state.shown_action_ids)
    ) and completion.learning_state.selected_action_ids == sorted(
        set(completion.learning_state.selected_action_ids)
    )
    submitted_selected = (
        submitted_action_id is None
        or not callable(validate_action_id)
        or validate_action_id(submitted_action_id) is None
        or submitted_action_id in completion.learning_state.selected_action_ids
    )
    state_ok = (
        completion.learning_state.submitted_action_id is None
        and actions_unique
        and repeats_suppressed
        and output_ids_are_shown
        and returned_ids_valid
        and history_preserved
        and arrays_normalized
        and submitted_selected
    )
    checks.append(
        _check(
            "learning-state-contract",
            "education_contract",
            state_ok,
            "Returned learning state consumed submission and action IDs are unique."
            if state_ok
            else "Learning submission was not consumed or action IDs repeat.",
            case_critical=case_critical,
        )
    )
    submitted_action = (
        validate_action_id(submitted_action_id)
        if callable(validate_action_id) and submitted_action_id is not None
        else None
    )
    expected_depths = dict(input_state.topic_depths)
    if submitted_action is not None:
        depth_rank: dict[TopicDepth, int] = {
            "introductory": 0,
            "deeper": 1,
            "comparative": 2,
        }
        submitted_depth = getattr(submitted_action, "depth", None)
        submitted_topic = getattr(submitted_action, "topic_id", None)
        next_depth: dict[TopicDepth, TopicDepth] = {
            "introductory": "deeper",
            "deeper": "comparative",
            "comparative": "comparative",
        }
        if submitted_depth in next_depth and submitted_topic in LearningTopicId.__args__:
            required_depth = next_depth[cast(TopicDepth, submitted_depth)]
            actual_depth = completion.learning_state.topic_depths.get(
                cast(LearningTopicId, submitted_topic), "introductory"
            )
            current_depth = expected_depths.get(
                cast(LearningTopicId, submitted_topic), "introductory"
            )
            if depth_rank[required_depth] > depth_rank[current_depth]:
                expected_depths[cast(LearningTopicId, submitted_topic)] = required_depth
            progression_shape_valid = actual_depth == expected_depths.get(
                cast(LearningTopicId, submitted_topic), "introductory"
            )
        else:
            progression_shape_valid = False
    else:
        progression_shape_valid = True
    progression_ok = (
        progression_shape_valid and completion.learning_state.topic_depths == expected_depths
    )
    checks.append(
        _check(
            "learning-depth-progression",
            "education_contract",
            progression_ok,
            "Formal topic depth changed only for a reviewed submitted action."
            if progression_ok
            else "Formal topic depth did not follow the reviewed progression contract.",
            case_critical=case_critical,
        )
    )

    usage = completion.usage
    usage_ok = (
        usage.total_tokens >= (usage.input_tokens + usage.output_tokens + usage.thought_tokens)
        and usage.estimated_cost_usd >= 0
    )
    checks.append(
        _check(
            "usage-observation",
            "performance_observation",
            usage_ok,
            "Usage and estimated cost are internally bounded."
            if usage_ok
            else "Usage fields are internally inconsistent.",
            case_critical=case_critical,
        )
    )
    return tuple(checks)


def checks_to_payload(checks: Sequence[DeterministicCheck]) -> list[dict[str, Any]]:
    return [check.model_dump(mode="json") for check in checks]


def evaluate_quality_gate(
    payload: dict[str, Any],
    *,
    metrics: dict[str, float],
    baseline_metrics: dict[str, float] | None = None,
    deterministic_checks_complete: bool = True,
    case_matrix_complete: bool = True,
) -> QualityGateReport:
    """Apply the release rules without mutating an evaluation result."""
    cases = payload.get("cases", [])
    review = payload.get("review", {})
    review_cases = review.get("cases", {}) if isinstance(review, dict) else {}
    performance = review.get("performance", {}) if isinstance(review, dict) else {}
    checks: list[dict[str, Any]] = []
    critical_case_failures: list[str] = []
    provider_errors: list[str] = []
    live_provider_errors: list[str] = []
    for case in cases:
        case_id = case.get("id", "unknown")
        errors = case.get("operational_errors", [])
        for error in errors:
            code = error.get("code", "provider_error") if isinstance(error, dict) else "error"
            provider_errors.append(f"{case_id}: {code}")
            if case.get("execution") != "fixture":
                live_provider_errors.append(case_id)
        case_checks = [
            check
            for turn in case.get("turns", [])
            for check in turn.get("checks", [])
            if isinstance(check, dict)
        ]
        checks.extend(case_checks)
        if case.get("critical") and any(not check.get("passed", False) for check in case_checks):
            critical_case_failures.append(case_id)

    rules: list[QualityGateRule] = []
    rules.append(
        QualityGateRule(
            id="deterministic-check-completeness",
            passed=deterministic_checks_complete,
            detail="Stored deterministic evidence matches a fresh local recomputation."
            if deterministic_checks_complete
            else "Stored deterministic evidence is missing or differs from recomputation.",
        )
    )
    rules.append(
        QualityGateRule(
            id="case-matrix-complete",
            passed=case_matrix_complete,
            detail="Result contains the exact current evaluation case matrix."
            if case_matrix_complete
            else "Result is missing or reorders current evaluation cases.",
        )
    )
    group_rule_ids = {
        "citation_integrity": "citation-integrity",
        "verified_excerpt": "verified-excerpts",
        "corpus_boundary": "corpus-boundary",
        "prompt_safety": "prompt-safety",
    }
    for group, rule_id in group_rule_ids.items():
        group_checks = [check for check in checks if check.get("group") == group]
        passed = bool(group_checks) and all(check.get("passed") is True for check in group_checks)
        rules.append(
            QualityGateRule(
                id=rule_id,
                passed=passed,
                detail=f"{sum(check.get('passed') is True for check in group_checks)}/"
                f"{len(group_checks)} checks passed.",
            )
        )

    remaining = [check for check in checks if check.get("group") not in group_rule_ids]
    remaining_passed = sum(check.get("passed") is True for check in remaining)
    remaining_rate = remaining_passed / len(remaining) if remaining else 0.0
    rules.append(
        QualityGateRule(
            id="remaining-deterministic",
            passed=bool(remaining) and remaining_rate >= 0.9,
            detail=f"{remaining_passed}/{len(remaining)} checks passed ({remaining_rate:.1%}).",
        )
    )

    scores_by_category: dict[str, list[int]] = defaultdict(list)
    complete_scores = True
    human_score_failures: list[str] = []
    core_score_one: list[str] = []
    personality_score_failures: list[str] = []
    personality_scores: list[int] = []
    personality_case_count = 0
    for case in cases:
        required = case.get("human_review", [])
        if not required:
            continue
        case_id = case.get("id", "unknown")
        reviewed = review_cases.get(case_id, {}) if isinstance(review_cases, dict) else {}
        scores = reviewed.get("scores", {}) if isinstance(reviewed, dict) else {}
        category_notes = reviewed.get("category_notes") if isinstance(reviewed, dict) else None
        if not isinstance(scores, dict) or set(scores) != set(required):
            complete_scores = False
        if not category_notes_are_valid(category_notes, required, scores):
            complete_scores = False
        for category in required:
            score = scores.get(category) if isinstance(scores, dict) else None
            if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 4:
                complete_scores = False
                continue
            scores_by_category[category].append(score)
            if score < 3:
                human_score_failures.append(f"{case_id}:{category}")
            if case.get("core_historical") and score == 1:
                core_score_one.append(f"{case_id}:{category}")
        if set(_PERSONALITY_CATEGORIES) <= set(required):
            personality_case_count += 1
            case_personality_scores = [
                scores.get(category) if isinstance(scores, dict) else None
                for category in _PERSONALITY_CATEGORIES
            ]
            valid_personality_scores = [
                score
                for score in case_personality_scores
                if isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 4
            ]
            if len(valid_personality_scores) == len(_PERSONALITY_CATEGORIES):
                personality_scores.extend(valid_personality_scores)
                if any(score < 3 for score in valid_personality_scores):
                    personality_score_failures.append(str(case_id))
            else:
                personality_score_failures.append(f"{case_id}:scores-missing")
    category_averages = {
        category: sum(values) / len(values) for category, values in scores_by_category.items()
    }
    expected_categories = {category for case in cases for category in case.get("human_review", [])}
    averages_pass = (
        bool(expected_categories)
        and expected_categories == set(category_averages)
        and all(average >= 3.25 for average in category_averages.values())
    )
    personality_average = (
        sum(personality_scores) / len(personality_scores) if personality_scores else 0.0
    )
    rules.extend(
        [
            QualityGateRule(
                id="rubric-category-averages",
                passed=averages_pass,
                detail=", ".join(
                    f"{category}={average:.2f}"
                    for category, average in sorted(category_averages.items())
                )
                or "No rubric scores found.",
            ),
            QualityGateRule(
                id="human-score-minimums",
                passed=bool(scores_by_category) and not human_score_failures,
                detail=(
                    "Every assigned human-review score is at least 3."
                    if scores_by_category and not human_score_failures
                    else "Human-review scores below 3: "
                    + (", ".join(human_score_failures) or "scores missing")
                ),
            ),
            QualityGateRule(
                id="personality-case-minimums",
                passed=bool(personality_scores) and not personality_score_failures,
                detail=(
                    "Every personality case scored at least 3 in character specificity and "
                    "conversational presence."
                    if personality_scores and not personality_score_failures
                    else "Personality cases below 3: "
                    + (", ".join(personality_score_failures) or "scores missing")
                ),
            ),
            QualityGateRule(
                id="personality-dimensions-average",
                passed=(
                    len(personality_scores) == personality_case_count * len(_PERSONALITY_CATEGORIES)
                    and personality_average >= 3.5
                ),
                detail=f"Combined personality-dimension average={personality_average:.2f}.",
            ),
            QualityGateRule(
                id="core-historical-no-score-one",
                passed=not core_score_one,
                detail="No core historical case received a 1."
                if not core_score_one
                else "Scores of 1: " + ", ".join(core_score_one),
            ),
            QualityGateRule(
                id="critical-cases",
                passed=not critical_case_failures,
                detail="No critical case has a deterministic failure."
                if not critical_case_failures
                else "Failed critical cases: " + ", ".join(critical_case_failures),
            ),
            QualityGateRule(
                id="human-scores-complete",
                passed=complete_scores,
                detail="Every required score is present and between 1 and 4."
                if complete_scores
                else "One or more required scores are missing or invalid.",
            ),
            QualityGateRule(
                id="performance-acknowledged",
                passed=isinstance(performance, dict) and performance.get("acknowledged") is True,
                detail="Cost and latency review acknowledged."
                if isinstance(performance, dict) and performance.get("acknowledged") is True
                else "Cost and latency review is not acknowledged.",
            ),
        ]
    )

    def regression_rule(metric: str, explanation_key: str, rule_id: str) -> QualityGateRule:
        baseline_value = (baseline_metrics or {}).get(metric)
        current = metrics.get(metric, 0.0)
        regression = (
            baseline_value is not None and baseline_value > 0 and current > baseline_value * 1.15
        )
        explanation = performance.get(explanation_key, "") if isinstance(performance, dict) else ""
        passed = not regression or bool(isinstance(explanation, str) and explanation.strip())
        return QualityGateRule(
            id=rule_id,
            passed=passed,
            detail=(
                f"Current {metric}={current:.6f}; baseline={baseline_value:.6f}; "
                f"explanation {'present' if passed else 'required'}."
                if regression and baseline_value is not None
                else "No p95 regression above 15%."
            ),
        )

    rules.extend(
        [
            regression_rule(
                "p95_cost_usd", "cost_regression_explanation", "cost-regression-explained"
            ),
            regression_rule(
                "p95_latency_ms",
                "latency_regression_explanation",
                "latency-regression-explained",
            ),
            QualityGateRule(
                id="operational-errors",
                passed=not live_provider_errors,
                detail="No live provider or retrieval errors."
                if not live_provider_errors
                else "Live operational errors: " + ", ".join(live_provider_errors),
            ),
        ]
    )
    return QualityGateReport(
        passed=all(rule.passed for rule in rules),
        rules=tuple(rules),
        provider_errors=tuple(provider_errors),
        category_averages=category_averages,
        metrics=metrics,
    )
