from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import SecretStr, ValidationError

import artigas_mvp_backend.api.chat as chat_module
import artigas_mvp_backend.main as main_module
from artigas_mvp_backend.api.chat import chat
from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.main import _validation_payload, create_app
from artigas_mvp_backend.models import ChatRequest, Citation, LearningState
from artigas_mvp_backend.services.gemini import (
    GeminiCompleted,
    GeminiServiceError,
    GeminiTextDelta,
)
from artigas_mvp_backend.services.usage import NormalizedUsage

USAGE = NormalizedUsage(1, 0, 2, 0, 3, Decimal("0.0000195"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeService:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.calls: list[tuple[str, str | None]] = []

    async def stream(
        self, *, message: str, previous_interaction_id: str | None
    ) -> AsyncIterator[GeminiTextDelta | GeminiCompleted]:
        self.calls.append((message, previous_interaction_id))
        for event in self.events:
            if isinstance(event, Exception):
                raise event
            yield event  # type: ignore[misc]


def configured_settings(**updates: object) -> Settings:
    values: dict[str, object] = {
        "gemini_api_key": SecretStr("test-key"),
        "gemini_file_search_store": "fileSearchStores/test",
    }
    values.update(updates)
    return Settings.model_validate(values)


class FakeRequest:
    def __init__(
        self,
        settings: Settings,
        service: object | None = None,
        *,
        corpus_service: object | None = None,
        disconnected: bool = False,
    ) -> None:
        empty_corpus = SimpleNamespace(
            learning_map=SimpleNamespace(topics=(), actions=()),
            validate_action_id=lambda _action_id: None,
        )
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                settings=settings,
                gemini_service=service,
                corpus_service=corpus_service or empty_corpus,
            )
        )
        self.disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self.disconnected


async def response_text(response: object) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def test_health_route_is_preserved() -> None:
    app = create_app(settings=Settings())
    assert any(getattr(route, "path", None) == "/api/health" for route in app.routes)


@pytest.mark.anyio
async def test_missing_runtime_configuration_is_json_before_stream() -> None:
    response = await chat(
        cast(Request, FakeRequest(Settings())), ChatRequest(message="Hola", turn_number=1)
    )
    assert response.status_code == 503
    assert json.loads(bytes(response.body)) == {
        "code": "configuration_error",
        "message": "La configuración de Gemini no está completa.",
        "retryable": False,
    }

    missing_store = Settings(gemini_api_key=SecretStr("test-key"))
    response = await chat(
        cast(Request, FakeRequest(missing_store)), ChatRequest(message="Hola", turn_number=1)
    )
    assert response.status_code == 503


def test_request_schema_rejects_invalid_values_before_stream() -> None:
    for values in (
        {"message": "  ", "turn_number": 1},
        {"message": "x" * 2001, "turn_number": 1},
        {"message": "Hola", "turn_number": 13},
    ):
        with pytest.raises(ValidationError):
            ChatRequest.model_validate(values)


@pytest.mark.parametrize(
    ("values", "status", "code", "message"),
    [
        (
            {"message": " ", "turn_number": 1},
            422,
            "invalid_request",
            "La pregunta no es válida.",
        ),
        (
            {"message": "x" * 2001, "turn_number": 1},
            422,
            "invalid_request",
            "La pregunta no puede superar los 2.000 caracteres.",
        ),
        (
            {"message": "Hola", "turn_number": 13},
            409,
            "turn_limit_reached",
            (
                "Esta conversación alcanzó el límite de 12 preguntas. "
                "Inicie una nueva conversación para continuar."
            ),
        ),
    ],
)
def test_validation_payload_has_exact_public_mapping(
    values: dict[str, object], status: int, code: str, message: str
) -> None:
    with pytest.raises(ValidationError) as validation:
        ChatRequest.model_validate(values)
    mapped_status, payload = _validation_payload(RequestValidationError(validation.value.errors()))
    assert (mapped_status, payload.code, payload.message) == (status, code, message)


