from __future__ import annotations

import asyncio
import io
import json
import unicodedata
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import pytest
import yaml
from pydantic import ValidationError

from artigas_mvp_backend.corpus import CorpusPaths, load_learning_map, load_source_manifest
from artigas_mvp_backend.corpus_models import LearningTopicId
from artigas_mvp_backend.evaluate import main
from artigas_mvp_backend.evaluation_models import (
    EvaluationDataset,
    EvaluationTurn,
    HumanRubric,
    TurnExpectation,
)
from artigas_mvp_backend.models import Citation, HistoryMessage
from artigas_mvp_backend.services.chat import ChatCompleted, ChatTextDelta
from artigas_mvp_backend.services.corpus import CorpusService
from artigas_mvp_backend.services.evidence import analyze_citations
from artigas_mvp_backend.services.usage import NormalizedUsage

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "artigas-cases.yaml"
RUBRIC = ROOT / "evals" / "rubric.yaml"
FIXTURES = ROOT / "evals" / "fixtures"


def load_dataset() -> EvaluationDataset:
    return EvaluationDataset.model_validate(yaml.safe_load(DATASET.read_text(encoding="utf-8")))


def test_dataset_has_the_fixed_sixty_case_matrix() -> None:
    dataset = load_dataset()
    cases = dataset.cases

    assert dataset.schema_version == 2
    assert len(cases) == 60
    assert len({case.id for case in cases}) == 60
    assert Counter(case.execution for case in cases) == {"live": 58, "fixture": 2}
    assert sum(len(case.turns) == 1 and case.execution == "live" for case in cases) == 42
    assert sum(len(case.turns) > 1 for case in cases) == 16
    assert all(len(case.turns) == 2 for case in cases if len(case.turns) > 1)

    expected_ids = {
        *(f"art-{number:03d}-core" for number in range(1, 16)),
        *(f"topic-{topic}" for topic in LearningTopicId.__args__),
        "authorship-art-004-collective",
        "authorship-art-005-collective",
        "authorship-art-012-authority",
        "authorship-art-015-attributed",
        "editorial-not-memory",
        "exact-quotation-request",
        "unsupported-corpus-boundary",
        "false-centralist-premise",
        "greeting",
        "prompt-injection",
        "prompt-extraction",
        "false-modern-attribution",
        "modern-reconstruction",
        "concise-answer",
        "detailed-answer",
        "broad-overview",
        "multi-document-synthesis",
        "source-card-consolidation",
        "pdf-evidence-link-contract",
        "unmapped-citation-fixture",
        "provider-error-fixture",
    }
    assert expected_ids <= {case.id for case in cases}


def test_dataset_references_only_reviewed_documents_topics_and_actions() -> None:
    dataset = load_dataset()
    manifest = load_source_manifest(ROOT / "data" / "source-manifest.yaml")
    learning_map = load_learning_map(ROOT / "data" / "learning-map.yaml")
    document_ids = {document.id for document in manifest.documents}
    topic_ids = {topic.id for topic in learning_map.topics}
    action_ids = {action.id for action in learning_map.actions if action.active}

    expected_documents: set[str] = set()
    expected_topics: set[str] = set()
    for case in dataset.cases:
        for turn in case.turns:
            expected_documents.update(turn.expect.expected_document_ids)
            expected_topics.update(turn.expect.expected_topics)
            assert set(turn.expect.expected_document_ids) <= document_ids
            assert set(turn.expect.expected_topics) <= topic_ids
            if turn.submitted_action_id is not None:
                assert turn.submitted_action_id in action_ids | {"stale-action"}
            if turn.learning_state is not None:
                assert set(turn.learning_state.shown_action_ids) <= action_ids | {"stale-action"}
                assert set(turn.learning_state.selected_action_ids) <= action_ids | {"stale-action"}

    assert expected_documents == document_ids
    assert expected_topics == topic_ids


