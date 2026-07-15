from __future__ import annotations

import io
import json
from functools import lru_cache
from pathlib import Path
from typing import cast

import pytest

from artigas_mvp_backend.corpus import CorpusPaths
from artigas_mvp_backend.evaluation_checks import run_turn_checks
from artigas_mvp_backend.evaluation_models import TurnExpectation
from artigas_mvp_backend.evaluation_review import (
    EvaluationReviewError,
    compare_result,
    nearest_rank_percentile,
    review_result,
)
from artigas_mvp_backend.models import CompleteEventData, LearningState
from artigas_mvp_backend.services.corpus import CorpusService

CATEGORIES = [
    "historical_accuracy",
    "source_interpretation",
    "educational_usefulness",
    "character_fidelity",
]
CHECK_GROUPS = {
    "citation-numbering": "citation_integrity",
    "citation-source-grouping": "citation_integrity",
    "minimum-citations": "citation_integrity",
    "citation-offsets": "citation_integrity",
    "verified-excerpts": "verified_excerpt",
    "expected-documents": "corpus_boundary",
    "expected-section-types": "corpus_boundary",
    "expected-learning-topics": "corpus_boundary",
    "pdf-urls": "corpus_boundary",
    "forbidden-claims": "prompt_safety",
    "generated-quotation-punctuation": "prompt_safety",
    "answer-status": "content_contract",
    "answer-opening": "content_contract",
    "required-concepts": "content_contract",
    "visible-word-count": "content_contract",
    "educational-action-types": "education_contract",
    "learning-state-contract": "education_contract",
    "learning-depth-progression": "education_contract",
    "usage-observation": "performance_observation",
}
ACTION_ID = "sl-04-deeper-condiciones"


@lru_cache(maxsize=1)
def _corpus() -> CorpusService:
    return CorpusService.load(CorpusPaths.repository_defaults())


def _check(
    check_id: str,
    group: str,
    *,
    passed: bool = True,
    critical: bool = False,
) -> dict[str, object]:
    return {
        "id": check_id,
        "group": group,
        "passed": passed,
        "critical": critical,
        "detail": f"detail for {check_id}",
    }


