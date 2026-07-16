from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.evaluation_baseline import (
    ArtifactPaths,
    EvaluationBaselineError,
    current_artifact_hashes,
    promote_result,
    runtime_settings,
)


def _artifacts(tmp_path: Path) -> ArtifactPaths:
    paths = ArtifactPaths(
        pdf=tmp_path / "corpus.pdf",
        pages=tmp_path / "pages.json",
        manifest=tmp_path / "manifest.yaml",
        learning_map=tmp_path / "learning.yaml",
        prompt=tmp_path / "prompt.txt",
        prompt_loader=tmp_path / "prompt-loader.py",
        dataset=tmp_path / "cases.yaml",
        rubric=tmp_path / "rubric.yaml",
    )
    for field, path in vars(paths).items():
        path.write_text(f"{field}\n", encoding="utf-8")
    paths.dataset.write_text(
        "schema_version: 2\ncases:\n  - id: complete-case\n",
        encoding="utf-8",
    )
    return paths


def _result(path: Path, artifacts: ArtifactPaths) -> dict[str, object]:
    hashes = current_artifact_hashes(artifacts)
    payload: dict[str, object] = {
        "schema_version": 2,
        "generated_at": "2026-07-15T00:00:00Z",
        "dataset_sha256": hashes["evaluation_dataset"],
        "artifact_hashes": hashes,
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
        "embedding_model": "voyage-4-large",
        "settings": runtime_settings(Settings()),
        "cases": [
            {
                "id": "complete-case",
                "execution": "live",
                "critical": False,
                "core_historical": True,
                "human_review": ["historical_accuracy"],
                "turns": [{"checks": [{"passed": True}], "estimated_cost_usd": 0.01}],
                "operational_errors": [],
            }
        ],
        "review": {
            "reviewer": "Codex",
            "cases": {
                "complete-case": {
                    "scores": {"historical_accuracy": 4},
                    "notes": "Revisado.",
                    "reviewed_at": "2026-07-15T01:00:00Z",
                }
            },
            "performance": {
                "acknowledged": True,
                "notes": "Revisado.",
                "cost_regression_explanation": "",
                "latency_regression_explanation": "",
            },
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _passing_report():
    return SimpleNamespace(
        passed=True,
        category_averages={"historical_accuracy": 4.0},
        metrics={
            "median_cost_usd": 0.01,
            "p95_cost_usd": 0.02,
            "median_latency_ms": 100.0,
            "p95_latency_ms": 150.0,
        },
    )


def test_promotion_requires_exact_result_hash_and_writes_minimal_baseline(
    tmp_path: Path,
) -> None:
    artifacts = _artifacts(tmp_path)
    result = tmp_path / "result.json"
    _result(result, artifacts)
    baseline = tmp_path / "baseline.json"
    import hashlib

    result_hash = hashlib.sha256(result.read_bytes()).hexdigest()
    output = io.StringIO()

    promoted = promote_result(
        result,
        baseline_path=baseline,
        artifacts=artifacts,
        settings=Settings(),
        stdin=io.StringIO(result_hash + "\n"),
        stdout=output,
        now=lambda: datetime(2026, 7, 15, 2, tzinfo=UTC),
        gate_evaluator=lambda *_args, **_kwargs: _passing_report(),
    )

    saved = json.loads(baseline.read_text(encoding="utf-8"))
    assert promoted == saved
    assert saved["schema_version"] == 1
    assert saved["reviewer"] == "Codex"
    assert saved["promoted_at"] == "2026-07-15T02:00:00Z"
    assert saved["source_result_sha256"] == result_hash
    assert saved["artifact_hashes"] == current_artifact_hashes(artifacts)
    assert saved["provider"] == "groq"
    assert saved["model"] == "openai/gpt-oss-120b"
    assert saved["embedding_model"] == "voyage-4-large"
    assert saved["settings"]["embedding_provider"] == "voyage"
    assert saved["settings"]["embedding_dimensions"] == 1024
    assert saved["settings"]["embedding_dtype"] == "float"
    assert saved["settings"]["distance"] == "cosine"
    assert saved["settings"]["max_output_tokens"] == 4096
    assert saved["settings"]["chat_reasoning_effort"] == "medium"
    assert saved["results"] == [
        {
            "id": "complete-case",
            "deterministic_passed": True,
            "operational_error_count": 0,
            "scores": {"historical_accuracy": 4},
        }
    ]
    assert saved["scores"] == {"historical_accuracy": 4.0}
    assert saved["summary"]["p95_cost_usd"] == 0.02
    serialized = json.dumps(saved).casefold()
    assert "gemini_api_key" not in serialized
    assert "file_search_store" not in serialized
    assert "cases" not in saved
    assert not list(tmp_path.glob(".*baseline*.tmp"))
    assert result_hash in output.getvalue()


def test_promotion_rejects_a_different_reasoning_effort(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    result = tmp_path / "result.json"
    _result(result, artifacts)

    with pytest.raises(EvaluationBaselineError, match="configuración"):
        promote_result(
            result,
            baseline_path=tmp_path / "baseline.json",
            artifacts=artifacts,
            settings=Settings(chat_reasoning_effort="high"),
            stdin=io.StringIO("unused\n"),
            stdout=io.StringIO(),
            gate_evaluator=lambda *_args, **_kwargs: _passing_report(),
        )

    assert not (tmp_path / "baseline.json").exists()


@pytest.mark.parametrize(
    "mutation", ["incomplete-review", "failed-gate", "changed-hash", "settings"]
)
def test_promotion_refuses_unqualified_results(tmp_path: Path, mutation: str) -> None:
    artifacts = _artifacts(tmp_path)
    result = tmp_path / "result.json"
    payload = _result(result, artifacts)
    report = _passing_report()
    if mutation == "incomplete-review":
        payload["review"] = {}
        result.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "failed-gate":
        report = SimpleNamespace(passed=False)
    elif mutation == "changed-hash":
        artifacts.manifest.write_text("changed\n", encoding="utf-8")
    elif mutation == "settings":
        payload["settings"]["max_output_tokens"] = 2048  # type: ignore[index]
        result.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationBaselineError):
        promote_result(
            result,
            baseline_path=tmp_path / "baseline.json",
            artifacts=artifacts,
            settings=Settings(),
            stdin=io.StringIO("irrelevant\n"),
            stdout=io.StringIO(),
            gate_evaluator=lambda *_args, **_kwargs: report,
        )

    assert not (tmp_path / "baseline.json").exists()


def test_promotion_refuses_partial_case_set_and_wrong_confirmation(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    result = tmp_path / "result.json"
    payload = _result(result, artifacts)
    payload["cases"] = []
    result.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EvaluationBaselineError, match="casos"):
        promote_result(
            result,
            baseline_path=tmp_path / "baseline.json",
            artifacts=artifacts,
            settings=Settings(),
            stdin=io.StringIO("wrong\n"),
            stdout=io.StringIO(),
            gate_evaluator=lambda *_args, **_kwargs: _passing_report(),
        )

    _result(result, artifacts)
    with pytest.raises(EvaluationBaselineError, match="confirmación"):
        promote_result(
            result,
            baseline_path=tmp_path / "baseline.json",
            artifacts=artifacts,
            settings=Settings(),
            stdin=io.StringIO("wrong\n"),
            stdout=io.StringIO(),
            gate_evaluator=lambda *_args, **_kwargs: _passing_report(),
        )


def test_replacement_requires_both_baseline_and_result_hashes(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    result = tmp_path / "result.json"
    _result(result, artifacts)
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"schema_version": 1, "old": true}\n', encoding="utf-8")
    import hashlib

    old_hash = hashlib.sha256(baseline.read_bytes()).hexdigest()
    result_hash = hashlib.sha256(result.read_bytes()).hexdigest()
    before = baseline.read_bytes()

    with pytest.raises(EvaluationBaselineError, match="confirmación"):
        promote_result(
            result,
            baseline_path=baseline,
            artifacts=artifacts,
            settings=Settings(),
            stdin=io.StringIO(result_hash + "\n"),
            stdout=io.StringIO(),
            gate_evaluator=lambda *_args, **_kwargs: _passing_report(),
        )
    assert baseline.read_bytes() == before

    promote_result(
        result,
        baseline_path=baseline,
        artifacts=artifacts,
        settings=Settings(),
        stdin=io.StringIO(f"{old_hash} {result_hash}\n"),
        stdout=io.StringIO(),
        gate_evaluator=lambda *_args, **_kwargs: _passing_report(),
    )
    assert json.loads(baseline.read_text(encoding="utf-8"))["source_result_sha256"] == result_hash


def test_atomic_replace_failure_preserves_existing_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(tmp_path)
    result = tmp_path / "result.json"
    _result(result, artifacts)
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"schema_version": 1, "old": true}\n', encoding="utf-8")
    import hashlib

    confirmation = (
        hashlib.sha256(baseline.read_bytes()).hexdigest()
        + " "
        + hashlib.sha256(result.read_bytes()).hexdigest()
        + "\n"
    )
    from artigas_mvp_backend import evaluation_baseline

    monkeypatch.setattr(
        evaluation_baseline.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )
    before = baseline.read_bytes()
    with pytest.raises(EvaluationBaselineError, match="línea base"):
        promote_result(
            result,
            baseline_path=baseline,
            artifacts=artifacts,
            settings=Settings(),
            stdin=io.StringIO(confirmation),
            stdout=io.StringIO(),
            gate_evaluator=lambda *_args, **_kwargs: _passing_report(),
        )
    assert baseline.read_bytes() == before
    assert not list(tmp_path.glob(".*baseline*.tmp"))


def test_prompt_hash_binds_template_and_runtime_injection_source(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    before = current_artifact_hashes(artifacts)

    artifacts.prompt_loader.write_text("DOCUMENTARY_LIMIT_RESPONSE = 'changed'\n", encoding="utf-8")

    after = current_artifact_hashes(artifacts)
    assert after["prompt_runtime"] != before["prompt_runtime"]


def test_repository_prompt_hash_uses_shared_template_and_profile_loader() -> None:
    artifacts = ArtifactPaths.repository_defaults()

    assert artifacts.prompt.name == "historical_character.txt"
    assert artifacts.prompt_loader.name == "__init__.py"


def test_promotion_rejects_result_changed_during_gate(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    result = tmp_path / "result.json"
    _result(result, artifacts)

    def mutating_gate(*_args, **_kwargs):
        with result.open("a", encoding="utf-8") as target:
            target.write(" ")
        return _passing_report()

    with pytest.raises(EvaluationBaselineError, match=r"resultado.*cambi"):
        promote_result(
            result,
            baseline_path=tmp_path / "baseline.json",
            artifacts=artifacts,
            settings=Settings(),
            stdin=io.StringIO("unused\n"),
            stdout=io.StringIO(),
            gate_evaluator=mutating_gate,
        )


@pytest.mark.parametrize("mutation", ["artifact", "baseline"])
def test_promotion_rejects_files_changed_during_confirmation(tmp_path: Path, mutation: str) -> None:
    artifacts = _artifacts(tmp_path)
    result = tmp_path / "result.json"
    _result(result, artifacts)
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"schema_version": 1, "old": true}\n', encoding="utf-8")
    import hashlib

    confirmation = (
        hashlib.sha256(baseline.read_bytes()).hexdigest()
        + " "
        + hashlib.sha256(result.read_bytes()).hexdigest()
        + "\n"
    )

    class MutatingInput(io.StringIO):
        def readline(self, *args, **kwargs):
            value = super().readline(*args, **kwargs)
            if mutation == "artifact":
                artifacts.learning_map.write_text("changed\n", encoding="utf-8")
            else:
                baseline.write_text('{"schema_version": 1, "changed": true}\n', encoding="utf-8")
            return value

    with pytest.raises(EvaluationBaselineError, match="cambiaron"):
        promote_result(
            result,
            baseline_path=baseline,
            artifacts=artifacts,
            settings=Settings(),
            stdin=MutatingInput(confirmation),
            stdout=io.StringIO(),
            gate_evaluator=lambda *_args, **_kwargs: _passing_report(),
        )