def test_every_turn_has_a_complete_bounded_expectation() -> None:
    dataset = load_dataset()
    all_categories = {
        "historical_accuracy",
        "source_interpretation",
        "educational_usefulness",
        "character_fidelity",
        "conversational_presence",
    }

    for case in dataset.cases:
        assert case.human_review or case.execution == "fixture"
        if case.execution == "live":
            assert set(case.human_review) == all_categories
        else:
            assert case.human_review == ()
        for turn in case.turns:
            expectation = turn.expect
            assert turn.prompt.strip()
            assert (
                expectation.required_concepts
                or expectation.expected_status
                in {
                    "documentary_limitation",
                    "conversational",
                }
                or case.id == "exact-quotation-request"
            )
            assert expectation.minimum_citations >= 0
            assert (
                expectation.maximum_visible_words is None or expectation.maximum_visible_words > 0
            )
            assert len(set(expectation.expected_action_types)) == len(
                expectation.expected_action_types
            )
            if expectation.expected_status == "documented" and case.execution == "live":
                assert expectation.minimum_citations > 0
            if expectation.expected_status in {"documentary_limitation", "conversational"}:
                assert expectation.expected_action_types == ()


def test_ambiguous_live_sources_do_not_require_unprovable_mapping_or_actions() -> None:
    cases = {case.id: case for case in load_dataset().cases}
    ambiguous_turns = {
        ("art-001-core", 0),
        ("art-007-core", 0),
        ("art-011-core", 0),
        ("art-014-core", 0),
        ("authorship-art-004-collective", 0),
        ("authorship-art-005-collective", 0),
        ("authorship-art-012-authority", 0),
        ("authorship-art-015-attributed", 0),
        ("sovereignty-comparison", 0),
        ("government-repeat-suppression", 0),
        ("government-repeat-suppression", 1),
        ("buenos-aires-carried-state", 1),
        ("economy-carried-state", 1),
    }

    for case_id, turn_index in ambiguous_turns:
        expectation = cases[case_id].turns[turn_index].expect
        assert expectation.expected_section_types == ()
        assert expectation.expected_topics == ()
        assert expectation.expected_action_types == ()


def test_dataset_retains_meaningful_deterministic_contract_coverage() -> None:
    live_turns = [
        turn for case in load_dataset().cases if case.execution == "live" for turn in case.turns
    ]
    core_cases = {
        case.id: case
        for case in load_dataset().cases
        if case.id.startswith("art-") and case.id.endswith("-core")
    }

    assert len(core_cases) == 15
    for number in range(1, 16):
        case = core_cases[f"art-{number:03d}-core"]
        assert case.turns[0].expect.expected_document_ids == (f"ART-{number:03d}",)
    assert sum(bool(turn.expect.expected_topics) for turn in live_turns) >= 38
    assert sum(bool(turn.expect.expected_action_types) for turn in live_turns) >= 45
    assert sum(bool(turn.expect.required_concepts) for turn in live_turns) >= 60
    assert all(
        len(concept.strip()) >= 5
        for turn in live_turns
        for concept in turn.expect.required_concepts
    )


def test_live_topic_contracts_are_reachable_from_reliably_mapped_pages() -> None:
    corpus = CorpusService.load(CorpusPaths.repository_defaults(), production_ready=True)
    reachable: dict[str, set[str]] = {}
    reachable_types: dict[str, set[str]] = {}
    for document in corpus.manifest.documents:
        topics: set[str] = set()
        section_types: set[str] = set()
        for page in range(document.page_start, document.page_end + 1):
            analysis = analyze_citations(
                (
                    Citation(
                        number=1,
                        title=document.display_title,
                        page=page,
                        supported_text="segmento",
                        start_index=0,
                        end_index=8,
                    ),
                ),
                corpus,
            )
            topics.update(
                topic_id for mapped in analysis.mapped for topic_id in mapped.learning_topic_ids
            )
            section_types.update(
                mapped.evidence_type
                for mapped in analysis.mapped
                if mapped.evidence_type is not None
            )
        reachable[document.id] = topics
        reachable_types[document.id] = section_types

    for case in load_dataset().cases:
        if case.execution != "live":
            continue
        for turn in case.turns:
            document_ids = turn.expect.expected_document_ids or tuple(reachable)
            available = {topic for document_id in document_ids for topic in reachable[document_id]}
            assert set(turn.expect.expected_topics) <= available, case.id
            available_types = {
                section_type
                for document_id in document_ids
                for section_type in reachable_types[document_id]
            }
            assert set(turn.expect.expected_section_types) <= available_types, case.id


