"""Resumable human review and read-only quality-gate comparison."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, TextIO

import yaml
from pydantic import ValidationError

from artigas_mvp_backend.corpus import CorpusPaths
from artigas_mvp_backend.evaluation_checks import (
    QualityGateReport,
    evaluate_quality_gate,
    run_turn_checks,
)
from artigas_mvp_backend.evaluation_models import (
    HumanRubric,
    RubricCategoryDefinition,
    TurnExpectation,
)
from artigas_mvp_backend.models import CompleteEventData, LearningState
from artigas_mvp_backend.services.corpus import CorpusService

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUBRIC = REPOSITORY_ROOT / "evals" / "rubric.yaml"
DEFAULT_DATASET = REPOSITORY_ROOT / "evals" / "artigas-cases.yaml"
_ANSI_ESCAPE = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])")
_UNSAFE_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


class EvaluationReviewError(Exception):
    """Raised for invalid, incomplete, or interrupted review data."""


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as target:
            json.dump(payload, target, ensure_ascii=False, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _load_result(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationReviewError("No fue posible leer el resultado de evaluación.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise EvaluationReviewError("Solo se admiten resultados con schema_version 2.")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvaluationReviewError("El resultado de evaluación está incompleto.")
    ids: list[str] = []
    allowed_categories = {
        "historical_accuracy",
        "source_interpretation",
        "educational_usefulness",
        "character_fidelity",
    }
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("id"), str)
            or not isinstance(case.get("turns"), list)
            or not case["turns"]
            or not isinstance(case.get("human_review"), list)
            or not isinstance(case.get("operational_errors"), list)
            or any(
                not isinstance(turn, dict)
                or not isinstance(turn.get("checks"), list)
                or (not isinstance(turn.get("completion"), dict) and not turn.get("error"))
                for turn in case.get("turns", [])
            )
            or not set(case.get("human_review", [])) <= allowed_categories
        ):
            raise EvaluationReviewError("El resultado de evaluación contiene un caso incompleto.")
        ids.append(case["id"])
    if len(ids) != len(set(ids)):
        raise EvaluationReviewError("El resultado de evaluación contiene casos duplicados.")
    return payload


def nearest_rank_percentile(values: Sequence[float | int], percentile: float) -> float:
    if not values or not 0 < percentile <= 1:
        raise ValueError("percentile requires values and a probability in (0, 1]")
    ordered = sorted(float(value) for value in values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def _metrics(payload: dict[str, Any]) -> dict[str, float]:
    turns = [turn for case in payload["cases"] for turn in case["turns"]]
    costs = [float(turn.get("estimated_cost_usd", 0)) for turn in turns]
    latencies = [float(turn.get("latency_ms", 0)) for turn in turns]
    return {
        "median_cost_usd": float(median(costs)),
        "p95_cost_usd": nearest_rank_percentile(costs, 0.95),
        "median_latency_ms": float(median(latencies)),
        "p95_latency_ms": nearest_rank_percentile(latencies, 0.95),
    }


def _baseline_metrics(path: Path | None) -> dict[str, float] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary = payload.get("summary", {})
        return {
            "p95_cost_usd": float(summary["p95_cost_usd"]),
            "p95_latency_ms": float(summary["p95_latency_ms"]),
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise EvaluationReviewError("La línea base de evaluación es inválida.") from exc


def _load_rubric(path: Path) -> HumanRubric:
    try:
        return HumanRubric.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise EvaluationReviewError("La rúbrica de revisión es inválida.") from exc


def _current_case_ids(path: Path = DEFAULT_DATASET) -> tuple[str, ...]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        case_ids = tuple(case["id"] for case in payload["cases"])
    except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        raise EvaluationReviewError("La matriz de evaluación actual es inválida.") from exc
    if (
        not case_ids
        or len(case_ids) != len(set(case_ids))
        or not all(isinstance(case_id, str) and case_id for case_id in case_ids)
    ):
        raise EvaluationReviewError("La matriz de evaluación actual es inválida.")
    return case_ids


def _read(stdin: TextIO, stdout: TextIO, prompt: str) -> str:
    print(prompt, end=" ", file=stdout, flush=True)
    value = stdin.readline()
    if value == "":
        raise EvaluationReviewError("Revisión interrumpida; el progreso guardado se conserva.")
    return value.rstrip("\r\n")


def _score(
    stdin: TextIO,
    stdout: TextIO,
    title: str,
    definition: RubricCategoryDefinition,
) -> int:
    print(f"\n{definition.title}", file=stdout)
    for value in (1, 2, 3, 4):
        print(f"  {value}: {definition.scores[value]}", file=stdout)
    while True:
        value = _read(stdin, stdout, f"{title} (1..4):")
        if value in {"1", "2", "3", "4"}:
            return int(value)
        print("Ingrese un número entre 1 y 4.", file=stdout)


def _acknowledgement(stdin: TextIO, stdout: TextIO) -> bool:
    while True:
        value = _read(stdin, stdout, "¿Reconoce la revisión de costo y latencia? [s/n]:")
        normalized = value.strip().casefold()
        if normalized in {"s", "si", "sí", "y", "yes"}:
            return True
        if normalized in {"n", "no"}:
            return False
        print("Responda s o n.", file=stdout)


def _required_text(stdin: TextIO, stdout: TextIO, prompt: str) -> str:
    while True:
        value = _read(stdin, stdout, prompt).strip()
        if value:
            return value
        print("La explicación no puede estar vacía.", file=stdout)


def _terminal_text(value: object) -> str:
    text = value if isinstance(value, str) else str(value)
    return _UNSAFE_CONTROL.sub("", _ANSI_ESCAPE.sub("", text)).replace("\r", "")


def _display_case(case: dict[str, Any], stdout: TextIO) -> None:
    print(f"\n=== Caso {_terminal_text(case['id'])} ===", file=stdout)
    for turn in case["turns"]:
        print(
            f"Turno {_terminal_text(turn.get('turn_number', '?'))}: "
            f"{_terminal_text(turn.get('prompt', ''))}",
            file=stdout,
        )
        print(
            f"Acción enviada: {_terminal_text(turn.get('submitted_action_id'))}",
            file=stdout,
        )
        print(
            "Estado de aprendizaje de entrada: "
            + _terminal_text(
                json.dumps(turn.get("learning_state", {}), ensure_ascii=False, sort_keys=True)
            ),
            file=stdout,
        )
        if turn.get("expect") is not None:
            print(
                "Expectativas revisadas: "
                + json.dumps(turn["expect"], ensure_ascii=False, sort_keys=True),
                file=stdout,
            )
        completion = turn.get("completion")
        if isinstance(completion, dict):
            print(f"Respuesta: {_terminal_text(completion.get('final_text', ''))}", file=stdout)
            print(f"Estado: {_terminal_text(completion.get('answer_status', ''))}", file=stdout)
            print(
                "Citas: "
                + _terminal_text(
                    json.dumps(completion.get("citations", []), ensure_ascii=False, sort_keys=True)
                ),
                file=stdout,
            )
            documents = [
                source.get("document_id") or source.get("title", "sin mapa")
                for source in completion.get("sources", [])
                if isinstance(source, dict)
            ]
            document_text = _terminal_text(", ".join(str(item) for item in documents))
            print(f"Fuentes: {document_text}", file=stdout)
            print(
                "Tarjetas y bloques de evidencia: "
                + _terminal_text(
                    json.dumps(completion.get("sources", []), ensure_ascii=False, sort_keys=True)
                ),
                file=stdout,
            )
            action_types = [
                action.get("type", "")
                for action in completion.get("educational_actions", [])
                if isinstance(action, dict)
            ]
            print(f"Acciones: {_terminal_text(', '.join(action_types))}", file=stdout)
            print(
                "Detalle de acciones: "
                + _terminal_text(
                    json.dumps(
                        completion.get("educational_actions", []),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
                file=stdout,
            )
            print(
                "Estado de aprendizaje devuelto: "
                + _terminal_text(
                    json.dumps(
                        completion.get("learning_state", {}),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
                file=stdout,
            )
        print(
            f"Observación: costo={float(turn.get('estimated_cost_usd', 0)):.6f} USD; "
            f"latencia={float(turn.get('latency_ms', 0)):.2f} ms; "
            f"uso={json.dumps(turn.get('usage', {}), ensure_ascii=False, sort_keys=True)}",
            file=stdout,
        )
        if turn.get("error"):
            print(f"Error operativo: {_terminal_text(turn['error'])}", file=stdout)
        failures = [
            check
            for check in turn.get("checks", [])
            if isinstance(check, dict) and check.get("passed") is not True
        ]
        for check in failures:
            print(
                f"FALLO determinista [{_terminal_text(check.get('id', '?'))}]: "
                f"{_terminal_text(check.get('detail', ''))}",
                file=stdout,
            )
    for error in case.get("operational_errors", []):
        print(f"Error operativo del caso: {_terminal_text(error)}", file=stdout)


def _case_review_is_complete(entry: object, categories: list[str]) -> bool:
    if not isinstance(entry, dict):
        return False
    scores = entry.get("scores")
    return (
        isinstance(scores, dict)
        and set(scores) == set(categories)
        and all(
            isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 4
            for score in scores.values()
        )
        and isinstance(entry.get("notes"), str)
        and isinstance(entry.get("reviewed_at"), str)
        and bool(entry["reviewed_at"].strip())
    )


def _performance_review_is_complete(
    entry: object,
    metrics: dict[str, float],
    baseline: dict[str, float] | None,
) -> bool:
    structurally_complete = (
        isinstance(entry, dict)
        and entry.get("acknowledged") is True
        and all(
            isinstance(entry.get(key), str)
            for key in (
                "notes",
                "cost_regression_explanation",
                "latency_regression_explanation",
            )
        )
    )
    if not structurally_complete:
        return False
    assert isinstance(entry, dict)
    return (
        not _regression_explanation_needed(metrics, baseline, "p95_cost_usd")
        or bool(entry["cost_regression_explanation"].strip())
    ) and (
        not _regression_explanation_needed(metrics, baseline, "p95_latency_ms")
        or bool(entry["latency_regression_explanation"].strip())
    )


def _regression_explanation_needed(
    metrics: dict[str, float], baseline: dict[str, float] | None, metric: str
) -> bool:
    return bool(
        baseline and baseline.get(metric, 0) > 0 and metrics[metric] > baseline[metric] * 1.15
    )


def review_result(
    path: Path,
    *,
    stdin: TextIO,
    stdout: TextIO,
    baseline_path: Path | None = None,
    rubric_path: Path = DEFAULT_RUBRIC,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    payload = _load_result(path)
    rubric = _load_rubric(rubric_path)
    raw_review = payload.setdefault("review", {})
    if not isinstance(raw_review, dict):
        raise EvaluationReviewError("La revisión guardada es inválida.")
    reviewer = raw_review.get("reviewer")
    if reviewer is None:
        reviewer = _read(stdin, stdout, "Identidad del revisor:").strip()
        if not reviewer:
            raise EvaluationReviewError("La identidad del revisor no puede estar vacía.")
        raw_review["reviewer"] = reviewer
        raw_review["cases"] = {}
        _atomic_write_json(path, payload)
    elif not isinstance(reviewer, str) or not reviewer.strip():
        raise EvaluationReviewError("La identidad guardada del revisor es inválida.")
    reviewed_cases = raw_review.setdefault("cases", {})
    if not isinstance(reviewed_cases, dict):
        raise EvaluationReviewError("Las revisiones de casos guardadas son inválidas.")

    for case in payload["cases"]:
        categories = case["human_review"]
        if not categories:
            continue
        if _case_review_is_complete(reviewed_cases.get(case["id"]), categories):
            continue
        reviewed_cases.pop(case["id"], None)
        _display_case(case, stdout)
        scores = {
            category: _score(stdin, stdout, category, rubric.categories[category])
            for category in categories
        }
        notes = _read(stdin, stdout, "Notas opcionales (Enter para omitir):")
        reviewed_cases[case["id"]] = {
            "scores": scores,
            "notes": notes,
            "reviewed_at": now().astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        _atomic_write_json(path, payload)

    metrics = _metrics(payload)
    baseline = _baseline_metrics(baseline_path)
    if not _performance_review_is_complete(raw_review.get("performance"), metrics, baseline):
        raw_review.pop("performance", None)
        print(f"Mediana costo: {metrics['median_cost_usd']:.6f} USD", file=stdout)
        print(f"p95 costo: {metrics['p95_cost_usd']:.6f} USD", file=stdout)
        print(f"Mediana latencia: {metrics['median_latency_ms']:.2f} ms", file=stdout)
        print(f"p95 latencia: {metrics['p95_latency_ms']:.2f} ms", file=stdout)
        acknowledged = _acknowledgement(stdin, stdout)
        notes = _read(stdin, stdout, "Notas de costo y latencia:")
        cost_explanation = ""
        latency_explanation = ""
        if _regression_explanation_needed(metrics, baseline, "p95_cost_usd"):
            cost_explanation = _required_text(
                stdin, stdout, "Explique el aumento de p95 de costo superior al 15%:"
            )
        if _regression_explanation_needed(metrics, baseline, "p95_latency_ms"):
            latency_explanation = _required_text(
                stdin, stdout, "Explique el aumento de p95 de latencia superior al 15%:"
            )
        raw_review["performance"] = {
            "acknowledged": acknowledged,
            "notes": notes,
            "cost_regression_explanation": cost_explanation,
            "latency_regression_explanation": latency_explanation,
        }
        _atomic_write_json(path, payload)
    return payload


def compare_result(
    path: Path,
    *,
    stdout: TextIO,
    baseline_path: Path | None = None,
    corpus: CorpusService | None = None,
    expected_case_ids: Sequence[str] | None = None,
) -> QualityGateReport:
    payload = _load_result(path)
    corpus = corpus or CorpusService.load(CorpusPaths.repository_defaults())
    deterministic_checks_complete = _revalidate_deterministic_checks(payload, corpus)
    expected_ids = (
        tuple(expected_case_ids) if expected_case_ids is not None else _current_case_ids()
    )
    actual_ids = tuple(case["id"] for case in payload["cases"])
    report = evaluate_quality_gate(
        payload,
        metrics=_metrics(payload),
        baseline_metrics=_baseline_metrics(baseline_path),
        deterministic_checks_complete=deterministic_checks_complete,
        case_matrix_complete=actual_ids == expected_ids,
    )
    for rule in report.rules:
        print(f"[{'PASS' if rule.passed else 'FAIL'}] {rule.id}: {rule.detail}", file=stdout)
    if report.provider_errors:
        print("Errores operativos informados por separado:", file=stdout)
        for error in report.provider_errors:
            print(f"- {error}", file=stdout)
    print(
        f"RESULTADO GENERAL: {'APROBADO' if report.passed else 'RECHAZADO'}",
        file=stdout,
    )
    return report


def _check_signature(check: object) -> tuple[object, ...] | None:
    if not isinstance(check, dict):
        return None
    return (
        check.get("id"),
        check.get("group"),
        check.get("passed"),
        check.get("critical"),
        check.get("detail"),
    )


def _revalidate_deterministic_checks(payload: dict[str, Any], corpus: CorpusService) -> bool:
    """Recompute checks from stored completion/evaluation inputs before gating."""
    try:
        for case in payload["cases"]:
            for turn in case["turns"]:
                completion_payload = turn.get("completion")
                completion = (
                    CompleteEventData.model_validate(completion_payload)
                    if completion_payload is not None
                    else None
                )
                expectation = TurnExpectation.model_validate(turn["expect"])
                input_state = LearningState.model_validate(turn.get("learning_state", {}))
                recomputed = run_turn_checks(
                    completion,
                    expectation,
                    corpus=corpus,
                    case_critical=case.get("critical") is True,
                    input_state=input_state,
                    submitted_action_id=turn.get("submitted_action_id"),
                )
                expected = [
                    (check.id, check.group, check.passed, check.critical, check.detail)
                    for check in recomputed
                ]
                stored = [_check_signature(check) for check in turn["checks"]]
                if stored != expected:
                    return False
        return True
    except (KeyError, TypeError, ValueError):
        return False
