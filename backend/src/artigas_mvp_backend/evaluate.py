"""Run the reviewed Artigas evaluation matrix and record deterministic evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import yaml
from pydantic import ValidationError

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.corpus import CorpusPaths
from artigas_mvp_backend.evaluation_baseline import (
    ArtifactPaths,
    current_artifact_hashes,
    runtime_settings,
)
from artigas_mvp_backend.evaluation_checks import checks_to_payload, run_turn_checks
from artigas_mvp_backend.evaluation_models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationTurn,
)
from artigas_mvp_backend.models import CompleteEventData, HistoryMessage, LearningState
from artigas_mvp_backend.services.corpus import CorpusService
from artigas_mvp_backend.services.education import (
    advance_learning_state,
    normalize_learning_state,
    select_educational_actions,
)
from artigas_mvp_backend.services.evidence import (
    analyze_citations,
    build_source_cards,
    canonicalize_answer_text,
    classify_answer,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = REPOSITORY_ROOT / "evals" / "artigas-cases.yaml"
DEFAULT_RESULTS_DIR = REPOSITORY_ROOT / "evals" / "results"
DEFAULT_BASELINE = REPOSITORY_ROOT / "evals" / "baseline.json"

_LEGACY_CASE_ALIASES = {
    "instructions-xiii": "art-005-core",
    "art-005-instructions": "art-005-core",
}


class EvaluationDataError(Exception):
    """Raised when evaluation input or a resumable result is invalid."""


class CaseSelectionError(Exception):
    """Raised when a requested case does not exist."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path: Path = DEFAULT_DATASET) -> EvaluationDataset:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return EvaluationDataset.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise EvaluationDataError("No fue posible leer el conjunto de evaluación v2.") from exc


def load_cases(path: Path = DEFAULT_DATASET) -> tuple[EvaluationCase, ...]:
    """Compatibility facade retained for callers of the original evaluator."""
    return load_dataset(path).cases


def select_cases(
    cases: tuple[EvaluationCase, ...],
    *,
    case_id: str | None = None,
    all_cases: bool = False,
) -> tuple[EvaluationCase, ...]:
    if all_cases:
        return cases
    selected_id = _LEGACY_CASE_ALIASES.get(case_id or "", case_id)
    for case in cases:
        if case.id == selected_id:
            return (case,)
    raise CaseSelectionError("No existe el caso de evaluación solicitado.")