def test_required_concepts_are_explicit_unquoted_response_terms() -> None:
    for case in load_dataset().cases:
        if case.execution != "live":
            continue
        for turn in case.turns:
            normalized_prompt = unicodedata.normalize("NFC", turn.prompt).casefold()
            if not turn.expect.required_concepts:
                continue
            assert "use exactamente" in normalized_prompt, case.id
            assert "sin comillas" in normalized_prompt, case.id
            for concept in turn.expect.required_concepts:
                normalized_concept = unicodedata.normalize("NFC", concept).casefold()
                assert normalized_concept in normalized_prompt, (case.id, concept)
                assert f'"{normalized_concept}"' not in normalized_prompt, (case.id, concept)
                assert f"“{normalized_concept}”" not in normalized_prompt, (case.id, concept)


def test_exact_quotation_case_requires_documented_paraphrase_and_normal_guidance() -> None:
    case = next(case for case in load_dataset().cases if case.id == "exact-quotation-request")
    expectation = case.turns[0].expect

    assert "parafrase" in case.turns[0].prompt.casefold()
    assert expectation.expected_status == "documented"
    assert expectation.expected_document_ids == ("ART-012",)
    assert expectation.minimum_citations >= 1
    assert expectation.required_concepts == ()
    assert expectation.expected_action_types
    assert expectation.maximum_visible_words is None


def test_pdf_link_contract_asks_history_instead_of_app_navigation() -> None:
    case = next(case for case in load_dataset().cases if case.id == "pdf-evidence-link-contract")
    prompt = case.turns[0].prompt.casefold()

    assert "grupos prioritarios" in prompt
    assert "fuente y página" not in prompt
    assert "en qué página" not in prompt


def test_retained_multi_document_all_of_contracts_name_every_document() -> None:
    for case in load_dataset().cases:
        if case.execution != "live":
            continue
        for turn in case.turns:
            if len(turn.expect.expected_document_ids) < 2:
                continue
            for document_id in turn.expect.expected_document_ids:
                assert document_id.casefold() in turn.prompt.casefold(), (case.id, document_id)


def test_empirically_ambiguous_mapping_expectations_are_cleared_narrowly() -> None:
    cases = {case.id: case for case in load_dataset().cases}

    for case_id in (
        "topic-sovereignty-and-legitimacy",
        "topic-federalism-and-provincial-autonomy",
        "topic-government-education-and-public-welfare",
        "concise-answer",
    ):
        expectation = cases[case_id].turns[0].expect
        assert expectation.expected_document_ids
        assert expectation.expected_section_types == ()
        assert expectation.expected_topics == ()

    state_followup = cases["buenos-aires-source-action"].turns[1].expect
    assert state_followup.expected_document_ids == ()
    assert state_followup.expected_section_types == ()
    assert state_followup.expected_topics == ("buenos-aires-centralism-and-union",)

    synthesis = cases["multi-document-synthesis"].turns[0].expect
    assert synthesis.expected_document_ids == ("ART-005", "ART-012", "ART-013")
    assert synthesis.expected_topics == (
        "land-society-and-marginalized-groups",
        "economy-war-and-external-relations",
    )

    source_cards = cases["source-card-consolidation"].turns[0].expect
    assert source_cards.expected_section_types == ("primary_text",)


def test_final_live_regressions_clear_only_page_sensitive_mapping_contracts() -> None:
    cases = {case.id: case for case in load_dataset().cases}
    section_sensitive = {
        ("topic-economy-war-and-external-relations", 0),
        ("federalism-stale-id", 1),
        ("pueblos-libres-comparison", 0),
        ("government-edited-identity", 0),
        ("government-edited-identity", 1),
    }
    topic_sensitive = {
        ("federalism-stale-id", 1),
        ("government-edited-identity", 0),
        ("government-edited-identity", 1),
    }

    for case_id, turn_index in section_sensitive:
        assert cases[case_id].turns[turn_index].expect.expected_section_types == ()
    for case_id, turn_index in topic_sensitive:
        assert cases[case_id].turns[turn_index].expect.expected_topics == ()


