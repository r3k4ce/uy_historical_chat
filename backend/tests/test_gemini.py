from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.services.gemini import (
    GeminiCompleted,
    GeminiService,
    GeminiServiceError,
    GeminiTextDelta,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def event(event_type: str, **values: Any) -> Any:
    return SimpleNamespace(event_type=event_type, **values)


def stored_interaction(
    text: str = "La libertad.",
    *,
    status: str = "completed",
    reason: str | None = None,
    annotations: list[Any] | None = None,
    output_tokens: int = 20,
    thought_tokens: int = 5,
) -> Any:
    content = SimpleNamespace(
        type="output_text",
        text=text,
        annotations=annotations or [],
    )
    return SimpleNamespace(
        id="interactions/abc",
        status=status,
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        steps=[SimpleNamespace(type="message", role="assistant", content=[content])],
        usage=SimpleNamespace(
            total_input_tokens=100,
            total_cached_tokens=10,
            total_output_tokens=output_tokens,
            total_thought_tokens=thought_tokens,
            total_tokens=100 + output_tokens + thought_tokens,
        ),
    )


class FakeStream:
    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.closed = False

    def __aiter__(self) -> AsyncIterator[Any]:
        return self

    async def __anext__(self) -> Any:
        if not self.items:
            raise StopAsyncIteration
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def aclose(self) -> None:
        self.closed = True


class BlockingStream(FakeStream):
    def __init__(self) -> None:
        super().__init__([])
        self.started = asyncio.Event()

    async def __anext__(self) -> Any:
        self.started.set()
        await asyncio.Event().wait()
        raise StopAsyncIteration


class FakeInteractions:
    def __init__(self, attempts: list[Any], stored: Any | list[Any] | None = None) -> None:
        self.attempts = attempts
        self.stored = stored or stored_interaction()
        self.create_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []

    async def create(self, **kwargs: Any) -> Any:
        self.create_calls.append(kwargs)
        attempt = self.attempts.pop(0)
        if isinstance(attempt, BaseException):
            raise attempt
        return attempt

    async def get(self, interaction_id: str) -> Any:
        self.get_calls.append(interaction_id)
        if isinstance(self.stored, list):
            if len(self.stored) > 1:
                return self.stored.pop(0)
            return self.stored[0]
        return self.stored


class FakeClient:
    def __init__(self, interactions: FakeInteractions) -> None:
        self.aio = SimpleNamespace(interactions=interactions)


def configured_settings(**changes: Any) -> Settings:
    return Settings(
        gemini_api_key=SecretStr("test-key"),
        gemini_file_search_store="fileSearchStores/test-store",
        **changes,
    )


def complete_stream(*deltas: str) -> FakeStream:
    items = [
        event(
            "interaction.step.delta",
            delta=SimpleNamespace(type="text", text=delta),
        )
        for delta in deltas
    ]
    items.append(
        event(
            "interaction.complete",
            interaction=SimpleNamespace(id="interactions/abc", status="completed"),
        )
    )
    return FakeStream(items)


async def collect(service: GeminiService, *, message: str = "pregunta", **kwargs: Any) -> list[Any]:
    return [item async for item in service.stream(message=message, **kwargs)]


@pytest.mark.anyio
async def test_request_reapplies_exact_configuration_on_first_and_followup() -> None:
    interactions = FakeInteractions([complete_stream(), complete_stream()])
    service = GeminiService(configured_settings(), client=FakeClient(interactions))

    await collect(service, previous_interaction_id=None)
    await collect(
        service,
        message="Continuación histórica.",
        previous_interaction_id="interactions/previous",
    )

    first, followup = interactions.create_calls
    for request in (first, followup):
        assert request["model"] == "gemini-3.5-flash"
        assert "simulación histórica" in request["system_instruction"]
        assert "No generes acciones educativas" in request["system_instruction"]
        assert "3. Alcance y límites" in request["system_instruction"]
        assert request["tools"] == [
            {
                "type": "file_search",
                "file_search_store_names": ["fileSearchStores/test-store"],
            }
        ]
        assert request["generation_config"] == {
            "thinking_level": "low",
            "max_output_tokens": 4096,
            "temperature": 0.4,
            "tool_choice": "validated",
        }
        assert request["stream"] is True
    assert "previous_interaction_id" not in first
    assert followup["previous_interaction_id"] == "interactions/previous"


@pytest.mark.anyio
async def test_non_question_followup_retains_conversational_tool_choice() -> None:
    interactions = FakeInteractions([complete_stream()])
    service = GeminiService(configured_settings(), client=FakeClient(interactions))

    _ = [
        item
        async for item in service.stream(
            message="Gracias por la explicación.",
            previous_interaction_id="interactions/previous",
        )
    ]

    assert interactions.create_calls[0]["generation_config"]["tool_choice"] == "validated"


@pytest.mark.anyio
async def test_uncited_question_followup_retries_grounding_without_streaming_second_draft() -> None:
    annotation = {
        "type": "file_citation",
        "source_id": "files/1",
        "file_name": "artigas.pdf",
        "page_number": 3,
        "start_index": 0,
        "end_index": len(b"Respuesta documentada"),
    }
    interactions = FakeInteractions(
        [complete_stream("Primer borrador"), complete_stream("Segundo borrador")],
        stored=[
            stored_interaction("Primer borrador"),
            stored_interaction("Respuesta documentada", annotations=[annotation]),
        ],
    )
    service = GeminiService(configured_settings(), client=FakeClient(interactions))

    events = await collect(
        service,
        message="¿Pregunta histórica?",
        previous_interaction_id="interactions/previous",
    )

    assert [event.delta for event in events if isinstance(event, GeminiTextDelta)] == [
        "Primer borrador"
    ]
    completed = next(event for event in events if isinstance(event, GeminiCompleted))
    assert completed.final_text == "Respuesta documentada"
    assert len(completed.citations) == 1
    assert interactions.create_calls[1]["input"].startswith("Consulta nuevamente el corpus")
    assert interactions.create_calls[1]["previous_interaction_id"] == "interactions/previous"


@pytest.mark.anyio
async def test_grounding_retry_failure_returns_the_streamed_fallback_completion() -> None:
    interactions = FakeInteractions(
        [complete_stream("Borrador"), RuntimeError("retry failed")],
        stored=stored_interaction("Borrador"),
    )
    service = GeminiService(configured_settings(), client=FakeClient(interactions))

    events = await collect(
        service,
        message="¿Pregunta histórica?",
        previous_interaction_id="interactions/previous",
    )

    completed = next(event for event in events if isinstance(event, GeminiCompleted))
    assert completed.final_text == "Borrador"
    assert completed.citations == ()


@pytest.mark.anyio
async def test_uncited_grounding_retry_keeps_fallback_and_combines_usage() -> None:
    first_stream = complete_stream("Primer borrador")
    second_stream = complete_stream("Segundo borrador")
    interactions = FakeInteractions(
        [first_stream, second_stream],
        stored=[
            stored_interaction("Primer borrador", output_tokens=20),
            stored_interaction("Segundo borrador", output_tokens=30),
        ],
    )
    service = GeminiService(configured_settings(), client=FakeClient(interactions))

    events = await collect(
        service,
        message="¿Pregunta histórica?",
        previous_interaction_id="interactions/previous",
    )

    completed = next(event for event in events if isinstance(event, GeminiCompleted))
    assert completed.final_text == "Primer borrador"
    assert completed.citations == ()
    assert completed.usage.output_tokens == 50
    assert first_stream.closed is True
    assert second_stream.closed is True


@pytest.mark.anyio
async def test_nonaccepted_terminal_interaction_retries_without_duplicate_deltas() -> None:
    first_stream = complete_stream("Primer borrador")
    second_stream = complete_stream("Segundo borrador")
    interactions = FakeInteractions(
        [first_stream, second_stream],
        stored=[
            stored_interaction("Primer borrador", status="failed", output_tokens=20),
            stored_interaction("Respuesta final", output_tokens=30),
        ],
    )
    service = GeminiService(configured_settings(), client=FakeClient(interactions))

    events = await collect(service, previous_interaction_id=None)

    assert [event.delta for event in events if isinstance(event, GeminiTextDelta)] == [
        "Primer borrador"
    ]
    completed = next(event for event in events if isinstance(event, GeminiCompleted))
    assert completed.final_text == "Respuesta final"
    assert completed.usage.output_tokens == 50
    assert first_stream.closed is True
    assert second_stream.closed is True


@pytest.mark.anyio
async def test_terminal_retry_streams_when_the_failed_attempt_emitted_no_text() -> None:
    first_stream = complete_stream()
    second_stream = complete_stream("Respuesta del reintento")
    interactions = FakeInteractions(
        [first_stream, second_stream],
        stored=[
            stored_interaction("", status="failed"),
            stored_interaction("Respuesta del reintento"),
        ],
    )
    service = GeminiService(configured_settings(), client=FakeClient(interactions))

    events = await collect(service, previous_interaction_id=None)

    assert [event.delta for event in events if isinstance(event, GeminiTextDelta)] == [
        "Respuesta del reintento"
    ]
    assert first_stream.closed is True
    assert second_stream.closed is True


@pytest.mark.anyio
async def test_stream_yields_text_and_reconciles_canonical_completion() -> None:
    annotation = {
        "type": "file_citation",
        "source_id": "files/1",
        "file_name": "artigas.pdf",
        "page_number": 3,
        "start_index": 0,
        "end_index": len(b"La libertad"),
    }
    stored = stored_interaction("La libertad.", annotations=[annotation])
    interactions = FakeInteractions(
        [
            FakeStream(
                [
                    event("unknown.event"),
                    event(
                        "interaction.step.delta",
                        delta=SimpleNamespace(type="image", text="ignored"),
                    ),
                    event(
                        "interaction.step.delta",
                        delta=SimpleNamespace(type="text", text="La "),
                    ),
                    event(
                        "interaction.step.delta",
                        delta=SimpleNamespace(type="text", text="libertad"),
                    ),
                    event(
                        "interaction.complete",
                        interaction=SimpleNamespace(id="interactions/abc"),
                    ),
                ]
            )
        ],
        stored,
    )

    result = await collect(
        GeminiService(configured_settings(), client=FakeClient(interactions)),
        previous_interaction_id=None,
    )

    assert result[:2] == [GeminiTextDelta("La "), GeminiTextDelta("libertad")]
    completed = result[-1]
    assert isinstance(completed, GeminiCompleted)
    assert completed.interaction_id == "interactions/abc"
    assert completed.final_text == "La libertad."
    assert completed.citations[0].title == "artigas.pdf"
    assert completed.citations[0].supported_text == "La libertad"
    assert completed.usage.total_tokens == 125
    assert completed.usage.thought_tokens == 5
    assert interactions.get_calls == ["interactions/abc"]


@pytest.mark.anyio
@pytest.mark.parametrize("stale_status", ["in_progress", "incomplete"])
async def test_reconciles_stale_canonical_status_without_regenerating(
    stale_status: str,
) -> None:
    interactions = FakeInteractions(
        [complete_stream("Respuesta")],
        [
            stored_interaction("Respuesta", status=stale_status),
            stored_interaction("Respuesta", status="completed"),
        ],
    )

    result = await collect(
        GeminiService(configured_settings(), client=FakeClient(interactions)),
        previous_interaction_id=None,
    )

    assert isinstance(result[-1], GeminiCompleted)
    assert result[-1].final_text == "Respuesta"
    assert interactions.get_calls == ["interactions/abc", "interactions/abc"]
    assert len(interactions.create_calls) == 1


@pytest.mark.anyio
async def test_persistent_stale_canonical_status_retries_once_then_fails() -> None:
    stale = stored_interaction("Respuesta", status="incomplete")
    interactions = FakeInteractions([complete_stream("Respuesta")], [stale])

    with pytest.raises(GeminiServiceError) as exc_info:
        await collect(
            GeminiService(configured_settings(), client=FakeClient(interactions)),
            previous_interaction_id=None,
        )

    assert exc_info.value.code == "provider_error"
    assert len(interactions.get_calls) > 1
    assert len(interactions.create_calls) == 2


@pytest.mark.anyio
async def test_cancellation_during_canonical_reconciliation_closes_stream() -> None:
    first_get = asyncio.Event()

    class SignalingInteractions(FakeInteractions):
        async def get(self, interaction_id: str) -> Any:
            stored = await super().get(interaction_id)
            first_get.set()
            return stored

    stream = complete_stream("Respuesta")
    interactions = SignalingInteractions(
        [stream],
        [stored_interaction("Respuesta", status="incomplete")],
    )
    service = GeminiService(configured_settings(), client=FakeClient(interactions))

    async def consume() -> None:
        async for _ in service.stream(message="pregunta", previous_interaction_id=None):
            pass

    task = asyncio.create_task(consume())
    await first_get.wait()
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert stream.closed is True
    assert len(interactions.create_calls) == 1


@pytest.mark.anyio
async def test_accepts_nonempty_output_limit_incomplete_response() -> None:
    stored = stored_interaction(
        "Respuesta truncada", status="incomplete", reason="max_output_tokens"
    )
    interactions = FakeInteractions([complete_stream()], stored)

    result = await collect(
        GeminiService(configured_settings(), client=FakeClient(interactions)),
        previous_interaction_id=None,
    )

    assert isinstance(result[-1], GeminiCompleted)
    assert result[-1].final_text == "Respuesta truncada"


@pytest.mark.anyio
async def test_accepts_reasonless_incomplete_response_at_configured_token_limit() -> None:
    stored = stored_interaction(
        "Respuesta truncada",
        status="incomplete",
        output_tokens=37,
        thought_tokens=659,
    )
    interactions = FakeInteractions([complete_stream()], stored)

    result = await collect(
        GeminiService(
            configured_settings(gemini_max_output_tokens=700),
            client=FakeClient(interactions),
        ),
        previous_interaction_id=None,
    )

    assert isinstance(result[-1], GeminiCompleted)
    assert result[-1].final_text == "Respuesta truncada"
    assert interactions.get_calls == ["interactions/abc"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stored", "expected_code"),
    [
        (stored_interaction("", status="incomplete", reason="max_output_tokens"), "provider_error"),
        (stored_interaction("texto", status="failed"), "provider_error"),
    ],
)
async def test_rejects_other_unsuccessful_terminal_states(stored: Any, expected_code: str) -> None:
    interactions = FakeInteractions([complete_stream()], stored)

    with pytest.raises(GeminiServiceError) as exc_info:
        await collect(
            GeminiService(configured_settings(), client=FakeClient(interactions)),
            previous_interaction_id=None,
        )

    assert exc_info.value.code == expected_code


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__("sensitive provider detail")
        self.status_code = status_code


class RequestTimeout(Exception):
    pass


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failure", "code", "retryable", "attempts"),
    [
        (RequestTimeout("secret"), "provider_timeout", True, 2),
        (StatusError(429), "provider_rate_limit", False, 1),
        (StatusError(400), "provider_error", False, 1),
        (StatusError(500), "provider_error", True, 2),
        (RuntimeError("secret"), "provider_error", False, 1),
    ],
)
async def test_maps_provider_errors_without_exposing_raw_messages(
    failure: Exception, code: str, retryable: bool, attempts: int
) -> None:
    interactions = FakeInteractions([failure] * attempts)

    with pytest.raises(GeminiServiceError) as exc_info:
        await collect(
            GeminiService(configured_settings(), client=FakeClient(interactions)),
            previous_interaction_id=None,
        )

    assert len(interactions.create_calls) == attempts
    assert exc_info.value.code == code
    assert exc_info.value.retryable is retryable
    assert "secret" not in exc_info.value.user_message


