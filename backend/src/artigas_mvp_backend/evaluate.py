"""Run explicitly selected live Artigas cases for manual human review."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import yaml

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.services.usage import (
    CACHED_INPUT_USD_PER_MILLION,
    INPUT_USD_PER_MILLION,
    OUTPUT_AND_THOUGHT_USD_PER_MILLION,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = REPOSITORY_ROOT / "evals" / "artigas-cases.yaml"
DEFAULT_RESULTS_DIR = REPOSITORY_ROOT / "evals" / "results"


class EvaluationDataError(Exception):
    """Raised when the committed evaluation dataset is invalid."""


class CaseSelectionError(Exception):
    """Raised when a requested case does not exist."""


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    prompt: str
    expected_behavior: str
    requires_citation: bool
    tags: tuple[str, ...]


def load_cases(path: Path = DEFAULT_DATASET) -> tuple[EvaluationCase, ...]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EvaluationDataError("No fue posible leer el conjunto de evaluación.") from exc
    if not isinstance(document, list):
        raise EvaluationDataError("El conjunto de evaluación debe ser una lista.")

    cases: list[EvaluationCase] = []
    ids: set[str] = set()
    for entry in document:
        if not isinstance(entry, dict):
            raise EvaluationDataError("Cada caso debe ser un objeto.")
        case_id = entry.get("id")
        prompt = entry.get("prompt")
        expected = entry.get("expected_behavior")
        requires_citation = entry.get("requires_citation")
        tags = entry.get("tags")
        if (
            not isinstance(case_id, str)
            or not case_id.strip()
            or not isinstance(prompt, str)
            or not prompt.strip()
            or not isinstance(expected, str)
            or not expected.strip()
            or not isinstance(requires_citation, bool)
            or not isinstance(tags, list)
            or not tags
            or not all(isinstance(tag, str) and tag.strip() for tag in tags)
        ):
            raise EvaluationDataError("Un caso de evaluación tiene un esquema inválido.")
        if case_id in ids:
            raise EvaluationDataError("Los identificadores de casos deben ser únicos.")
        ids.add(case_id)
        cases.append(
            EvaluationCase(
                id=case_id,
                prompt=prompt,
                expected_behavior=expected,
                requires_citation=requires_citation,
                tags=tuple(tags),
            )
        )
    if len(cases) != 15:
        raise EvaluationDataError("El conjunto debe contener exactamente 15 casos.")
    return tuple(cases)


def select_cases(
    cases: tuple[EvaluationCase, ...],
    *,
    case_id: str | None = None,
    all_cases: bool = False,
) -> tuple[EvaluationCase, ...]:
    if all_cases:
        return cases
    for case in cases:
        if case.id == case_id:
            return (case,)
    raise CaseSelectionError("No existe el caso de evaluación solicitado.")


def _dump_model(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    return model_dump(mode="json") if callable(model_dump) else value


def _serialize_usage(usage: Any) -> dict[str, Any]:
    to_payload = getattr(usage, "to_payload", None)
    payload = to_payload() if callable(to_payload) else usage
    dumped = _dump_model(payload)
    return dumped if isinstance(dumped, dict) else {}


def _serialize_citations(citations: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for citation in citations or ():
        dumped = _dump_model(citation)
        if isinstance(dumped, dict):
            result.append(dumped)
    return result


def _stable_error(exc: Exception) -> dict[str, Any]:
    code = getattr(exc, "code", "provider_error")
    message = getattr(exc, "user_message", "No fue posible completar la respuesta.")
    retryable = getattr(exc, "retryable", False)
    return {
        "code": code if isinstance(code, str) else "provider_error",
        "message": message
        if isinstance(message, str)
        else "No fue posible completar la respuesta.",
        "retryable": retryable if isinstance(retryable, bool) else False,
    }


async def _run_cases(
    cases: Sequence[EvaluationCase],
    service: Any,
    clock: Callable[[], float],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        started = clock()
        answer = ""
        citations: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        error: dict[str, Any] | None = None
        try:
            completed = None
            async for event in service.stream(
                message=case.prompt,
                previous_interaction_id=None,
            ):
                if hasattr(event, "final_text"):
                    completed = event
            if completed is None:
                raise RuntimeError("missing completion")
            answer = completed.final_text
            citations = _serialize_citations(completed.citations)
            usage = _serialize_usage(completed.usage)
        except Exception as exc:
            error = _stable_error(exc)
        latency_ms = round((clock() - started) * 1000)
        results.append(
            {
                "id": case.id,
                "prompt": case.prompt,
                "expected_behavior": case.expected_behavior,
                "requires_citation": case.requires_citation,
                "answer": answer,
                "citations": citations,
                "usage": usage,
                "latency_ms": latency_ms,
                "error": error,
            }
        )
    return results


def _default_service_factory(settings: Settings) -> Any:
    from artigas_mvp_backend.services.gemini import GeminiService

    return GeminiService(settings)


def _print_cost_notice(count: int, max_output_tokens: int, stdout: TextIO) -> None:
    noun = "llamada" if count == 1 else "llamadas"
    adjective = "real" if count == 1 else "reales"
    print(f"Se realizarán {count} {noun} {adjective} al modelo, una por caso.", file=stdout)
    formatted_output_tokens = f"{max_output_tokens:,}".replace(",", ".")
    print(
        f"Límites por llamada: {formatted_output_tokens} tokens de salida y "
        "2.000 caracteres de entrada.",
        file=stdout,
    )
    print(
        "Precios por millón de tokens (USD): "
        f"entrada {INPUT_USD_PER_MILLION}, "
        f"entrada en caché {CACHED_INPUT_USD_PER_MILLION}, "
        f"salida y pensamiento {OUTPUT_AND_THOUGHT_USD_PER_MILLION}.",
        file=stdout,
    )
    print(
        "File Search agrega recuperación, por lo que el cargo exacto no puede conocerse "
        "de antemano.",
        file=stdout,
    )


def main(
    argv: list[str] | None = None,
    *,
    dataset_path: Path = DEFAULT_DATASET,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    service_factory: Callable[[Settings], Any] = _default_service_factory,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    clock: Callable[[], float] = time.perf_counter,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output_stream: TextIO = sys.stdout if stdout is None else stdout
    error_stream: TextIO = sys.stderr if stderr is None else stderr
    parser = argparse.ArgumentParser(description="Ejecuta evaluaciones manuales con costo real.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case", dest="case_id")
    selection.add_argument("--all", dest="all_cases", action="store_true")
    parser.add_argument("--confirm-cost", action="store_true")
    args = parser.parse_args(argv)

    try:
        cases = select_cases(
            load_cases(dataset_path),
            case_id=args.case_id,
            all_cases=args.all_cases,
        )
    except (EvaluationDataError, CaseSelectionError) as exc:
        print(str(exc), file=error_stream)
        return 2

    settings = Settings.from_env()
    _print_cost_notice(len(cases), settings.gemini_max_output_tokens, output_stream)
    if not args.confirm_cost:
        print("Agregue --confirm-cost para autorizar las llamadas reales.", file=error_stream)
        return 2

    configuration_error = settings.chat_configuration_error()
    if configuration_error:
        print(configuration_error, file=error_stream)
        return 2

    service = service_factory(settings)
    results = asyncio.run(_run_cases(cases, service, clock))
    timestamp = now().astimezone(UTC)
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = results_dir / timestamp.strftime("%Y%m%dT%H%M%SZ.json")
    payload = {
        "generated_at": timestamp.isoformat().replace("+00:00", "Z"),
        "model": settings.gemini_model,
        "results": results,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Resultados guardados en {output_path}", file=output_stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