def _dump_model(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    return model_dump(mode="json") if callable(model_dump) else value


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
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _fixture_path(case: EvaluationCase) -> Path:
    assert case.fixture_file is not None
    path = Path(case.fixture_file)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def _load_fixture(case: EvaluationCase) -> tuple[CompleteEventData | None, dict[str, Any] | None]:
    try:
        payload = json.loads(_fixture_path(case).read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported fixture schema")
        raw_completion = payload.get("completion")
        completion = (
            CompleteEventData.model_validate(raw_completion) if raw_completion is not None else None
        )
        raw_error = payload.get("error")
        if raw_error is not None and not isinstance(raw_error, dict):
            raise ValueError("invalid fixture error")
        return completion, raw_error
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise EvaluationDataError(f"El fixture del caso {case.id} es inválido.") from exc


def _prepare_state(
    turn: EvaluationTurn,
    carried_state: LearningState,
    corpus: CorpusService,
) -> LearningState:
    state = (
        turn.learning_state.model_copy(deep=True)
        if turn.learning_state
        else carried_state.model_copy(deep=True)
    )
    submitted = turn.submitted_action_id
    state.submitted_action_id = (
        submitted
        if submitted is not None and corpus.validate_action_id(submitted) is not None
        else None
    )
    return normalize_learning_state(state, corpus)


def _enrich_completion(
    completed: Any,
    state: LearningState,
    corpus: CorpusService,
) -> CompleteEventData:
    citations = list(completed.citations)
    final_text = canonicalize_answer_text(completed.final_text, citations)
    normalized_state = advance_learning_state(state, corpus)
    analysis = analyze_citations(citations, corpus)
    answer_status = classify_answer(final_text, citations)
    actions = select_educational_actions(
        answer_status=answer_status,
        analysis=analysis,
        state=normalized_state,
        corpus=corpus,
    )
    return CompleteEventData(
        final_text=final_text,
        citations=citations,
        answer_status=answer_status,
        sources=list(build_source_cards(final_text, citations, analysis, corpus)),
        educational_actions=list(actions),
        learning_state=normalized_state,
        usage=completed.usage.to_payload(),
    )


async def _run_live_turn(
    turn: EvaluationTurn,
    *,
    service: Any,
    corpus: CorpusService,
    history: list[HistoryMessage],
    state: LearningState,
) -> tuple[CompleteEventData | None, dict[str, Any] | None]:
    iterator = None
    completion: CompleteEventData | None = None
    error: dict[str, Any] | None = None
    try:
        iterator = service.stream(
            message=turn.prompt,
            history=list(history),
        )
        completed = None
        async for event in iterator:
            if hasattr(event, "final_text"):
                completed = event
        if completed is None:
            raise RuntimeError("missing completion")
        completion = _enrich_completion(completed, state, corpus)
    except Exception as exc:
        error = _stable_error(exc)
    if iterator is not None and hasattr(iterator, "aclose"):
        try:
            await iterator.aclose()
        except Exception as exc:
            if error is None:
                completion = None
                error = _stable_error(exc)
    return completion, error


async def _execute_case(
    case: EvaluationCase,
    *,
    service: Any | None,
    corpus: CorpusService,
    clock: Callable[[], float],
) -> dict[str, Any]:
    turns: list[dict[str, Any]] = []
    operational_errors: list[dict[str, Any]] = []
    history: list[HistoryMessage] = []
    carried_state = LearningState()

    for turn_number, turn in enumerate(case.turns, start=1):
        started = clock()
        input_state = _prepare_state(turn, carried_state, corpus)
        if case.execution == "fixture":
            completion, error = _load_fixture(case)
        else:
            if service is None:  # defensive: live selection always constructs it
                error = {
                    "code": "configuration_error",
                    "message": "La configuración del servicio de conversación no está completa.",
                    "retryable": False,
                }
                completion = None
            else:
                completion, error = await _run_live_turn(
                    turn,
                    service=service,
                    corpus=corpus,
                    history=history,
                    state=input_state,
                )
        latency_ms = max(0, round((clock() - started) * 1000))
        checks = run_turn_checks(
            completion,
            turn.expect,
            corpus=corpus,
            case_critical=case.critical,
            input_state=input_state,
            submitted_action_id=turn.submitted_action_id,
        )
        completion_payload = _dump_model(completion) if completion is not None else None
        usage = completion_payload.get("usage", {}) if completion_payload is not None else {}
        turn_result = {
            "turn_number": turn_number,
            "prompt": turn.prompt,
            "submitted_action_id": turn.submitted_action_id,
            "learning_state": input_state.model_dump(mode="json"),
            "expect": turn.expect.model_dump(mode="json"),
            "completion": completion_payload,
            "checks": checks_to_payload(checks),
            "usage": usage,
            "latency_ms": latency_ms,
            "estimated_cost_usd": usage.get("estimated_cost_usd", 0),
            "error": error,
        }
        turns.append(turn_result)
        if error is not None:
            operational_errors.append({"turn_number": turn_number, **error})
            break
        assert completion is not None
        history.extend(
            (
                HistoryMessage(role="user", content=turn.prompt),
                HistoryMessage(role="assistant", content=completion.final_text),
            )
        )
        carried_state = completion.learning_state.model_copy(deep=True)

    return {
        "id": case.id,
        "execution": case.execution,
        "critical": case.critical,
        "core_historical": case.core_historical,
        "human_review": list(case.human_review),
        "turns": turns,
        "operational_errors": operational_errors,
    }


def _print_cost_notice(call_count: int, settings: Settings, stdout: TextIO) -> None:
    noun = "llamada" if call_count == 1 else "llamadas"
    adjective = "real" if call_count == 1 else "reales"
    print(
        f"Se realizarán {call_count} {noun} {adjective} al modelo, una por turno live.",
        file=stdout,
    )
    formatted_output_tokens = f"{settings.chat_max_output_tokens:,}".replace(",", ".")
    print(
        f"Límites por llamada: {formatted_output_tokens} tokens de salida y "
        "2.000 caracteres de entrada.",
        file=stdout,
    )
    print(
        "Precios por millón de tokens (USD): "
        f"entrada {settings.input_price_usd_per_million}, "
        f"salida {settings.output_price_usd_per_million}.",
        file=stdout,
    )
    print(
        "La recuperación local no agrega llamadas al modelo de chat; la consulta de "
        "embeddings puede tener un costo adicional.",
        file=stdout,
    )


def _new_payload(
    *,
    timestamp: datetime,
    settings: Settings,
    dataset_path: Path,
) -> dict[str, Any]:
    artifact_hashes = current_artifact_hashes(
        ArtifactPaths.repository_defaults(dataset=dataset_path)
    )
    return {
        "schema_version": 2,
        "generated_at": timestamp.isoformat().replace("+00:00", "Z"),
        "dataset_sha256": _sha256_file(dataset_path),
        "artifact_hashes": artifact_hashes,
        "provider": "groq",
        "model": settings.chat_model,
        "embedding_model": settings.embedding_model,
        "corpus_sha256": artifact_hashes["corpus_pdf"],
        "settings": _runtime_settings(settings),
        "cases": [],
    }


def _runtime_settings(settings: Settings) -> dict[str, Any]:
    return runtime_settings(settings)


def _load_resume(
    path: Path,
    dataset_path: Path,
    settings: Settings,
    cases: Sequence[EvaluationCase],
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationDataError("No fue posible leer el resultado a reanudar.") from exc
    if payload.get("schema_version") != 2:
        raise EvaluationDataError("Solo se pueden reanudar resultados con schema_version 2.")
    if payload.get("dataset_sha256") != _sha256_file(dataset_path):
        raise EvaluationDataError("El resultado no corresponde al conjunto de evaluación actual.")
    if payload.get("artifact_hashes") != current_artifact_hashes(
        ArtifactPaths.repository_defaults(dataset=dataset_path)
    ):
        raise EvaluationDataError("Los artefactos de evaluación cambiaron desde la ejecución.")
    if (
        payload.get("provider") != "groq"
        or payload.get("model") != settings.chat_model
        or payload.get("embedding_model") != settings.embedding_model
        or payload.get("settings") != _runtime_settings(settings)
    ):
        raise EvaluationDataError("El resultado usa un modelo o configuración diferente.")
    if not isinstance(payload.get("cases"), list):
        raise EvaluationDataError("El resultado a reanudar no contiene casos válidos.")
    expected_by_id = {case.id: case for case in cases}
    result_ids: list[str] = []
    for item in payload["cases"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise EvaluationDataError("El resultado a reanudar contiene un caso inválido.")
        case_id = item["id"]
        expected = expected_by_id.get(case_id)
        turns = item.get("turns")
        operational_errors = item.get("operational_errors")
        if (
            expected is None
            or item.get("execution") != expected.execution
            or not isinstance(turns, list)
            or not turns
            or not isinstance(operational_errors, list)
            or (not operational_errors and len(turns) != len(expected.turns))
            or len(turns) > len(expected.turns)
            or any(not isinstance(turn, dict) for turn in turns)
        ):
            raise EvaluationDataError("El resultado a reanudar contiene un caso incompleto.")
        result_ids.append(case_id)
    if len(result_ids) != len(set(result_ids)):
        raise EvaluationDataError("El resultado a reanudar contiene casos duplicados.")
    return payload


async def _execute_pending_cases(
    pending: Sequence[EvaluationCase],
    *,
    settings: Settings,
    service_factory: Callable[[Settings], Any],
    corpus: CorpusService,
    clock: Callable[[], float],
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    service = (
        service_factory(settings) if any(case.execution == "live" for case in pending) else None
    )
    for case in pending:
        case_result = await _execute_case(case, service=service, corpus=corpus, clock=clock)
        payload["cases"].append(case_result)
        _atomic_write_json(output_path, payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ejecuta la evaluación educativa de Artigas.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Ejecuta casos live o fixtures.")
    selection = run.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case", dest="case_id")
    selection.add_argument("--all", dest="all_cases", action="store_true")
    run.add_argument("--confirm-cost", action="store_true")
    run.add_argument("--resume", type=Path)
    review = subparsers.add_parser("review", help="Revisa y puntúa un resultado.")
    review.add_argument("result", type=Path)
    compare = subparsers.add_parser("compare", help="Aplica la puerta formal de calidad.")
    compare.add_argument("result", type=Path)
    promote = subparsers.add_parser("promote", help="Promueve una línea base aprobada.")
    promote.add_argument("result", type=Path)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    dataset_path: Path = DEFAULT_DATASET,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    service_factory: Callable[[Settings], Any] | None = None,
    corpus_factory: Callable[[], CorpusService] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    clock: Callable[[], float] = time.perf_counter,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    baseline_path: Path = DEFAULT_BASELINE,
) -> int:
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    error_stream = sys.stderr if stderr is None else stderr
    arguments = list(sys.argv[1:] if argv is None else argv)
    legacy = bool(arguments and arguments[0] in {"--case", "--all"})
    if legacy:
        arguments.insert(0, "run")
        print(
            "Aviso: esta invocación es obsoleta; use `evaluate run`.",
            file=error_stream,
        )
    args = _parser().parse_args(arguments)
    if args.command == "promote":
        from artigas_mvp_backend.evaluation_baseline import (
            EvaluationBaselineError,
            promote_result,
        )

        try:
            promote_result(
                args.result,
                baseline_path=baseline_path,
                artifacts=ArtifactPaths.repository_defaults(dataset=dataset_path),
                settings=Settings.from_env(),
                stdin=input_stream,
                stdout=output_stream,
            )
            print(f"Línea base guardada en {baseline_path}", file=output_stream)
            return 0
        except EvaluationBaselineError as exc:
            print(str(exc), file=error_stream)
            return 2
    if args.command in {"review", "compare"}:
        from artigas_mvp_backend.evaluation_review import (
            EvaluationReviewError,
            compare_result,
            review_result,
        )

        try:
            if args.command == "review":
                review_result(
                    args.result,
                    stdin=input_stream,
                    stdout=output_stream,
                    baseline_path=baseline_path,
                )
                print(f"Revisión guardada en {args.result}", file=output_stream)
                return 0
            report = compare_result(
                args.result,
                stdout=output_stream,
                baseline_path=baseline_path,
            )
            return 0 if report.passed else 1
        except EvaluationReviewError as exc:
            print(str(exc), file=error_stream)
            return 2
    if args.resume is not None and not args.all_cases:
        print("--resume solo puede usarse junto con --all.", file=error_stream)
        return 2

    try:
        cases = select_cases(
            load_cases(dataset_path), case_id=args.case_id, all_cases=args.all_cases
        )
    except (EvaluationDataError, CaseSelectionError) as exc:
        print(str(exc), file=error_stream)
        return 2

    settings = Settings.from_env()
    live_turn_count = sum(len(case.turns) for case in cases if case.execution == "live")
    if live_turn_count:
        _print_cost_notice(live_turn_count, settings, output_stream)
        if not args.confirm_cost:
            print("Agregue --confirm-cost para autorizar las llamadas reales.", file=error_stream)
            return 2
        configuration_error = settings.chat_configuration_error()
        if configuration_error:
            print(configuration_error, file=error_stream)
            return 2

    timestamp = now().astimezone(UTC)
    output_path = (
        args.resume
        if args.resume is not None
        else results_dir / timestamp.strftime("%Y%m%dT%H%M%SZ.json")
    )
    try:
        payload = (
            _load_resume(output_path, dataset_path, settings, cases)
            if args.resume is not None
            else _new_payload(
                timestamp=timestamp,
                settings=settings,
                dataset_path=dataset_path,
            )
        )
        completed_ids = {item.get("id") for item in payload["cases"] if isinstance(item, dict)}
        selected_ids = {case.id for case in cases}
        if not completed_ids <= selected_ids:
            raise EvaluationDataError("El resultado contiene casos ajenos a esta ejecución.")
        pending = [case for case in cases if case.id not in completed_ids]
        corpus = (
            corpus_factory()
            if corpus_factory is not None
            else CorpusService.load(CorpusPaths.repository_defaults())
        )
        if service_factory is None:
            from artigas_mvp_backend.index_corpus import open_index
            from artigas_mvp_backend.services.chat import (
                ChatService,
                RetrievalService,
                create_chat_model,
            )
            from artigas_mvp_backend.services.embeddings import create_embeddings

            def default_service_factory(active_settings: Settings) -> ChatService:
                store = open_index(
                    CorpusPaths.repository_defaults(),
                    active_settings.chroma_persist_directory,
                    create_embeddings(active_settings),
                    embedding_model=active_settings.embedding_model,
                    dimensions=active_settings.embedding_dimensions,
                )
                return ChatService(
                    active_settings,
                    model=create_chat_model(active_settings),
                    retriever=RetrievalService(store),
                )

            service_factory = default_service_factory

        _atomic_write_json(output_path, payload)
        asyncio.run(
            _execute_pending_cases(
                pending,
                settings=settings,
                service_factory=service_factory,
                corpus=corpus,
                clock=clock,
                payload=payload,
                output_path=output_path,
            )
        )
    except EvaluationDataError as exc:
        print(str(exc), file=error_stream)
        return 2
    except Exception:
        print("No fue posible completar la ejecución de evaluación.", file=error_stream)
        return 1

    print(f"Resultados guardados en {output_path}", file=output_stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