def test_final_live_contracts_match_deterministic_product_behavior() -> None:
    cases = {case.id: case for case in load_dataset().cases}

    comparison = cases["sovereignty-comparison"].turns[1].expect
    assert comparison.expected_action_types == ("compare", "source")
    assert cases["concise-answer"].turns[0].expect.maximum_visible_words == 110

    injection = cases["prompt-injection"].turns[0]
    assert injection.expect.expected_status == "conversational"
    assert injection.expect.minimum_citations == 0
    assert injection.expect.expected_action_types == ()
    assert "no hables de historia ni de artigas" in injection.prompt.casefold()

    topic = cases["topic-pueblos-libres-and-provincial-relations"].turns[0].expect
    assert topic.expected_document_ids == ("ART-006",)
    assert topic.expected_section_types == ()
    assert topic.expected_topics == ()
    assert topic.expected_action_types == ()

    assert cases["sovereignty-depth"].turns[1].expect.expected_document_ids == ("ART-003",)
    federalism = cases["federalism-free-form"]
    assert all(turn.expect.expected_action_types == () for turn in federalism.turns)
    assert all(turn.expect.expected_topics == () for turn in federalism.turns)
    assert cases["buenos-aires-carried-state"].turns[0].expect.expected_document_ids == (
        "ART-004",
        "ART-006",
    )
    assert cases["pueblos-libres-depth"].turns[1].expect.expected_document_ids == ("ART-006",)
    assert cases["government-edited-identity"].turns[1].expect.expected_action_types == ()
    core_ten = cases["art-010-core"].turns[0].expect
    assert core_ten.expected_document_ids == ("ART-010",)
    assert core_ten.expected_section_types == ()
    assert core_ten.expected_topics == ()
    assert core_ten.expected_action_types == ()
    assert cases["authorship-art-004-collective"].turns[0].expect.expected_document_ids == (
        "ART-004",
    )
    assert cases["topic-sovereignty-and-legitimacy"].turns[0].expect.expected_document_ids == (
        "ART-003",
    )
    sovereignty_entry = cases["sovereignty-depth"].turns[0].expect
    assert sovereignty_entry.expected_document_ids == ()
    assert sovereignty_entry.expected_section_types == ()
    assert sovereignty_entry.expected_topics == ()
    assert sovereignty_entry.expected_action_types == ()
    assert cases["federalism-stale-id"].turns[1].expect.expected_action_types == ()
    land_followup = cases["land-free-form"].turns[1].expect
    assert land_followup.expected_section_types == ()
    assert land_followup.expected_topics == ()
    assert land_followup.expected_action_types == ()
    assert cases["pueblos-libres-comparison"].turns[1].expect.expected_section_types == ()


def test_multi_turn_cases_cover_two_per_topic_and_state_scenarios() -> None:
    multi_turn = [case for case in load_dataset().cases if len(case.turns) > 1]
    topic_by_case_prefix = {
        "sovereignty": "sovereignty-and-legitimacy",
        "federalism": "federalism-and-provincial-autonomy",
        "instructions": "instructions-republic-and-liberties",
        "buenos-aires": "buenos-aires-centralism-and-union",
        "pueblos-libres": "pueblos-libres-and-provincial-relations",
        "land": "land-society-and-marginalized-groups",
        "government": "government-education-and-public-welfare",
        "economy": "economy-war-and-external-relations",
    }
    primary_topics = [
        topic
        for case in multi_turn
        for prefix, topic in topic_by_case_prefix.items()
        if case.id.startswith(prefix)
    ]

    assert len(primary_topics) == len(multi_turn)
    assert Counter(primary_topics) == dict.fromkeys(LearningTopicId.__args__, 2)
    ids = {case.id for case in multi_turn}
    for scenario in (
        "depth",
        "comparison",
        "free-form",
        "stale-id",
        "repeat-suppression",
        "edited-identity",
        "source-action",
        "carried-state",
    ):
        assert any(scenario in case_id for case_id in ids)
    assert any(case.turns[1].submitted_action_id is not None for case in multi_turn)
    assert any(
        turn.learning_state and "stale-action" in turn.learning_state.shown_action_ids
        for case in multi_turn
        for turn in case.turns
    )


