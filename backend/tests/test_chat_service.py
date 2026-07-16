from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessageChunk, UsageMetadata
from pydantic import SecretStr

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.models import HistoryMessage
from artigas_mvp_backend.prompts import load_artigas_prompts
from artigas_mvp_backend.services.chat import (
    ChatCompleted,
    ChatService,
    ChatServiceError,
    ChatTextDelta,
    RetrievalService,
)


class FakeRetriever:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        self.queries: list[str] = []

    async def ainvoke(self, query: str) -> list[Document]:
        self.queries.append(query)
        return self.documents


class FakeModel:
    def __init__(self, attempts: list[list[Any]]) -> None:
        self.attempts = attempts
        self.messages: list[list[Any]] = []
        self.closed = False

    async def astream(self, messages: list[Any]) -> AsyncIterator[Any]:
        self.messages.append(messages)
        for item in self.attempts.pop(0):
            if isinstance(item, BaseException):
                raise item
            yield item


def settings(**changes: Any) -> Settings:
    return Settings(
        groq_api_key=SecretStr("groq"),
        voyage_api_key=SecretStr("voyage"),
        **changes,
    )


def chunk(text: str, *, input_tokens: int = 0, output_tokens: int = 0) -> AIMessageChunk:
    usage = None
    if input_tokens or output_tokens:
        usage = UsageMetadata(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
    return AIMessageChunk(content=text, usage_metadata=usage)


def evidence() -> list[Document]:
    return [
        Document(
            page_content="La evidencia recuperada.",
            metadata={"title": "Documento federal", "page": 2, "chunk": 0},
        )
    ]


async def collect(service: ChatService, **kwargs: Any) -> list[Any]:
    return [item async for item in service.stream(**kwargs)]


@pytest.mark.anyio
async def test_retrieval_query_uses_current_message_and_last_completed_pair() -> None:
    retriever = FakeRetriever(evidence())
    model = FakeModel([[chunk("Respuesta [[S1]]", input_tokens=10, output_tokens=3)]])
    service = ChatService(settings(), model=model, retriever=retriever)
    history = [
        HistoryMessage(role="user", content="Pregunta anterior"),
        HistoryMessage(role="assistant", content="Respuesta anterior"),
    ]

    events = await collect(service, message="Pregunta actual", history=history)

    assert retriever.queries == ["Pregunta actual\nPregunta anterior\nRespuesta anterior"]
    assert isinstance(events[-1], ChatCompleted)
    request = model.messages[0]
    assert [getattr(message, "role", message.type) for message in request] == [
        "system",
        "developer",
        "developer",
        "human",
        "ai",
        "human",
    ]
    prompts = load_artigas_prompts()
    assert request[0].content == prompts.system
    assert request[1].content == prompts.character
    assert request[2].content.startswith(prompts.evidence)
    assert "La evidencia recuperada." not in request[0].content
    assert "La evidencia recuperada." not in request[1].content
    assert "La evidencia recuperada." in request[2].content
    assert "José Gervasio Artigas" not in request[2].content
    assert "S1" in request[2].content


@pytest.mark.anyio
async def test_stream_strips_markers_and_returns_citations_and_usage() -> None:
    retriever = FakeRetriever(evidence())
    model = FakeModel(
        [
            [
                chunk("Defendí "),
                chunk("la soberanía [["),
                chunk("S1]]", input_tokens=8, output_tokens=4),
            ]
        ]
    )
    service = ChatService(settings(), model=model, retriever=retriever)

    events = await collect(service, message="Explique", history=[])

    assert "".join(event.delta for event in events if isinstance(event, ChatTextDelta)) == (
        "Defendí la soberanía "
    )
    completed = events[-1]
    assert isinstance(completed, ChatCompleted)
    assert completed.final_text == "Defendí la soberanía "
    assert completed.citations[0].supported_text == "Defendí la soberanía"
    assert completed.usage.input_tokens == 8
    assert completed.usage.output_tokens == 4


@pytest.mark.anyio
async def test_uncited_question_retries_silently_and_keeps_first_as_fallback() -> None:
    retriever = FakeRetriever(evidence())
    model = FakeModel(
        [
            [chunk("Primer borrador", input_tokens=5, output_tokens=2)],
            [chunk("Segundo borrador", input_tokens=5, output_tokens=3)],
        ]
    )
    service = ChatService(settings(), model=model, retriever=retriever)

    events = await collect(service, message="¿Pregunta?", history=[])

    assert "".join(event.delta for event in events if isinstance(event, ChatTextDelta)) == (
        "Primer borrador"
    )
    completion = events[-1]
    assert completion.final_text == "Primer borrador"
    assert completion.usage.output_tokens == 5
    assert len(model.messages) == 2


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__("sensitive provider details")
        self.status_code = status_code


class RequestTimeout(Exception):
    pass


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failure", "code", "retryable"),
    [
        (RequestTimeout("secret"), "provider_timeout", True),
        (StatusError(429), "provider_rate_limit", False),
        (StatusError(400), "provider_error", False),
        (StatusError(503), "provider_error", True),
    ],
)
async def test_provider_errors_are_mapped_without_secrets(
    failure: Exception, code: str, retryable: bool
) -> None:
    service = ChatService(
        settings(), model=FakeModel([[failure]]), retriever=FakeRetriever(evidence())
    )

    with pytest.raises(ChatServiceError) as exc_info:
        await collect(service, message="Pregunta", history=[])

    assert exc_info.value.code == code
    assert exc_info.value.retryable is retryable
    assert "secret" not in exc_info.value.user_message


@pytest.mark.anyio
async def test_cancellation_is_not_translated() -> None:
    class BlockingModel:
        started = asyncio.Event()

        async def astream(self, messages: list[Any]) -> AsyncIterator[Any]:
            self.started.set()
            await asyncio.Event().wait()
            yield SimpleNamespace(content="unreachable")

    model = BlockingModel()
    service = ChatService(settings(), model=model, retriever=FakeRetriever(evidence()))

    task = asyncio.create_task(collect(service, message="Pregunta", history=[]))
    await model.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


def test_retrieval_service_configures_mmr() -> None:
    calls: dict[str, Any] = {}

    class FakeStore:
        def as_retriever(self, **kwargs: Any) -> object:
            calls.update(kwargs)
            return object()

    RetrievalService(FakeStore())  # type: ignore[arg-type]

    assert calls == {"search_type": "mmr", "search_kwargs": {"k": 6, "fetch_k": 20}}