@pytest.mark.anyio
async def test_stream_frames_text_and_canonical_completion() -> None:
    service = FakeService(
        [
            GeminiTextDelta("Defendí "),
            GeminiCompleted(
                interaction_id="interaction-1",
                final_text="Defendí la federación.",
                citations=(
                    Citation(
                        number=1,
                        title="corpus.pdf",
                        page=None,
                        supported_text="federación",
                        start_index=11,
                        end_index=21,
                    ),
                ),
                usage=USAGE,
            ),
        ]
    )
    response = await chat(
        cast(Request, FakeRequest(configured_settings(), service)),
        ChatRequest(
            message="  Explique la federación.  ",
            previous_interaction_id="previous-1",
            turn_number=12,
        ),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    body = await response_text(response)
    assert 'event: text\ndata: {"delta":"Defendí "}\n\n' in body
    assert "event: complete\n" in body
    assert '"interaction_id":"interaction-1"' in body
    assert '"final_text":"Defendí la federación."' in body
    assert '"answer_status":"documented"' in body
    assert '"sources":[{"id":"unmapped-1"' in body
    assert '"supported_text":"federación"' in body
    assert '"educational_actions":[]' in body
    assert '"learning_state":{"shown_action_ids":[]' in body
    assert service.calls == [("Explique la federación.", "previous-1")]


@pytest.mark.anyio
async def test_canonical_completion_enriches_mapped_corpus_evidence(tmp_path) -> None:
    from corpus_fixtures import make_corpus_paths

    from artigas_mvp_backend.services.corpus import CorpusService

    corpus = CorpusService.load(make_corpus_paths(tmp_path))
    service = FakeService(
        [
            GeminiCompleted(
                interaction_id="interaction-mapped",
                final_text="Defendí la autonomía provincial.",
                citations=(
                    Citation(
                        number=1,
                        title="corpus.pdf",
                        page=2,
                        supported_text="autonomía provincial",
                        start_index=11,
                        end_index=31,
                    ),
                ),
                usage=USAGE,
            )
        ]
    )
    response = await chat(
        cast(
            Request,
            FakeRequest(configured_settings(), service, corpus_service=corpus),
        ),
        ChatRequest(message="Explique la autonomía.", turn_number=1),
    )

    body = await response_text(response)

    assert '"answer_status":"documented"' in body
    assert '"id":"document-DOC-001"' in body
    assert '"document_id":"DOC-001"' in body
    assert '"pdf_url":"/api/corpus/artigas#page=2"' in body
    assert '"type":"deepen","label":"Profundizar","action_id":"active-action"' in body
    assert '"type":"source","label":"Examinar la fuente"' in body
    assert '"shown_action_ids":["active-action"]' in body
    assert service.calls == [("Explique la autonomía.", None)]


@pytest.mark.anyio
async def test_completion_advances_and_returns_normalized_learning_state(tmp_path) -> None:
    from corpus_fixtures import make_corpus_paths

    from artigas_mvp_backend.services.corpus import CorpusService

    corpus = CorpusService.load(make_corpus_paths(tmp_path))
    service = FakeService(
        [
            GeminiCompleted(
                interaction_id="interaction-learning",
                final_text="Defendí la autonomía provincial.",
                citations=(
                    Citation(
                        number=1,
                        title="corpus.pdf",
                        page=2,
                        supported_text="autonomía provincial",
                        start_index=11,
                        end_index=31,
                    ),
                ),
                usage=USAGE,
            )
        ]
    )
    response = await chat(
        cast(Request, FakeRequest(configured_settings(), service, corpus_service=corpus)),
        ChatRequest(
            message="Continúe.",
            turn_number=2,
            learning_state=LearningState(
                shown_action_ids=["active-action", "stale"],
                submitted_action_id="active-action",
            ),
        ),
    )

    body = await response_text(response)

    assert '"educational_actions":[{"type":"source"' in body
    assert '"shown_action_ids":["active-action"]' in body
    assert '"selected_action_ids":["active-action"]' in body
    assert '"submitted_action_id":null' in body
    assert '"topic_depths":{"federalism-and-provincial-autonomy":"deeper"}' in body


@pytest.mark.anyio
async def test_local_enrichment_failure_is_a_safe_terminal_sse(monkeypatch) -> None:
    class BrokenCorpus:
        def resolve_document(self, _page: int) -> None:
            raise RuntimeError("sensitive local path")

    service = FakeService(
        [
            GeminiCompleted(
                interaction_id="interaction-broken",
                final_text="Respuesta canónica.",
                citations=(
                    Citation(
                        number=1,
                        title="corpus.pdf",
                        page=1,
                        supported_text="Respuesta",
                        start_index=0,
                        end_index=9,
                    ),
                ),
                usage=USAGE,
            )
        ]
    )
    logged: list[dict[str, object]] = []
    monkeypatch.setattr(chat_module, "log_error", lambda **values: logged.append(values))
    response = await chat(
        cast(
            Request,
            FakeRequest(configured_settings(), service, corpus_service=BrokenCorpus()),
        ),
        ChatRequest(message="Pregunta", turn_number=1),
    )

    body = await response_text(response)

    assert body.count("event: error") == 1
    assert body.count("event: complete") == 0
    assert '"code":"corpus_unavailable"' in body
    assert "sensitive local path" not in body
    assert logged[0]["error_code"] == "corpus_unavailable"
    assert service.calls == [("Pregunta", None)]


@pytest.mark.anyio
async def test_service_error_is_safe_terminal_sse() -> None:
    service = FakeService(
        [
            GeminiServiceError(
                code="provider_timeout",
                user_message="La respuesta demoró demasiado.",
                retryable=True,
                transient=True,
            )
        ]
    )
    response = await chat(
        cast(Request, FakeRequest(configured_settings(), service)),
        ChatRequest(message="Hola", turn_number=1),
    )
    assert response.status_code == 200
    body = await response_text(response)
    assert body.count("event: error") == 1
    assert '"code":"provider_timeout"' in body
    assert "traceback" not in body.lower()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "retryable"),
    [
        ("provider_rate_limit", False),
        ("provider_error", True),
        ("citation_processing_error", False),
    ],
)
async def test_other_service_errors_are_single_safe_terminal_events(
    code: str, retryable: bool
) -> None:
    error = GeminiServiceError(
        code=cast(Any, code),
        user_message="No fue posible completar la respuesta.",
        retryable=retryable,
        transient=retryable,
    )
    response = await chat(
        cast(Request, FakeRequest(configured_settings(), FakeService([error]))),
        ChatRequest(message="Hola", turn_number=1),
    )
    body = await response_text(response)
    assert body.count("event: error") == 1
    assert body.count("event: complete") == 0
    assert code in body