@pytest.mark.anyio
async def test_detects_timeout_in_bounded_cause_chain() -> None:
    wrapped = RuntimeError("provider wrapper")
    wrapped.__cause__ = RequestTimeout("private timeout")
    interactions = FakeInteractions([wrapped, wrapped])

    with pytest.raises(GeminiServiceError) as exc_info:
        await collect(
            GeminiService(configured_settings(), client=FakeClient(interactions)),
            previous_interaction_id=None,
        )

    assert exc_info.value.code == "provider_timeout"
    assert len(interactions.create_calls) == 2


@pytest.mark.anyio
async def test_retries_one_transient_failure_before_text() -> None:
    interactions = FakeInteractions([StatusError(503), complete_stream("respuesta")])

    result = await collect(
        GeminiService(configured_settings(), client=FakeClient(interactions)),
        previous_interaction_id=None,
    )

    assert len(interactions.create_calls) == 2
    assert result[0] == GeminiTextDelta("respuesta")


@pytest.mark.anyio
async def test_never_retries_after_a_text_delta() -> None:
    stream = FakeStream(
        [
            event(
                "interaction.step.delta",
                delta=SimpleNamespace(type="text", text="parcial"),
            ),
            StatusError(503),
        ]
    )
    interactions = FakeInteractions([stream, complete_stream("no debe usarse")])
    service = GeminiService(configured_settings(), client=FakeClient(interactions))
    iterator = service.stream(message="pregunta", previous_interaction_id=None)

    assert await anext(iterator) == GeminiTextDelta("parcial")
    with pytest.raises(GeminiServiceError) as exc_info:
        await anext(iterator)

    assert exc_info.value.retryable is False
    assert len(interactions.create_calls) == 1


