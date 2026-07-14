from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from artigas_mvp_backend.evaluate import (
    CaseSelectionError,
    load_cases,
    main,
    select_cases,
)

DATASET = Path(__file__).resolve().parents[2] / "evals" / "artigas-cases.yaml"


class FakeService:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.active = 0
        self.max_active = 0

    async def stream(self, *, message: str, previous_interaction_id: str | None):
        assert previous_interaction_id is None
        self.messages.append(message)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        yield SimpleNamespace(delta="respuesta parcial")
        self.active -= 1
        yield SimpleNamespace(
            interaction_id=f"interaction-{len(self.messages)}",
            final_text=f"Respuesta a: {message}",
            citations=(
                SimpleNamespace(
                    model_dump=lambda **_: {
                        "number": 1,
                        "title": "corpus.pdf",
                        "page": None,
                        "supported_text": "Respuesta",
                        "start_index": 0,
                        "end_index": 9,
                    }
                ),
            ),
            usage=SimpleNamespace(
                to_payload=lambda: SimpleNamespace(
                    model_dump=lambda **_: {
                        "input_tokens": 10,
                        "cached_input_tokens": 0,
                        "output_tokens": 5,
                        "thought_tokens": 2,
                        "total_tokens": 17,
                        "estimated_cost_usd": 0.000033,
                    }
                )
            ),
        )


def configured_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_FILE_SEARCH_STORE", "fileSearchStores/test")
    monkeypatch.setenv("GEMINI_MAX_OUTPUT_TOKENS", "4096")


def test_dataset_contains_exactly_fifteen_unique_valid_cases() -> None:
    cases = load_cases(DATASET)

    assert len(cases) == 15
    assert len({case.id for case in cases}) == 15
    assert all(case.prompt for case in cases)
    assert all(case.expected_behavior for case in cases)
    assert all(isinstance(case.requires_citation, bool) for case in cases)
    assert all(case.tags for case in cases)


def test_selects_one_case_or_all_cases() -> None:
    cases = load_cases(DATASET)

    assert [case.id for case in select_cases(cases, case_id="instructions-xiii")] == [
        "instructions-xiii"
    ]
    assert select_cases(cases, all_cases=True) == cases


def test_rejects_unknown_case_selection() -> None:
    with pytest.raises(CaseSelectionError):
        select_cases(load_cases(DATASET), case_id="missing-case")


def test_missing_cost_confirmation_makes_zero_live_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configured_environment(monkeypatch)
    factory_calls: list[Any] = []

    exit_code = main(
        ["--case", "instructions-xiii"],
        dataset_path=DATASET,
        results_dir=tmp_path,
        service_factory=lambda settings: factory_calls.append(settings),
    )

    assert exit_code == 2
    assert factory_calls == []
    assert list(tmp_path.iterdir()) == []
    output = capsys.readouterr().out
    assert "1 llamada" in output
    assert "4.096" in output
    assert "1.50" in output
    assert "9.00" in output
    assert "File Search" in output


def test_runs_one_selected_case_and_serializes_human_review_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_environment(monkeypatch)
    service = FakeService()

    exit_code = main(
        ["--case", "instructions-xiii", "--confirm-cost"],
        dataset_path=DATASET,
        results_dir=tmp_path,
        service_factory=lambda _settings: service,
        now=lambda: datetime(2026, 7, 14, 12, 34, 56, tzinfo=UTC),
        clock=iter([1.0, 1.125]).__next__,
    )

    assert exit_code == 0
    assert len(service.messages) == 1
    output_path = tmp_path / "20260714T123456Z.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["generated_at"] == "2026-07-14T12:34:56Z"
    assert len(payload["results"]) == 1
    result = payload["results"][0]
    assert result["id"] == "instructions-xiii"
    assert result["prompt"] == "¿Qué buscaban las Instrucciones del Año XIII?"
    assert result["expected_behavior"]
    assert result["requires_citation"] is True
    assert result["answer"].startswith("Respuesta a:")
    assert result["citations"][0]["title"] == "corpus.pdf"
    assert result["usage"]["thought_tokens"] == 2
    assert result["latency_ms"] == 125
    assert result["error"] is None
    assert "score" not in result
    assert "passed" not in result


def test_all_cases_execute_sequentially_as_independent_interactions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_environment(monkeypatch)
    service = FakeService()
    times = iter(float(index) for index in range(30))

    exit_code = main(
        ["--all", "--confirm-cost"],
        dataset_path=DATASET,
        results_dir=tmp_path,
        service_factory=lambda _settings: service,
        now=lambda: datetime(2026, 7, 14, tzinfo=UTC),
        clock=times.__next__,
    )

    assert exit_code == 0
    assert len(service.messages) == 15
    assert service.max_active == 1
    payload = json.loads((tmp_path / "20260714T000000Z.json").read_text())
    assert len(payload["results"]) == 15
