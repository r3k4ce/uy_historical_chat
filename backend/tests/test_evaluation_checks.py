from __future__ import annotations

from types import SimpleNamespace

from artigas_mvp_backend.evaluation_checks import normalize_phrase, run_turn_checks
from artigas_mvp_backend.evaluation_models import TurnExpectation
from artigas_mvp_backend.models import CompleteEventData, LearningState


def _expectation(**updates: object) -> TurnExpectation:
    values: dict[str, object] = {
        "expected_status": "documented",
        "expected_document_ids": ("ART-005",),
        "expected_section_types": ("primary_text",),
        "expected_topics": ("instructions-republic-and-liberties",),
        "required_concepts": ("Soberan\u00eda   popular",),
        "forbidden_claims": ("monarqu\u00eda centralista",),
        "minimum_citations": 1,
        "maximum_visible_words": 20,
        "expected_action_types": ("deepen", "source"),
    }
    values.update(updates)
    return TurnExpectation.model_validate(values)


def _completion() -> CompleteEventData:
    text = "La soberan\u00eda popular sostiene la libertad civil."
    return CompleteEventData.model_validate(
        {
            "interaction_id": "interaction-1",
            "final_text": text,
            "citations": [
                {
                    "number": 1,
                    "title": "Corpus",
                    "page": 26,
                    "supported_text": "soberan\u00eda popular",
                    "start_index": 3,
                    "end_index": 20,
                }
            ],
            "answer_status": "documented",
            "sources": [
                {
                    "id": "document-ART-005",
                    "citation_numbers": [1],
                    "document_id": "ART-005",
                    "title": "Instrucciones del A\u00f1o XIII",
                    "date": "1813",
                    "document_type": "Instrucciones",
                    "authorship_classification": "approved_by_collective_body",
                    "relationship_to_artigas": "Decisi\u00f3n colectiva.",
                    "pages": [26],
                    "pdf_url": "/api/corpus/artigas#page=26",
                    "evidence_blocks": [
                        {
                            "id": "evidence-1",
                            "citation_numbers": [1],
                            "section_id": "ART-005-primary",
                            "evidence_type": "primary_text",
                            "page": 26,
                            "excerpt_id": "EX-005-1",
                            "excerpt": "texto documental",
                            "supported_text": "soberan\u00eda popular",
                            "learning_topic_ids": ["instructions-republic-and-liberties"],
                        }
                    ],
                }
            ],
            "educational_actions": [
                {
                    "type": "deepen",
                    "label": "Profundizar",
                    "action_id": "action-1",
                    "question": "\u00bfC\u00f3mo se expresa?",
                    "url": None,
                },
                {
                    "type": "source",
                    "label": "Examinar la fuente",
                    "action_id": None,
                    "question": None,
                    "url": "/api/corpus/artigas#page=26",
                },
            ],
            "learning_state": {
                "shown_action_ids": ["action-1"],
                "selected_action_ids": [],
                "submitted_action_id": None,
                "topic_depths": {},
            },
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 0,
                "output_tokens": 20,
                "thought_tokens": 5,
                "total_tokens": 35,
                "estimated_cost_usd": 0.000075,
            },
        }
    )


def test_phrase_normalization_is_nfc_whitespace_collapsed_and_casefolded() -> None:
    assert normalize_phrase("  SOBERANI\u0301A\n popular ") == "soberan\u00eda popular"


def test_deterministic_checks_cover_all_contract_groups_and_pass() -> None:
    corpus = SimpleNamespace(
        sidecar=SimpleNamespace(
            pages=(SimpleNamespace(page=26, text="Aqu\u00ed figura el texto documental."),)
        )
    )

    checks = run_turn_checks(_completion(), _expectation(), corpus=corpus, case_critical=False)

    assert checks
    assert all(check.passed for check in checks)
    assert {
        "citation_integrity",
        "verified_excerpt",
        "corpus_boundary",
        "prompt_safety",
        "content_contract",
        "education_contract",
        "performance_observation",
    } <= {check.group for check in checks}
    assert all(
        check.critical
        for check in checks
        if check.group
        in {"citation_integrity", "verified_excerpt", "corpus_boundary", "prompt_safety"}
    )


