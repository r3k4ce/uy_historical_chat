from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, cast

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ChatMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_groq import ChatGroq

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.models import Citation, ErrorCode, HistoryMessage
from artigas_mvp_backend.prompts import DOCUMENTARY_LIMIT_RESPONSE, load_artigas_prompts
from artigas_mvp_backend.services.citations import CitationMarkerParser
from artigas_mvp_backend.services.usage import NormalizedUsage, normalize_usage


@dataclass(frozen=True)
class ChatTextDelta:
    delta: str


@dataclass(frozen=True)
class ChatCompleted:
    final_text: str
    citations: tuple[Citation, ...]
    usage: NormalizedUsage


class ChatServiceError(Exception):
    def __init__(
        self,
        *,
        code: ErrorCode,
        user_message: str,
        retryable: bool,
        transient: bool,
    ) -> None:
        super().__init__(user_message)
        self.code: ErrorCode = code
        self.user_message = user_message
        self.retryable = retryable
        self.transient = transient


class RetrievalService:
    def __init__(self, store: Chroma) -> None:
        self.retriever = store.as_retriever(
            search_type="mmr", search_kwargs={"k": 6, "fetch_k": 20}
        )

    async def ainvoke(self, query: str) -> list[Document]:
        return list(await self.retriever.ainvoke(query))


def create_chat_model(settings: Settings) -> BaseChatModel:
    """Create the configured LangChain chat model without making a request."""
    common = {
        "model": settings.chat_model,
        "temperature": settings.chat_temperature,
        "reasoning_effort": settings.chat_reasoning_effort,
        "max_tokens": settings.chat_max_output_tokens,
        "timeout": settings.chat_request_timeout_seconds,
        "max_retries": settings.chat_max_retries,
    }
    if settings.groq_api_key is None:
        raise ValueError("Groq chat configuration is incomplete")
    return cast(
        BaseChatModel,
        ChatGroq(api_key=settings.groq_api_key, **common),
    )


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _status_code(exc: BaseException) -> int | None:
    for item in _exception_chain(exc):
        value = getattr(item, "status_code", None)
        value = getattr(value, "value", value)
        if isinstance(value, (int, str)):
            try:
                return int(value)
            except ValueError:
                pass
    return None


def _translate_provider_error(exc: BaseException, *, text_emitted: bool) -> ChatServiceError:
    status = _status_code(exc)
    if status == 429:
        return ChatServiceError(
            code="provider_rate_limit",
            user_message="El servicio alcanzó temporalmente su límite de solicitudes.",
            retryable=False,
            transient=False,
        )
    timeout = any(
        isinstance(item, TimeoutError) or "timeout" in item.__class__.__name__.lower()
        for item in _exception_chain(exc)
    )
    if timeout:
        return ChatServiceError(
            code="provider_timeout",
            user_message="La respuesta demoró demasiado.",
            retryable=not text_emitted,
            transient=True,
        )
    transient = status in {408, 500, 502, 503, 504}
    return ChatServiceError(
        code="provider_error",
        user_message="No fue posible completar la respuesta.",
        retryable=transient and not text_emitted,
        transient=transient,
    )


def _chunk_text(chunk: object) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""


def _combine_usage(first: NormalizedUsage, second: NormalizedUsage) -> NormalizedUsage:
    return NormalizedUsage(
        input_tokens=first.input_tokens + second.input_tokens,
        cached_input_tokens=first.cached_input_tokens + second.cached_input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        thought_tokens=first.thought_tokens + second.thought_tokens,
        total_tokens=first.total_tokens + second.total_tokens,
        estimated_cost=first.estimated_cost + second.estimated_cost,
    )