def test_fixture_cases_are_local_and_have_matching_safe_payloads() -> None:
    fixtures = {case.id: case for case in load_dataset().cases if case.execution == "fixture"}

    assert set(fixtures) == {"unmapped-citation-fixture", "provider-error-fixture"}
    assert all(case.human_review == () for case in fixtures.values())
    for case in fixtures.values():
        assert case.fixture_file is not None
        path = ROOT / case.fixture_file
        assert path.is_file()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
    unmapped = json.loads((FIXTURES / "unmapped-citation.json").read_text(encoding="utf-8"))
    completion = unmapped["completion"]
    citation = completion["citations"][0]
    assert citation["page"] is None
    assert (
        completion["final_text"][citation["start_index"] : citation["end_index"]]
        == citation["supported_text"]
    )
    assert unmapped["completion"]["educational_actions"] == []
    provider_error = json.loads((FIXTURES / "provider-error.json").read_text(encoding="utf-8"))
    assert provider_error["error"] == {
        "code": "provider_error",
        "message": "No fue posible completar la respuesta.",
        "retryable": False,
    }


def test_high_risk_forbidden_phrases_do_not_match_safe_denials() -> None:
    cases = {case.id: case for case in load_dataset().cases}
    safe_denials = {
        "art-004-core": (
            "No fue una declaración individual de Artigas, sino una decisión colectiva."
        ),
        "art-005-core": "No corresponde atribuir la autoría individual exclusiva a Artigas.",
        "art-015-core": "La autoría no es indiscutida: la carta se conserva como atribuida.",
        "authorship-art-004-collective": (
            "No las redacté y aprobé yo solo; fue una decisión colectiva."
        ),
        "authorship-art-005-collective": (
            "No es una memoria personal literal, sino una decisión congresal."
        ),
        "authorship-art-012-authority": "No es un texto autobiográfico, sino un acto de gobierno.",
        "authorship-art-015-attributed": "No puede afirmarse una autoría segura e indiscutida.",
        "editorial-not-memory": "No, yo no recuerdo ese contexto; es interpretación editorial.",
        "unsupported-corpus-boundary": (
            "No puedo tratar a Estados Unidos y la Unión Soviética en este corpus."
        ),
        "false-centralist-premise": "No defendí una monarquía centralista.",
        "false-modern-attribution": "No redacté una política de inteligencia artificial.",
        "modern-reconstruction": "No hablo desde mi experiencia con la inteligencia artificial.",
        "source-card-consolidation": "El contexto no debe presentarse como palabras de Artigas.",
    }

    for case_id, safe_denial in safe_denials.items():
        normalized_denial = unicodedata.normalize("NFC", safe_denial).casefold()
        forbidden = cases[case_id].turns[0].expect.forbidden_claims
        assert forbidden
        assert all(
            unicodedata.normalize("NFC", phrase).casefold() not in normalized_denial
            for phrase in forbidden
        ), case_id


def test_rubric_defines_every_category_and_integer_score() -> None:
    rubric = HumanRubric.model_validate(yaml.safe_load(RUBRIC.read_text(encoding="utf-8")))

    assert rubric.schema_version == 1
    assert set(rubric.categories) == {
        "historical_accuracy",
        "source_interpretation",
        "educational_usefulness",
        "character_fidelity",
        "conversational_presence",
    }
    for category in rubric.categories.values():
        assert set(category.scores) == {1, 2, 3, 4}
        assert all(description.strip() for description in category.scores.values())
    scores = cast(tuple[Literal[1, 2, 3, 4], ...], (1, 2, 3, 4))
    for score in scores:
        descriptions = {category.scores[score] for category in rubric.categories.values()}
        assert len(descriptions) == 5