def _action_types_check(completion: CompleteEventData, expectation: TurnExpectation):
    return next(
        check
        for check in run_turn_checks(
            completion,
            expectation,
            corpus=None,
            case_critical=False,
        )
        if check.id == "educational-action-types"
    )


def test_empty_action_expectation_is_unspecified_for_documented_mapped_evidence() -> None:
    check = _action_types_check(
        _completion(),
        _expectation(expected_action_types=()),
    )

    assert check.passed


def test_empty_action_expectation_still_forbids_actions_for_non_evidentiary_statuses() -> None:
    for status in ("conversational", "documentary_limitation"):
        completion = _completion().model_copy(update={"answer_status": status})
        expectation = _expectation(expected_status=status, expected_action_types=())

        assert not _action_types_check(completion, expectation).passed


def test_empty_action_expectation_forbids_actions_without_reliable_mapped_evidence() -> None:
    source = _completion().sources[0]
    evidence = source.evidence_blocks[0].model_copy(
        update={
            "section_id": None,
            "evidence_type": None,
            "learning_topic_ids": [],
        }
    )
    unmapped_source = source.model_copy(
        update={
            "document_id": None,
            "pages": [],
            "pdf_url": None,
            "evidence_blocks": [evidence],
        }
    )
    completion = _completion().model_copy(update={"sources": [unmapped_source]})

    assert not _action_types_check(
        completion,
        _expectation(expected_action_types=()),
    ).passed


def test_nonempty_action_expectation_remains_an_exact_ordered_contract() -> None:
    completion = _completion()

    assert _action_types_check(completion, _expectation()).passed
    assert not _action_types_check(
        completion,
        _expectation(expected_action_types=("source", "deepen")),
    ).passed


def test_quote_punctuation_forbidden_phrase_and_bad_offset_fail_separately() -> None:
    completion = _completion().model_copy(
        update={
            "final_text": (
                "\u00abLa soberan\u00eda popular\u00bb defiende una monarqu\u00eda centralista."
            )
        }
    )

    checks = run_turn_checks(completion, _expectation(), corpus=None, case_critical=True)
    failures = {check.id: check for check in checks if not check.passed}

    assert "citation-offsets" in failures
    assert "generated-quotation-punctuation" in failures
    assert "forbidden-claims" in failures
    assert all(check.critical for check in checks)


def test_all_prompt_forbidden_quote_delimiters_fail_the_quality_gate() -> None:
    for opening, closing in (
        ("'", "'"),
        ("\u2018", "\u2019"),
        ("\u201a", "\u201b"),
        ("`", "`"),
    ):
        completion = _completion().model_copy(
            update={"final_text": f"{opening}La soberanía popular{closing} sostiene la libertad."}
        )

        quote_check = next(
            check
            for check in run_turn_checks(
                completion,
                _expectation(),
                corpus=None,
                case_critical=False,
            )
            if check.id == "generated-quotation-punctuation"
        )

        assert quote_check.passed is False


def test_provider_errors_are_not_deterministic_quality_passes() -> None:
    checks = run_turn_checks(None, _expectation(), corpus=None, case_critical=True)

    assert checks == ()


def test_citation_grouping_and_exact_reviewed_excerpt_identity_are_checked() -> None:
    completion = _completion()
    source = completion.sources[0].model_copy(
        update={"citation_numbers": [], "evidence_blocks": completion.sources[0].evidence_blocks}
    )
    completion = completion.model_copy(update={"sources": [source]})
    corpus = SimpleNamespace(
        sidecar=SimpleNamespace(
            pages=(SimpleNamespace(page=26, text="texto documental texto documental"),)
        ),
        manifest=SimpleNamespace(excerpts=()),
    )

    failures = {
        check.id
        for check in run_turn_checks(completion, _expectation(), corpus=corpus, case_critical=False)
        if not check.passed
    }

    assert "citation-source-grouping" in failures
    assert "verified-excerpts" in failures