@pytest.mark.anyio
async def test_citation_processing_errors_are_not_retried() -> None:
    invalid = {"type": "file_citation", "start_index": 1, "end_index": 2}
    stored = stored_interaction("á", annotations=[invalid])
    interactions = FakeInteractions([complete_stream()], stored)

    with pytest.raises(GeminiServiceError) as exc_info:
        await collect(
            GeminiService(configured_settings(), client=FakeClient(interactions)),
            previous_interaction_id=None,
        )

    assert exc_info.value.code == "citation_processing_error"
    assert exc_info.value.retryable is False
    assert len(interactions.create_calls) == 1


@pytest.mark.anyio
async def test_cancellation_closes_stream_and_is_not_retried() -> None:
    stream = BlockingStream()
    interactions = FakeInteractions([stream, complete_stream()])
    service = GeminiService(configured_settings(), client=FakeClient(interactions))

    async def consume() -> None:
        async for _ in service.stream(message="pregunta", previous_interaction_id=None):
            pass

    task = asyncio.create_task(consume())
    await stream.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert stream.closed is True
    assert len(interactions.create_calls) == 1


def test_build_client_disables_sdk_retries_and_uses_millisecond_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    created_client = object()

    def client_factory(**kwargs: Any) -> object:
        captured.update(kwargs)
        return created_client

    monkeypatch.setattr("google.genai.Client", client_factory)
    service = GeminiService(configured_settings(gemini_request_timeout_seconds=12.5))

    assert service.client is created_client
    assert captured["api_key"] == "test-key"
    options = captured["http_options"]
    assert options.timeout == 12_500
    assert options.retry_options.attempts == 0
