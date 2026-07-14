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
from artigas_mvp_backend.models import ChatRequest, Citation
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
        self, settings: Settings, service: object | None = None, *, disconnected: bool = False
    ) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(settings=settings, gemini_service=service))
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
    assert service.calls == [("Explique la federación.", "previous-1")]


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