def test_learning_state_checks_repeat_suppression_and_valid_submission() -> None:
    completion = _completion()
    corpus = SimpleNamespace(validate_action_id=lambda action_id: object())

    failures = {
        check.id
        for check in run_turn_checks(
            completion,
            _expectation(),
            corpus=corpus,
            case_critical=False,
            input_state=LearningState(shown_action_ids=["action-1"]),
            submitted_action_id="submitted-action",
        )
        if not check.passed
    }

    assert "learning-state-contract" in failures


def test_exact_status_opening_and_depth_progression_are_checked() -> None:
    completion = _completion().model_copy(
        update={
            "answer_status": "contemporary_reconstruction",
            "final_text": "Una reconstrucción sin la apertura revisada.",
            "learning_state": LearningState(
                shown_action_ids=["action-1"],
                selected_action_ids=["submitted-action"],
                topic_depths={"instructions-republic-and-liberties": "introductory"},
            ),
        }
    )
    submitted = SimpleNamespace(
        id="submitted-action",
        topic_id="instructions-republic-and-liberties",
        depth="introductory",
    )
    corpus = SimpleNamespace(
        validate_action_id=lambda action_id: (
            submitted if action_id == "submitted-action" else object()
        )
    )
    expectation = _expectation(expected_status="contemporary_reconstruction")

    failures = {
        check.id
        for check in run_turn_checks(
            completion,
            expectation,
            corpus=corpus,
            case_critical=False,
            submitted_action_id="submitted-action",
        )
        if not check.passed
    }

    assert "answer-opening" in failures
    assert "learning-depth-progression" in failures


def test_state_history_and_unrelated_topic_depth_must_be_preserved_exactly() -> None:
    completion = _completion().model_copy(
        update={
            "learning_state": LearningState(
                shown_action_ids=["action-1"],
                selected_action_ids=["submitted-action"],
                topic_depths={
                    "instructions-republic-and-liberties": "deeper",
                    "sovereignty-and-legitimacy": "deeper",
                },
            )
        }
    )
    submitted = SimpleNamespace(
        id="submitted-action",
        topic_id="instructions-republic-and-liberties",
        depth="introductory",
    )
    corpus = SimpleNamespace(
        validate_action_id=lambda action_id: (
            submitted if action_id == "submitted-action" else object()
        )
    )
    input_state = LearningState(
        shown_action_ids=["old-shown"],
        selected_action_ids=["old-selected"],
        topic_depths={"sovereignty-and-legitimacy": "comparative"},
    )

    failures = {
        check.id
        for check in run_turn_checks(
            completion,
            _expectation(),
            corpus=corpus,
            case_critical=False,
            input_state=input_state,
            submitted_action_id="submitted-action",
        )
        if not check.passed
    }

    assert "learning-state-contract" in failures
    assert "learning-depth-progression" in failures


def test_source_action_url_must_match_a_positive_mapped_physical_page() -> None:
    completion = _completion()
    bad_source_action = completion.educational_actions[1].model_copy(
        update={"url": "/api/corpus/artigas#page=garbage"}
    )
    completion = completion.model_copy(
        update={"educational_actions": [completion.educational_actions[0], bad_source_action]}
    )

    failures = {
        check.id
        for check in run_turn_checks(completion, _expectation(), corpus=None, case_critical=False)
        if not check.passed
    }

    assert "pdf-urls" in failures


def test_source_action_may_target_strongest_evidence_after_card_first_page() -> None:
    completion = _completion()
    source = completion.sources[0].model_copy(
        update={"pages": [24, 26], "pdf_url": "/api/corpus/artigas#page=24"}
    )
    completion = completion.model_copy(update={"sources": [source]})

    checks = run_turn_checks(completion, _expectation(), corpus=None, case_critical=False)

    assert next(check for check in checks if check.id == "pdf-urls").passed