def _case(
    case_id: str,
    *,
    human_review: list[str] | None = None,
    critical: bool = False,
    core_historical: bool = False,
    execution: str = "live",
    checks: list[dict[str, object]] | None = None,
    operational_errors: list[dict[str, object]] | None = None,
    cost: float = 1.0,
    latency: int = 100,
) -> dict[str, object]:
    completion = {
        "interaction_id": f"interaction-{case_id}",
        "final_text": f"Respuesta con Fragmento verificado para {case_id}",
        "answer_status": "documented",
        "citations": [
            {
                "number": 1,
                "title": "Referencia",
                "page": 26,
                "supported_text": "Fragmento verificado",
                "start_index": 14,
                "end_index": 34,
            }
        ],
        "sources": [
            {
                "document_id": "ART-001",
                "id": "source-1",
                "citation_numbers": [1],
                "title": "Documento",
                "date": None,
                "document_type": None,
                "authorship_classification": None,
                "relationship_to_artigas": None,
                "pages": [26],
                "pdf_url": "/api/corpus/artigas#page=26",
                "evidence_blocks": [
                    {
                        "id": "block-1",
                        "citation_numbers": [1],
                        "section_id": "ART-001-primary",
                        "evidence_type": None,
                        "page": 26,
                        "excerpt_id": None,
                        "excerpt": None,
                        "supported_text": "Fragmento verificado",
                        "learning_topic_ids": [],
                    }
                ],
            }
        ],
        "educational_actions": [
            {
                "type": "deepen",
                "label": "Profundizar",
                "action_id": ACTION_ID,
                "question": "¿Cómo se expresa la legitimidad?",
                "url": None,
            }
        ],
        "learning_state": {
            "shown_action_ids": [ACTION_ID],
            "selected_action_ids": [],
            "submitted_action_id": None,
            "topic_depths": {},
        },
        "usage": {
            "input_tokens": 10,
            "cached_input_tokens": 0,
            "output_tokens": 10,
            "thought_tokens": 0,
            "total_tokens": 20,
            "estimated_cost_usd": cost,
        },
    }
    result = {
        "id": case_id,
        "execution": execution,
        "critical": critical,
        "core_historical": core_historical,
        "human_review": CATEGORIES if human_review is None else human_review,
        "turns": [
            {
                "turn_number": 1,
                "prompt": f"Prompt for {case_id}",
                "submitted_action_id": None,
                "learning_state": {
                    "shown_action_ids": [],
                    "selected_action_ids": [],
                    "submitted_action_id": None,
                    "topic_depths": {},
                },
                "expect": {
                    "expected_status": "documented",
                    "expected_document_ids": [],
                    "expected_section_types": [],
                    "expected_topics": [],
                    "required_concepts": ["Fragmento verificado"],
                    "forbidden_claims": [],
                    "minimum_citations": 1,
                    "maximum_visible_words": 20,
                    "expected_action_types": ["deepen"],
                },
                "completion": completion,
                "checks": checks
                if checks is not None
                else [
                    _check(
                        check_id,
                        group,
                        critical=critical
                        or group
                        in {
                            "citation_integrity",
                            "verified_excerpt",
                            "corpus_boundary",
                            "prompt_safety",
                        },
                    )
                    for check_id, group in CHECK_GROUPS.items()
                ],
                "estimated_cost_usd": cost,
                "latency_ms": latency,
                "error": None,
            }
        ],
        "operational_errors": operational_errors or [],
    }
    if checks is None:
        turn = result["turns"][0]
        recomputed = run_turn_checks(
            CompleteEventData.model_validate(turn["completion"]),
            TurnExpectation.model_validate(turn["expect"]),
            corpus=_corpus(),
            case_critical=critical,
            input_state=LearningState.model_validate(turn["learning_state"]),
            submitted_action_id=None,
        )
        turn["checks"] = [check.model_dump(mode="json") for check in recomputed]
    return result


def _result(*cases: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "generated_at": "2026-07-15T00:00:00Z",
        "dataset_sha256": "dataset-hash",
        "model": "gemini-3.5-flash",
        "settings": {},
        "cases": list(cases),
    }


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_review_persists_each_case_and_resumes_without_reasking_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "result.json"
    _write(path, _result(_case("first"), _case("second")))
    writes: list[int] = []
    from artigas_mvp_backend import evaluation_review

    real_write = evaluation_review._atomic_write_json

    def recording_write(target: Path, payload: dict[str, object]) -> None:
        writes.append(len(payload.get("review", {}).get("cases", {})))  # type: ignore[union-attr]
        real_write(target, payload)

    monkeypatch.setattr(evaluation_review, "_atomic_write_json", recording_write)
    first_input = io.StringIO("Codex\n4\n4\n4\n4\nPrimera nota\n")

    with pytest.raises(EvaluationReviewError, match="interrumpida"):
        review_result(path, stdin=first_input, stdout=io.StringIO())

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["review"]["reviewer"] == "Codex"
    assert set(saved["review"]["cases"]) == {"first"}
    assert writes[-1] == 1

    output = io.StringIO()
    resumed_input = io.StringIO("4\n4\n4\n4\nSegunda nota\ns\nSin observaciones.\n")
    review_result(path, stdin=resumed_input, stdout=output)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["review"]["reviewer"] == "Codex"
    assert set(saved["review"]["cases"]) == {"first", "second"}
    assert saved["review"]["performance"] == {
        "acknowledged": True,
        "notes": "Sin observaciones.",
        "cost_regression_explanation": "",
        "latency_regression_explanation": "",
    }
    assert "Prompt for second" in output.getvalue()
    assert "Respuesta con Fragmento verificado para second" in output.getvalue()
    assert "ART-001" in output.getvalue()
    assert "Fragmento verificado" in output.getvalue()
    assert '"page": 26' in output.getvalue()
    assert ACTION_ID in output.getvalue()
    assert "first" not in resumed_input.getvalue()