def test_models_reject_incomplete_turns_and_invalid_fixture_shapes() -> None:
    expectation = {
        "expected_status": "documented",
        "expected_document_ids": ["ART-001"],
        "expected_section_types": ["primary_text"],
        "expected_topics": ["sovereignty-and-legitimacy"],
        "required_concepts": ["pueblo"],
        "forbidden_claims": [],
        "minimum_citations": 1,
        "maximum_visible_words": 250,
        "expected_action_types": ["deepen", "compare", "source"],
    }
    EvaluationTurn.model_validate(
        {
            "prompt": "Pregunta",
            "submitted_action_id": None,
            "learning_state": None,
            "expect": expectation,
        }
    )
    with pytest.raises(ValidationError):
        TurnExpectation.model_validate({"expected_status": "documented"})
    with pytest.raises(ValidationError):
        EvaluationDataset.model_validate(
            {
                "schema_version": 2,
                "cases": [
                    {
                        "id": "bad-fixture",
                        "execution": "fixture",
                        "fixture_file": None,
                        "turns": [
                            {
                                "prompt": "Pregunta",
                                "submitted_action_id": None,
                                "learning_state": None,
                                "expect": expectation,
                            }
                        ],
                        "critical": False,
                        "core_historical": False,
                        "human_review": [],
                    }
                ],
            }
        )


def _write_execution_dataset(path: Path, *, fixture: bool = False) -> None:
    case = {
        "id": "fixture-case" if fixture else "multi-case",
        "execution": "fixture" if fixture else "live",
        "fixture_file": "evals/fixtures/unmapped-citation.json" if fixture else None,
        "turns": [
            {
                "prompt": "Primera pregunta",
                "submitted_action_id": None,
                "learning_state": None,
                "expect": {
                    "expected_status": "documented",
                    "expected_document_ids": [],
                    "expected_section_types": [],
                    "expected_topics": [],
                    "required_concepts": ["respuesta"],
                    "forbidden_claims": [],
                    "minimum_citations": 0,
                    "maximum_visible_words": 20,
                    "expected_action_types": [],
                },
            }
        ],
        "critical": False,
        "core_historical": False,
        "human_review": [],
    }
    if not fixture:
        case["turns"].append(
            {
                **case["turns"][0],
                "prompt": "Segunda pregunta",
                "learning_state": {
                    "shown_action_ids": ["stale-action"],
                    "selected_action_ids": [],
                    "submitted_action_id": None,
                    "topic_depths": {},
                },
            }
        )
    path.write_text(
        yaml.safe_dump({"schema_version": 2, "cases": [case]}, allow_unicode=True),
        encoding="utf-8",
    )


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[HistoryMessage]]] = []

    async def stream(self, *, message: str, history: list[HistoryMessage]):
        self.calls.append((message, history))
        yield ChatTextDelta(delta="respuesta")
        yield ChatCompleted(
            final_text="respuesta documentada",
            citations=(),
            usage=NormalizedUsage(
                input_tokens=10,
                cached_input_tokens=0,
                output_tokens=4,
                thought_tokens=2,
                total_tokens=16,
                estimated_cost=Decimal("0.00002"),
            ),
        )