class ChatService:
    """Retrieve current-turn evidence and stream a provider-neutral grounded answer."""

    def __init__(
        self,
        settings: Settings,
        *,
        model: BaseChatModel | Any,
        retriever: RetrievalService | Any,
    ) -> None:
        self.settings = settings
        self.model = model
        self.retriever = retriever
        self.prompts = load_artigas_prompts()
        self.prompt = self.prompts.combined

    @staticmethod
    def _retrieval_query(message: str, history: Sequence[HistoryMessage]) -> str:
        parts = [message]
        if len(history) >= 2:
            parts.extend((history[-2].content, history[-1].content))
        return "\n".join(parts)

    def _messages(
        self,
        message: str,
        history: Sequence[HistoryMessage],
        sources: dict[str, Document],
        *,
        retry_grounding: bool,
    ) -> list[BaseMessage]:
        evidence = "\n\n".join(
            f"{alias} | página {document.metadata.get('page', 'desconocida')} | "
            f"{document.page_content}"
            for alias, document in sources.items()
        )
        evidence_prompt = self.prompts.evidence + "\n\nEVIDENCIA RECUPERADA:\n" + evidence
        messages: list[BaseMessage] = [
            SystemMessage(self.prompts.system),
            ChatMessage(role="developer", content=self.prompts.character),
            ChatMessage(role="developer", content=evidence_prompt),
        ]
        messages.extend(
            HumanMessage(item.content) if item.role == "user" else AIMessage(item.content)
            for item in history
        )
        current = message
        if retry_grounding:
            current = (
                "Vuelve a responder usando marcadores válidos para toda afirmación histórica. "
                "La conversación previa aporta contexto, no evidencia.\n\n" + message
            )
        messages.append(HumanMessage(current))
        return messages

    async def _completion(
        self,
        messages: list[BaseMessage],
        sources: dict[str, Document],
        *,
        emit_text: bool,
    ) -> AsyncIterator[ChatTextDelta | ChatCompleted]:
        parser = CitationMarkerParser(sources)
        usage_data: object | None = None
        text_emitted = False
        provider_stream: Any | None = None
        try:
            created_stream = self.model.astream(messages)
            provider_stream = created_stream
            async for chunk in created_stream:
                chunk_usage = getattr(chunk, "usage_metadata", None)
                if chunk_usage:
                    usage_data = chunk_usage
                delta = parser.feed(_chunk_text(chunk))
                if delta and emit_text:
                    text_emitted = True
                    yield ChatTextDelta(delta)
            final_text, citations, trailing = parser.finish()
            if trailing and emit_text:
                text_emitted = True
                yield ChatTextDelta(trailing)
            yield ChatCompleted(
                final_text=final_text,
                citations=citations,
                usage=normalize_usage(
                    usage_data,
                    input_price_usd_per_million=self.settings.input_price_usd_per_million,
                    cached_input_price_usd_per_million=(self.settings.input_price_usd_per_million),
                    output_price_usd_per_million=self.settings.output_price_usd_per_million,
                ),
            )
        except asyncio.CancelledError:
            raise
        except ChatServiceError:
            raise
        except Exception as exc:
            raise _translate_provider_error(exc, text_emitted=text_emitted) from exc
        finally:
            close = getattr(provider_stream, "aclose", None)
            if close is not None:
                with suppress(Exception):
                    await close()

    async def stream(
        self, *, message: str, history: Sequence[HistoryMessage]
    ) -> AsyncIterator[ChatTextDelta | ChatCompleted]:
        try:
            documents = list(await self.retriever.ainvoke(self._retrieval_query(message, history)))[
                :6
            ]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ChatServiceError(
                code="corpus_unavailable",
                user_message="El corpus documental no está disponible.",
                retryable=False,
                transient=False,
            ) from exc
        sources = {f"S{index}": document for index, document in enumerate(documents, start=1)}
        first: ChatCompleted | None = None
        async for event in self._completion(
            self._messages(message, history, sources, retry_grounding=False),
            sources,
            emit_text=True,
        ):
            if isinstance(event, ChatCompleted):
                first = event
            else:
                yield event
        if first is None:
            raise ChatServiceError(
                code="provider_error",
                user_message="No fue posible completar la respuesta.",
                retryable=True,
                transient=True,
            )
        should_retry = (
            "?" in message
            and not first.citations
            and first.final_text.strip() != DOCUMENTARY_LIMIT_RESPONSE
        )
        if not should_retry:
            yield first
            return
        try:
            second: ChatCompleted | None = None
            async for event in self._completion(
                self._messages(message, history, sources, retry_grounding=True),
                sources,
                emit_text=False,
            ):
                if isinstance(event, ChatCompleted):
                    second = event
            if second is not None and second.citations:
                yield ChatCompleted(
                    final_text=second.final_text,
                    citations=second.citations,
                    usage=_combine_usage(first.usage, second.usage),
                )
                return
            if second is not None:
                first = ChatCompleted(
                    final_text=first.final_text,
                    citations=first.citations,
                    usage=_combine_usage(first.usage, second.usage),
                )
        except ChatServiceError:
            pass
        yield first
