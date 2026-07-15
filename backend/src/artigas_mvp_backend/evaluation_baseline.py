"""Deliberate, hash-bound promotion of reviewed evaluation results."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import yaml

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.corpus import CorpusPaths, sha256_file
from artigas_mvp_backend.ingest import (
    FILE_SEARCH_MAX_OVERLAP_TOKENS,
    FILE_SEARCH_MAX_TOKENS_PER_CHUNK,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class EvaluationBaselineError(Exception):
    """Raised when a result cannot be safely promoted."""


@dataclass(frozen=True)
class ArtifactPaths:
    """Every reviewed input whose exact bytes define an evaluation release."""

    pdf: Path
    pages: Path
    manifest: Path
    learning_map: Path
    prompt: Path
    prompt_loader: Path
    dataset: Path
    rubric: Path

    @classmethod
    def repository_defaults(cls, *, dataset: Path | None = None) -> ArtifactPaths:
        corpus = CorpusPaths.repository_defaults()
        return cls(
            pdf=corpus.pdf,
            pages=corpus.pages,
            manifest=corpus.manifest,
            learning_map=corpus.learning_map,
            prompt=REPOSITORY_ROOT
            / "backend"
            / "src"
            / "artigas_mvp_backend"
            / "prompts"
            / "artigas.txt",
            prompt_loader=REPOSITORY_ROOT
            / "backend"
            / "src"
            / "artigas_mvp_backend"
            / "prompts"
            / "__init__.py",
            dataset=dataset or REPOSITORY_ROOT / "evals" / "artigas-cases.yaml",
            rubric=REPOSITORY_ROOT / "evals" / "rubric.yaml",
        )


_ARTIFACT_NAMES = {
    "pdf": "corpus_pdf",
    "pages": "page_sidecar",
    "manifest": "source_manifest",
    "learning_map": "learning_map",
    "dataset": "evaluation_dataset",
    "rubric": "evaluation_rubric",
}


def current_artifact_hashes(paths: ArtifactPaths) -> dict[str, str]:
    """Hash all release inputs immediately, without loading credentials."""
    try:
        hashes = {
            output_name: sha256_file(getattr(paths, field_name))
            for field_name, output_name in _ARTIFACT_NAMES.items()
        }
        prompt_digest = hashlib.sha256()
        for path in (paths.prompt, paths.prompt_loader):
            content = path.read_bytes()
            prompt_digest.update(len(content).to_bytes(8, "big"))
            prompt_digest.update(content)
        hashes["prompt_runtime"] = prompt_digest.hexdigest()
        return hashes
    except OSError as exc:
        raise EvaluationBaselineError("No fue posible verificar los artefactos actuales.") from exc


def runtime_settings(settings: Settings) -> dict[str, Any]:
    """Return only reproducibility settings; credentials and store IDs are excluded."""
    return {
        "thinking_level": settings.gemini_thinking_level,
        "max_output_tokens": settings.gemini_max_output_tokens,
        "temperature": settings.gemini_temperature,
        "chunk_tokens": FILE_SEARCH_MAX_TOKENS_PER_CHUNK,
        "chunk_overlap_tokens": FILE_SEARCH_MAX_OVERLAP_TOKENS,
    }


def _load_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        content = path.read_bytes()
        payload = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationBaselineError("No fue posible leer el resultado de evaluación.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise EvaluationBaselineError("Solo se pueden promover resultados con schema_version 2.")
    if not isinstance(payload.get("cases"), list):
        raise EvaluationBaselineError("El resultado de evaluación está incompleto.")
    return payload, hashlib.sha256(content).hexdigest()


def _expected_case_ids(path: Path) -> list[str]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        cases = payload["cases"]
        ids = [case["id"] for case in cases]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        raise EvaluationBaselineError("El conjunto de evaluación actual es inválido.") from exc
    if (
        not ids
        or any(not isinstance(case_id, str) or not case_id for case_id in ids)
        or len(ids) != len(set(ids))
    ):
        raise EvaluationBaselineError("El conjunto de evaluación actual es inválido.")
    return ids


def _assert_complete_review(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    review = payload.get("review")
    if not isinstance(review, dict):
        raise EvaluationBaselineError("La revisión humana está incompleta.")
    reviewer = review.get("reviewer")
    reviewed_cases = review.get("cases")
    performance = review.get("performance")
    if (
        not isinstance(reviewer, str)
        or not reviewer.strip()
        or not isinstance(reviewed_cases, dict)
        or not isinstance(performance, dict)
        or performance.get("acknowledged") is not True
    ):
        raise EvaluationBaselineError("La revisión humana está incompleta.")
    for case in payload["cases"]:
        if not isinstance(case, dict):
            raise EvaluationBaselineError("El resultado contiene casos inválidos.")
        categories = case.get("human_review")
        if not isinstance(categories, list):
            raise EvaluationBaselineError("El resultado contiene casos inválidos.")
        if not categories:
            continue
        entry = reviewed_cases.get(case.get("id"))
        scores = entry.get("scores") if isinstance(entry, dict) else None
        if (
            not isinstance(scores, dict)
            or set(scores) != set(categories)
            or any(
                not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 4
                for score in scores.values()
            )
        ):
            raise EvaluationBaselineError("La revisión humana está incompleta.")
    return reviewer.strip(), reviewed_cases


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as target:
            json.dump(payload, target, ensure_ascii=False, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise EvaluationBaselineError("No fue posible escribir la línea base.") from exc
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _read_confirmation(stdin: TextIO, stdout: TextIO, expected: str) -> None:
    print("Escriba exactamente la confirmación mostrada para promover:", file=stdout)
    print(expected, file=stdout)
    supplied = stdin.readline()
    if supplied == "" or supplied.rstrip("\r\n") != expected:
        raise EvaluationBaselineError("La confirmación de promoción no coincide.")


def _assert_replaceable_baseline(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        content = path.read_bytes()
        payload = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationBaselineError("La línea base existente es inválida.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise EvaluationBaselineError("La línea base existente es inválida.")
    return hashlib.sha256(content).hexdigest()


def _files_unchanged(
    result_path: Path,
    result_sha256: str,
    baseline_path: Path,
    baseline_sha256: str | None,
    artifacts: ArtifactPaths,
    artifact_hashes: dict[str, str],
) -> bool:
    try:
        baseline_unchanged = (
            not baseline_path.exists()
            if baseline_sha256 is None
            else baseline_path.exists() and sha256_file(baseline_path) == baseline_sha256
        )
        return (
            sha256_file(result_path) == result_sha256
            and baseline_unchanged
            and current_artifact_hashes(artifacts) == artifact_hashes
        )
    except (OSError, EvaluationBaselineError):
        return False


def _baseline_payload(
    result: dict[str, Any],
    *,
    result_sha256: str,
    hashes: dict[str, str],
    reviewer: str,
    reviewed_cases: dict[str, Any],
    report: Any,
    promoted_at: datetime,
) -> dict[str, Any]:
    case_results: list[dict[str, Any]] = []
    for case in result["cases"]:
        stored_review = reviewed_cases.get(case["id"], {})
        checks = [
            check
            for turn in case.get("turns", [])
            for check in turn.get("checks", [])
            if isinstance(check, dict)
        ]
        case_results.append(
            {
                "id": case["id"],
                "deterministic_passed": bool(checks)
                and all(check.get("passed") is True for check in checks),
                "operational_error_count": len(case.get("operational_errors", [])),
                "scores": dict(stored_review.get("scores", {})),
            }
        )
    return {
        "schema_version": 1,
        "promoted_at": promoted_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "reviewer": reviewer,
        "source_result_sha256": result_sha256,
        "artifact_hashes": hashes,
        "model": result["model"],
        "settings": result["settings"],
        "results": case_results,
        "scores": dict(report.category_averages),
        "summary": dict(report.metrics),
    }


def promote_result(
    result_path: Path,
    *,
    baseline_path: Path,
    artifacts: ArtifactPaths,
    settings: Settings,
    stdin: TextIO,
    stdout: TextIO,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    gate_evaluator: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Promote only a complete, current, reviewed result after exact confirmation."""
    result, result_sha256 = _load_json(result_path)
    reviewer, reviewed_cases = _assert_complete_review(result)
    expected_ids = _expected_case_ids(artifacts.dataset)
    result_ids = [case.get("id") for case in result["cases"] if isinstance(case, dict)]
    if result_ids != expected_ids:
        raise EvaluationBaselineError("El resultado no contiene todos los casos actuales.")

    hashes = current_artifact_hashes(artifacts)
    if (
        result.get("artifact_hashes") != hashes
        or result.get("dataset_sha256") != hashes["evaluation_dataset"]
    ):
        raise EvaluationBaselineError("Los artefactos actuales cambiaron desde la evaluación.")
    expected_settings = runtime_settings(settings)
    if result.get("model") != settings.gemini_model or result.get("settings") != expected_settings:
        raise EvaluationBaselineError("El modelo o la configuración actual difieren del resultado.")

    baseline_sha256 = _assert_replaceable_baseline(baseline_path)

    if gate_evaluator is None:
        from artigas_mvp_backend.evaluation_review import compare_result

        gate_evaluator = compare_result
    report = gate_evaluator(result_path, stdout=stdout, baseline_path=baseline_path)
    if not report.passed:
        raise EvaluationBaselineError("El resultado no supera la puerta formal de calidad.")

    if not _files_unchanged(
        result_path, result_sha256, baseline_path, baseline_sha256, artifacts, hashes
    ):
        raise EvaluationBaselineError(
            "El resultado o los artefactos cambiaron durante la revisión."
        )
    if baseline_sha256 is not None:
        expected_confirmation = f"{baseline_sha256} {result_sha256}"
    else:
        expected_confirmation = result_sha256
    _read_confirmation(stdin, stdout, expected_confirmation)
    if not _files_unchanged(
        result_path, result_sha256, baseline_path, baseline_sha256, artifacts, hashes
    ):
        raise EvaluationBaselineError("Los archivos cambiaron durante la confirmación.")
    baseline = _baseline_payload(
        result,
        result_sha256=result_sha256,
        hashes=hashes,
        reviewer=reviewer,
        reviewed_cases=reviewed_cases,
        report=report,
        promoted_at=now(),
    )
    if not _files_unchanged(
        result_path, result_sha256, baseline_path, baseline_sha256, artifacts, hashes
    ):
        raise EvaluationBaselineError("Los archivos cambiaron inmediatamente antes de promover.")
    _atomic_write_json(baseline_path, baseline)
    return baseline