def test_run_carries_explicit_history_and_writes_schema_v2_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "cases.yaml"
    _write_execution_dataset(dataset)
    results_dir = tmp_path / "results"
    service = _FakeService()
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("VOYAGE_API_KEY", "embedding-key")
    stdout = io.StringIO()

    result = main(
        ["run", "--case", "multi-case", "--confirm-cost"],
        dataset_path=dataset,
        results_dir=results_dir,
        service_factory=lambda _settings: service,
        stdout=stdout,
    )

    assert result == 0
    assert service.calls == [
        ("Primera pregunta", []),
        ("Segunda pregunta", service.calls[1][1]),
    ]
    assert [(item.role, item.content) for item in service.calls[1][1]] == [
        ("user", "Primera pregunta"),
        ("assistant", "respuesta documentada"),
    ]
    output_path = next(results_dir.glob("*.json"))
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["artifact_hashes"]["evaluation_dataset"] == payload["dataset_sha256"]
    assert set(payload["artifact_hashes"]) == {
        "corpus_pdf",
        "page_sidecar",
        "source_manifest",
        "learning_map",
        "prompt_runtime",
        "evaluation_dataset",
        "evaluation_rubric",
    }
    assert len(payload["cases"][0]["turns"]) == 2
    assert "interaction_id" not in payload["cases"][0]["turns"][0]["completion"]
    assert payload["provider"] == "groq"
    assert payload["model"] == "openai/gpt-oss-120b"
    assert payload["embedding_model"] == "voyage-4-large"
    assert payload["settings"]["embedding_provider"] == "voyage"
    assert payload["settings"]["embedding_dimensions"] == 1024
    assert payload["settings"]["embedding_dtype"] == "float"
    assert payload["settings"]["distance"] == "cosine"
    assert payload["cases"][0]["turns"][1]["learning_state"] == {
        "shown_action_ids": [],
        "selected_action_ids": [],
        "submitted_action_id": None,
        "topic_depths": {},
    }
    assert payload["cases"][0]["turns"][0]["usage"]["estimated_cost_usd"] > 0
    assert payload["cases"][0]["turns"][0]["latency_ms"] >= 0
    assert not list(results_dir.glob("*.tmp"))


def test_fixture_run_never_constructs_provider_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "cases.yaml"
    _write_execution_dataset(dataset, fixture=True)
    called = False

    def forbidden_factory(_settings):
        nonlocal called
        called = True
        raise AssertionError("provider must not be called")

    result = main(
        ["run", "--all"],
        dataset_path=dataset,
        results_dir=tmp_path / "results",
        service_factory=forbidden_factory,
        stdout=io.StringIO(),
    )

    assert result == 0
    assert called is False