@pytest.mark.anyio
async def test_disconnect_closes_stream_without_terminal_event() -> None:
    class ClosingService:
        closed = False

        async def stream(self, **_: object):
            try:
                yield GeminiTextDelta("texto")
            finally:
                self.closed = True

    service = ClosingService()
    cancelled: list[dict[str, object]] = []
    original = chat_module.log_cancelled
    chat_module.log_cancelled = lambda **kwargs: cancelled.append(kwargs)
    response = await chat(
        cast(Request, FakeRequest(configured_settings(), service, disconnected=True)),
        ChatRequest(message="Hola", turn_number=1),
    )
    try:
        assert await response_text(response) == ""
    finally:
        chat_module.log_cancelled = original
    assert service.closed
    assert cancelled
    assert cancelled[0]["model"] == "gemini-3.5-flash"


@pytest.mark.anyio
async def test_lifespan_creates_and_closes_only_owned_service(monkeypatch) -> None:
    closed: list[bool] = []

    class AsyncClient:
        async def aclose(self) -> None:
            closed.append(True)

    owned = SimpleNamespace(client=SimpleNamespace(aio=AsyncClient()))
    monkeypatch.setattr(main_module, "GeminiService", lambda settings: owned)
    app = create_app(settings=configured_settings())

    async with app.router.lifespan_context(app):
        assert app.state.gemini_service is owned

    assert closed == [True]


@pytest.mark.anyio
async def test_lifespan_loads_owned_corpus_once_without_contacting_gemini(
    monkeypatch, tmp_path
) -> None:
    from corpus_fixtures import make_corpus_paths

    paths = make_corpus_paths(tmp_path)
    loaded: list[object] = []
    corpus = object()

    def load(injected_paths, *, production_ready=False):
        loaded.append((injected_paths, production_ready))
        return corpus

    monkeypatch.setattr(main_module.CorpusService, "load", load)
    monkeypatch.setattr(
        main_module,
        "GeminiService",
        lambda _settings: pytest.fail("Gemini was contacted"),
    )
    app = create_app(settings=Settings(), corpus_paths=paths)

    async with app.router.lifespan_context(app):
        assert app.state.corpus_service is corpus

    assert loaded == [(paths, False)]


@pytest.mark.anyio
async def test_lifespan_preserves_injected_corpus_service(monkeypatch) -> None:
    corpus = object()
    monkeypatch.setattr(
        main_module.CorpusService,
        "load",
        lambda *_args, **_kwargs: pytest.fail("loaded corpus files"),
    )
    app = create_app(settings=Settings(), corpus_service=corpus)

    async with app.router.lifespan_context(app):
        assert app.state.corpus_service is corpus