def test_review_validates_scores_displays_failures_and_skips_fixture_cases(
    tmp_path: Path,
) -> None:
    path = tmp_path / "result.json"
    failed = _check("bad-boundary", "corpus_boundary", passed=False, critical=True)
    live_case = _case("live", checks=[failed])
    live_case["turns"][0]["completion"]["final_text"] = "\x1b[2JRespuesta segura"  # type: ignore[index]
    _write(
        path,
        _result(
            live_case,
            _case("fixture", execution="fixture", human_review=[]),
        ),
    )
    output = io.StringIO()
    review_result(
        path,
        stdin=io.StringIO("Codex\n0\n5\nx\n4\n3\n2\n1\nnota\ns\nrevisado\n"),
        stdout=output,
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["review"]["cases"]["live"]["scores"] == dict(
        zip(CATEGORIES, [4, 3, 2, 1], strict=True)
    )
    assert "fixture" not in saved["review"]["cases"]
    assert output.getvalue().count("Ingrese un número entre 1 y 4") == 3
    assert "bad-boundary" in output.getvalue()
    assert "detail for bad-boundary" in output.getvalue()
    assert "No contiene errores materiales" in output.getvalue()
    assert "\x1b" not in output.getvalue()
    assert "Respuesta segura" in output.getvalue()


def test_review_rejects_old_schema_and_incomplete_case_results(tmp_path: Path) -> None:
    old = tmp_path / "old.json"
    _write(old, {"schema_version": 1, "cases": []})
    with pytest.raises(EvaluationReviewError, match="schema_version 2"):
        review_result(old, stdin=io.StringIO(), stdout=io.StringIO())

    incomplete = tmp_path / "incomplete.json"
    case = _case("broken")
    case["turns"] = []
    _write(incomplete, _result(case))
    with pytest.raises(EvaluationReviewError, match="incompleto"):
        review_result(incomplete, stdin=io.StringIO(), stdout=io.StringIO())


def test_review_repairs_partial_case_and_unacknowledged_performance(tmp_path: Path) -> None:
    path = tmp_path / "partial.json"
    payload = _result(_case("case"))
    payload["review"] = {
        "reviewer": "Codex",
        "cases": {
            "case": {
                "scores": {"historical_accuracy": 4},
                "notes": "parcial",
                "reviewed_at": "2026-07-15T00:00:00Z",
            }
        },
        "performance": {
            "acknowledged": False,
            "notes": "pendiente",
            "cost_regression_explanation": "",
            "latency_regression_explanation": "",
        },
    }
    _write(path, payload)

    review_result(
        path,
        stdin=io.StringIO("4\n4\n4\n4\nrevisado\ns\naceptado\n"),
        stdout=io.StringIO(),
    )

    saved = json.loads(path.read_text(encoding="utf-8"))["review"]
    assert saved["cases"]["case"]["scores"] == dict.fromkeys(CATEGORIES, 4)
    assert saved["performance"]["acknowledged"] is True


def test_nearest_rank_and_review_performance_summary(tmp_path: Path) -> None:
    assert nearest_rank_percentile([1, 2, 3, 100], 0.95) == 100
    assert nearest_rank_percentile([4, 1, 3, 2], 0.5) == 2

    path = tmp_path / "result.json"
    fixture_cases = [
        _case(
            f"fixture-{number}",
            execution="fixture",
            human_review=[],
            cost=float(number),
            latency=number * 10,
        )
        for number in range(1, 5)
    ]
    _write(path, _result(*fixture_cases))
    output = io.StringIO()
    review_result(
        path,
        stdin=io.StringIO("Codex\ns\nobservado\n"),
        stdout=output,
    )
    text = output.getvalue()
    assert "Mediana costo: 2.500000 USD" in text
    assert "p95 costo: 4.000000 USD" in text
    assert "Mediana latencia: 25.00 ms" in text
    assert "p95 latencia: 40.00 ms" in text


def _reviewed_result(
    *cases: dict[str, object],
    score: int = 4,
    acknowledged: bool = True,
    cost_explanation: str = "",
    latency_explanation: str = "",
) -> dict[str, object]:
    payload = _result(*cases)
    payload["review"] = {
        "reviewer": "Codex",
        "cases": {
            case["id"]: {
                "scores": dict.fromkeys(cast(list[str], case["human_review"]), score),
                "notes": "",
                "reviewed_at": "2026-07-15T00:00:00Z",
            }
            for case in cases
            if case["human_review"]
        },
        "performance": {
            "acknowledged": acknowledged,
            "notes": "",
            "cost_regression_explanation": cost_explanation,
            "latency_regression_explanation": latency_explanation,
        },
    }
    return payload


def test_compare_reports_every_gate_and_is_read_only(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    payload = _reviewed_result(_case("passing", core_historical=True))
    _write(path, payload)
    before = path.read_bytes()
    output = io.StringIO()

    report = compare_result(path, stdout=output, expected_case_ids=("passing",))

    assert report.passed is True
    assert path.read_bytes() == before
    assert {rule.id for rule in report.rules} == {
        "citation-integrity",
        "verified-excerpts",
        "corpus-boundary",
        "prompt-safety",
        "remaining-deterministic",
        "rubric-category-averages",
        "core-historical-no-score-one",
        "critical-cases",
        "human-scores-complete",
        "performance-acknowledged",
        "cost-regression-explained",
        "latency-regression-explained",
        "operational-errors",
        "deterministic-check-completeness",
        "case-matrix-complete",
    }
    assert "RESULTADO GENERAL: APROBADO" in output.getvalue()


@pytest.mark.parametrize(
    ("mutation", "failed_rule"),
    [
        ("critical-group", "citation-integrity"),
        ("remaining-rate", "remaining-deterministic"),
        ("category-average", "rubric-category-averages"),
        ("core-one", "core-historical-no-score-one"),
        ("critical-case", "critical-cases"),
        ("missing-score", "human-scores-complete"),
        ("no-ack", "performance-acknowledged"),
        ("provider-error", "operational-errors"),
        ("missing-check", "deterministic-check-completeness"),
    ],
)
def test_compare_enforces_each_quality_failure(
    tmp_path: Path, mutation: str, failed_rule: str
) -> None:
    checks = [
        _check("citation", "citation_integrity", critical=True),
        _check("excerpt", "verified_excerpt", critical=True),
        _check("boundary", "corpus_boundary", critical=True),
        _check("safety", "prompt_safety", critical=True),
        *[_check(f"remaining-{number}", "content_contract") for number in range(10)],
    ]
    case = _case("case", checks=checks, critical=mutation == "critical-case", core_historical=True)
    payload = _reviewed_result(case)
    if mutation == "critical-group":
        checks[0]["passed"] = False
    elif mutation == "remaining-rate":
        checks[-1]["passed"] = False
        checks[-2]["passed"] = False
    elif mutation == "category-average":
        payload["review"]["cases"]["case"]["scores"]["historical_accuracy"] = 3  # type: ignore[index]
    elif mutation == "core-one":
        payload["review"]["cases"]["case"]["scores"]["character_fidelity"] = 1  # type: ignore[index]
    elif mutation == "critical-case":
        checks[-1]["passed"] = False
    elif mutation == "missing-score":
        del payload["review"]["cases"]["case"]["scores"]["character_fidelity"]  # type: ignore[index]
    elif mutation == "no-ack":
        payload["review"]["performance"]["acknowledged"] = False  # type: ignore[index]
    elif mutation == "provider-error":
        case["operational_errors"] = [{"code": "provider_error"}]
    elif mutation == "missing-check":
        checks.pop()
    path = tmp_path / f"{mutation}.json"
    _write(path, payload)

    report = compare_result(path, stdout=io.StringIO(), expected_case_ids=("case",))

    assert report.passed is False
    assert next(rule for rule in report.rules if rule.id == failed_rule).passed is False


def test_compare_requires_explanations_for_p95_regressions_above_fifteen_percent(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.json"
    _write(
        baseline,
        {
            "schema_version": 1,
            "summary": {"p95_cost_usd": 1.0, "p95_latency_ms": 100.0},
        },
    )
    result = tmp_path / "result.json"
    _write(result, _reviewed_result(_case("case", cost=1.16, latency=116)))

    report = compare_result(
        result,
        baseline_path=baseline,
        stdout=io.StringIO(),
        expected_case_ids=("case",),
    )
    cost_rule = next(rule for rule in report.rules if rule.id == "cost-regression-explained")
    assert cost_rule.passed is False
    assert (
        next(rule for rule in report.rules if rule.id == "latency-regression-explained").passed
        is False
    )

    payload = json.loads(result.read_text(encoding="utf-8"))
    payload["review"]["performance"]["cost_regression_explanation"] = "Revisado."
    payload["review"]["performance"]["latency_regression_explanation"] = "Revisado."
    _write(result, payload)
    assert (
        compare_result(
            result,
            baseline_path=baseline,
            stdout=io.StringIO(),
            expected_case_ids=("case",),
        ).passed
        is True
    )


def test_review_requires_nonempty_explanations_for_material_regressions(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write(
        baseline,
        {
            "schema_version": 1,
            "summary": {"p95_cost_usd": 1.0, "p95_latency_ms": 100.0},
        },
    )
    result = tmp_path / "result.json"
    _write(result, _result(_case("case", cost=1.16, latency=116)))
    output = io.StringIO()

    review_result(
        result,
        baseline_path=baseline,
        stdin=io.StringIO(
            "Codex\n4\n4\n4\n4\nnota\ns\nobservado\n\nCosto aceptado.\n\nLatencia aceptada.\n"
        ),
        stdout=output,
    )

    performance = json.loads(result.read_text(encoding="utf-8"))["review"]["performance"]
    assert performance["cost_regression_explanation"] == "Costo aceptado."
    assert performance["latency_regression_explanation"] == "Latencia aceptada."
    assert output.getvalue().count("La explicación no puede estar vacía") == 2


def test_review_reopens_performance_when_a_new_baseline_requires_explanations(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.json"
    _write(
        baseline,
        {
            "schema_version": 1,
            "summary": {"p95_cost_usd": 1.0, "p95_latency_ms": 100.0},
        },
    )
    result = tmp_path / "result.json"
    payload = _reviewed_result(_case("case", cost=1.16, latency=116))
    _write(result, payload)

    review_result(
        result,
        baseline_path=baseline,
        stdin=io.StringIO("s\nreabierto\nCosto explicado.\nLatencia explicada.\n"),
        stdout=io.StringIO(),
    )

    performance = json.loads(result.read_text(encoding="utf-8"))["review"]["performance"]
    assert performance["cost_regression_explanation"] == "Costo explicado."
    assert performance["latency_regression_explanation"] == "Latencia explicada."


def test_compare_rejects_tampered_deterministic_detail(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    payload = _reviewed_result(_case("case"))
    payload["cases"][0]["turns"][0]["checks"][0]["detail"] = "Detalle adulterado"  # type: ignore[index]
    _write(result, payload)

    report = compare_result(result, stdout=io.StringIO(), expected_case_ids=("case",))

    completeness = next(
        rule for rule in report.rules if rule.id == "deterministic-check-completeness"
    )
    assert completeness.passed is False


def test_compare_rejects_a_passing_subset_of_the_current_case_matrix(tmp_path: Path) -> None:
    result = tmp_path / "subset.json"
    _write(result, _reviewed_result(_case("passing-subset")))

    report = compare_result(result, stdout=io.StringIO())

    matrix = next(rule for rule in report.rules if rule.id == "case-matrix-complete")
    assert matrix.passed is False
    assert report.passed is False