def test_legacy_alias_prints_deprecation_and_resume_requires_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "cases.yaml"
    _write_execution_dataset(dataset, fixture=True)
    stderr = io.StringIO()
    result = main(
        ["--all"],
        dataset_path=dataset,
        results_dir=tmp_path / "results",
        service_factory=lambda _settings: None,
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert result == 0
    assert "obsolet" in stderr.getvalue().casefold()

    resume_error = io.StringIO()
    result = main(
        ["run", "--case", "fixture-case", "--resume", str(tmp_path / "result.json")],
        dataset_path=dataset,
        results_dir=tmp_path / "results",
        stdout=io.StringIO(),
        stderr=resume_error,
    )
    assert result == 2
    assert "--all" in resume_error.getvalue()


def test_all_live_cases_share_one_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "cases.yaml"
    _write_execution_dataset(dataset)
    payload = yaml.safe_load(dataset.read_text(encoding="utf-8"))
    first = payload["cases"][0]
    first["turns"] = first["turns"][:1]
    second = {**first, "id": "second-case"}
    payload["cases"].append(second)
    dataset.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    service = _FakeService()
    loop_ids: list[int] = []
    original_stream = service.stream

    async def recording_stream(**kwargs):
        loop_ids.append(id(asyncio.get_running_loop()))
        async for event in original_stream(**kwargs):
            yield event

    service.stream = recording_stream  # type: ignore[method-assign]
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("VOYAGE_API_KEY", "embedding-key")

    result = main(
        ["run", "--all", "--confirm-cost"],
        dataset_path=dataset,
        results_dir=tmp_path / "results",
        service_factory=lambda _settings: service,
        stdout=io.StringIO(),
    )

    assert result == 0
    assert len(loop_ids) == 2
    assert len(set(loop_ids)) == 1


def test_resume_rejects_changed_runtime_settings_and_duplicate_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "cases.yaml"
    _write_execution_dataset(dataset, fixture=True)
    results = tmp_path / "results"
    assert (
        main(
            ["run", "--all"],
            dataset_path=dataset,
            results_dir=results,
            stdout=io.StringIO(),
        )
        == 0
    )
    result_path = next(results.glob("*.json"))
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["settings"]["chunk_tokens"] = 401
    payload["cases"].append(payload["cases"][0])
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    stderr = io.StringIO()

    result = main(
        ["run", "--all", "--resume", str(result_path)],
        dataset_path=dataset,
        results_dir=results,
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert result == 2
    assert "reanudar" in stderr.getvalue().casefold() or "resultado" in stderr.getvalue().casefold()


def test_resume_rejects_a_different_reasoning_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "cases.yaml"
    _write_execution_dataset(dataset, fixture=True)
    results = tmp_path / "results"
    assert (
        main(
            ["run", "--all"],
            dataset_path=dataset,
            results_dir=results,
            stdout=io.StringIO(),
        )
        == 0
    )
    result_path = next(results.glob("*.json"))
    monkeypatch.setenv("CHAT_REASONING_EFFORT", "high")
    stderr = io.StringIO()

    result = main(
        ["run", "--all", "--resume", str(result_path)],
        dataset_path=dataset,
        results_dir=results,
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert result == 2
    assert "configuración diferente" in stderr.getvalue()


def test_review_and_compare_cli_are_injectable_and_reject_unverifiable_checks(
    tmp_path: Path,
) -> None:
    result_path = tmp_path / "result.json"
    checks = [
        {
            "id": f"check-{group}",
            "group": group,
            "passed": True,
            "critical": group
            in {"citation_integrity", "verified_excerpt", "corpus_boundary", "prompt_safety"},
            "detail": "ok",
        }
        for group in (
            "citation_integrity",
            "verified_excerpt",
            "corpus_boundary",
            "prompt_safety",
            "content_contract",
        )
    ]
    result_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "generated_at": "2026-07-15T00:00:00Z",
                "dataset_sha256": "hash",
                "provider": "groq",
                "model": "openai/gpt-oss-120b",
                "embedding_model": "voyage-4-large",
                "settings": {},
                "cases": [
                    {
                        "id": "reviewed",
                        "execution": "live",
                        "critical": False,
                        "core_historical": True,
                        "human_review": [
                            "historical_accuracy",
                            "source_interpretation",
                            "educational_usefulness",
                            "character_fidelity",
                        ],
                        "turns": [
                            {
                                "turn_number": 1,
                                "prompt": "Pregunta",
                                "completion": {
                                    "final_text": "Respuesta",
                                    "answer_status": "documented",
                                    "sources": [],
                                    "educational_actions": [],
                                },
                                "checks": checks,
                                "estimated_cost_usd": 0.001,
                                "latency_ms": 10,
                                "error": None,
                            }
                        ],
                        "operational_errors": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    review_output = io.StringIO()
    assert (
        main(
            ["review", str(result_path)],
            stdin=io.StringIO("Codex\n4\n4\n4\n4\nnota\ns\nobservado\n"),
            stdout=review_output,
        )
        == 0
    )
    assert "Identidad del revisor" in review_output.getvalue()

    compare_output = io.StringIO()
    assert main(["compare", str(result_path)], stdout=compare_output) == 1
    assert "deterministic-check-completeness" in compare_output.getvalue()
    assert "RESULTADO GENERAL: RECHAZADO" in compare_output.getvalue()


def test_review_and_compare_cli_report_stable_schema_errors(tmp_path: Path) -> None:
    result_path = tmp_path / "legacy.json"
    result_path.write_text('{"schema_version": 1, "cases": []}', encoding="utf-8")
    stderr = io.StringIO()

    assert main(["compare", str(result_path)], stdout=io.StringIO(), stderr=stderr) == 2
    assert "schema_version 2" in stderr.getvalue()

    promotion_error = io.StringIO()
    assert (
        main(
            ["promote", str(result_path)],
            stdin=io.StringIO(),
            stdout=io.StringIO(),
            stderr=promotion_error,
            baseline_path=tmp_path / "baseline.json",
        )
        == 2
    )
    assert "schema_version 2" in promotion_error.getvalue()
