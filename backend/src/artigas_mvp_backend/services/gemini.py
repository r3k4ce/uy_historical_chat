"""Gemini-specific streaming boundary for the Artigas conversation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.models import Citation, ErrorCode
from artigas_mvp_backend.prompts import load_artigas_prompt
from artigas_mvp_backend.services.citations import (
    CitationProcessingError,
    normalize_citations,
)
from artigas_mvp_backend.services.usage import NormalizedUsage, normalize_usage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeminiTextDelta:
    delta: str


@dataclass(frozen=True)
class GeminiCompleted:
    interaction_id: str
    final_text: str
    citations: tuple[Citation, ...]
    usage: NormalizedUsage


class GeminiServiceError(Exception):
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


_TRANSIENT_STATUS_CODES = {408, 500, 502, 503, 504}
_TIMEOUT_CLASS_NAMES = {
    "ConnectTimeout",
    "ReadTimeout",
    "RequestTimeout",
    "TimeoutError",
    "TimeoutException",
    "WriteTimeout",
}
_CANONICAL_RECONCILIATION_DELAYS_SECONDS = (0.1, 0.2, 0.4, 0.8)
_GROUNDING_RETRY_PREFIX = (
    "Consulta nuevamente el corpus mediante File Search antes de responder. "
    "La interacción previa aporta contexto, no evidencia para este turno.\n\n"
)


def _combine_usage(first: NormalizedUsage, second: NormalizedUsage) -> NormalizedUsage:
    return NormalizedUsage(
        input_tokens=first.input_tokens + second.input_tokens,
        cached_input_tokens=first.cached_input_tokens + second.cached_input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        thought_tokens=first.thought_tokens + second.thought_tokens,
        total_tokens=first.total_tokens + second.total_tokens,
        estimated_cost=first.estimated_cost + second.estimated_cost,
    )


def _value(value: object | None, *names: str) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        attribute = getattr(value, name, None)
        if attribute is not None:
            return attribute
    return None


def _as_items(value: object | None) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return value
    return (value,)


def _normalized_enum(value: object | None) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value)).lower().replace("-", "_")


def _exception_chain(exc: BaseException, limit: int = 8) -> Iterable[BaseException]:
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(limit):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _status_code(exc: BaseException) -> int | None:
    for item in _exception_chain(exc):
        for attribute_name in ("status_code", "code"):
            value = getattr(item, attribute_name, None)
            if callable(value):
                try:
                    value = value()
                except Exception:  # pragma: no cover - defensive provider shim
                    continue
            value = getattr(value, "value", value)
            try:
                if isinstance(value, (int, str)):
                    return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _is_timeout(exc: BaseException) -> bool:
    return any(
        isinstance(item, TimeoutError) or item.__class__.__name__ in _TIMEOUT_CLASS_NAMES
        for item in _exception_chain(exc)
    )


def _translate_provider_error(exc: BaseException, *, text_emitted: bool) -> GeminiServiceError:
    status_code = _status_code(exc)
    if status_code == 429:
        return GeminiServiceError(
            code="provider_rate_limit",
            user_message="El servicio alcanzó temporalmente su límite de solicitudes.",
            retryable=False,
            transient=False,
        )
    timeout = _is_timeout(exc)
    transient = timeout or status_code in _TRANSIENT_STATUS_CODES
    if timeout:
        return GeminiServiceError(
            code="provider_timeout",
            user_message="La respuesta demoró demasiado.",
            retryable=transient and not text_emitted,
            transient=True,
        )
    return GeminiServiceError(
        code="provider_error",
        user_message="No fue posible completar la respuesta.",
        retryable=transient and not text_emitted,
        transient=transient,
    )


def _event_type(event: object) -> str:
    return _normalized_enum(_value(event, "event_type", "type"))


def _interaction_id(event: object) -> str | None:
    interaction = _value(event, "interaction")
    identifier = _value(interaction, "id", "name") or _value(event, "interaction_id", "id")
    return str(identifier) if identifier else None


def _text_delta(event: object) -> str | None:
    if _event_type(event) not in {
        "content.delta",
        "interaction.content.delta",
        "interaction.step.delta",
        "step.delta",
    }:
        return None
    delta = _value(event, "delta") or _value(_value(event, "step"), "delta")
    if _normalized_enum(_value(delta, "type")) not in {"text", "text_delta"}:
        return None
    text = _value(delta, "text", "delta")
    return text if isinstance(text, str) and text else None


def _canonical_output(interaction: object) -> tuple[str, tuple[object, ...]]:
    texts: list[str] = []
    annotations: list[object] = []
    steps = _value(interaction, "steps", "outputs", "output")
    for step in _as_items(steps):
        role = _normalized_enum(_value(step, "role"))
        if role and role not in {"assistant", "model"}:
            continue
        contents = _value(step, "content", "contents")
        if contents is None and _normalized_enum(_value(step, "type")) in {
            "output_text",
            "text",
        }:
            contents = step
        for content in _as_items(contents):
            content_type = _normalized_enum(_value(content, "type"))
            text = _value(content, "text")
            if content_type not in {"", "output_text", "text"} or not isinstance(text, str):
                continue
            texts.append(text)
            annotations.extend(_as_items(_value(content, "annotations")))
        annotations.extend(_as_items(_value(step, "annotations")))
    return "".join(texts), tuple(annotations)


def _is_near_output_token_limit(interaction: object, max_output_tokens: int) -> bool:
    usage = _value(interaction, "usage")
    output_tokens = _value(usage, "total_output_tokens", "output_tokens")
    thought_tokens = _value(usage, "total_thought_tokens", "thought_tokens")
    if not isinstance(output_tokens, int) or not isinstance(thought_tokens, int):
        return False
    return (output_tokens + thought_tokens) * 100 >= max_output_tokens * 95


def _is_accepted_interaction(
    interaction: object, final_text: str, max_output_tokens: int
) -> tuple[bool, bool]:
    status = _normalized_enum(_value(interaction, "status"))
    if status.endswith("completed"):
        return True, False
    if not status.endswith("incomplete") or not final_text:
        return False, False
    details = _value(interaction, "incomplete_details", "incomplete_reason", "error")
    reason = _normalized_enum(_value(details, "reason", "code") or details)
    token_limited = reason in {
        "max_output_tokens",
        "max_tokens",
        "output_token_limit",
    } or (not reason and _is_near_output_token_limit(interaction, max_output_tokens))
    return token_limited, token_limited


def _is_stale_canonical_interaction(interaction: object, max_output_tokens: int) -> bool:
    status = _normalized_enum(_value(interaction, "status"))
    if status == "in_progress":
        return True
    if status != "incomplete":
        return False
    details = _value(interaction, "incomplete_details", "incomplete_reason", "error")
    reason = _normalized_enum(_value(details, "reason", "code") or details)
    return not reason and not _is_near_output_token_limit(interaction, max_output_tokens)


async def _get_canonical_interaction(
    client: Any, interaction_id: str, max_output_tokens: int
) -> Any:
    canonical = await client.aio.interactions.get(interaction_id)
    for delay_seconds in _CANONICAL_RECONCILIATION_DELAYS_SECONDS:
        if not _is_stale_canonical_interaction(canonical, max_output_tokens):
            return canonical
        await asyncio.sleep(delay_seconds)
        canonical = await client.aio.interactions.get(interaction_id)
    return canonical


class GeminiService:
    """Own all provider-specific calls for one configured Gemini model and store."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        api_key = settings.gemini_api_key
        store = settings.gemini_file_search_store
        if api_key is None or not store:
            raise ValueError("Gemini chat configuration is incomplete")
        self.settings = settings
        self.store = store
        self.prompt = load_artigas_prompt()
        self.client: Any = client or genai.Client(
            api_key=api_key.get_secret_value(),
            http_options=types.HttpOptions(
                timeout=int(settings.gemini_request_timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=0),
            ),
        )

    def _request_arguments(
        self, message: str, previous_interaction_id: str | None
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "model": self.settings.gemini_model,
            "input": message,
            "system_instruction": self.prompt,
            "tools": [
                {
                    "type": "file_search",
                    "file_search_store_names": [self.store],
                }
            ],
            "generation_config": {
                "thinking_level": self.settings.gemini_thinking_level,
                "max_output_tokens": self.settings.gemini_max_output_tokens,
                "temperature": self.settings.gemini_temperature,
                # File Search is the only configured tool. Validated mode keeps
                # conversational replies available while constraining any tool
                # use to the reviewed corpus.
                "tool_choice": "validated",
            },
            "stream": True,
        }
        if previous_interaction_id is not None:
            arguments["previous_interaction_id"] = previous_interaction_id
        return arguments

    async def stream(
        self, *, message: str, previous_interaction_id: str | None
    ) -> AsyncIterator[GeminiTextDelta | GeminiCompleted]:
        maximum_attempts = self.settings.gemini_max_retries + 1
        text_emitted = False
        grounding_fallback: GeminiCompleted | None = None
        terminal_retry_usage: NormalizedUsage | None = None
        suppress_retry_deltas = False
        for attempt in range(maximum_attempts):
            provider_stream: Any | None = None
            try:
                attempt_message = (
                    _GROUNDING_RETRY_PREFIX + message if grounding_fallback is not None else message
                )
                created_stream = await self.client.aio.interactions.create(
                    **self._request_arguments(attempt_message, previous_interaction_id)
                )
                provider_stream = created_stream
                interaction_id: str | None = None
                async for event in created_stream:
                    interaction_id = _interaction_id(event) or interaction_id
                    delta = _text_delta(event)
                    if delta is not None:
                        text_emitted = True
                        if grounding_fallback is None and not suppress_retry_deltas:
                            yield GeminiTextDelta(delta)
                if interaction_id is None:
                    raise RuntimeError("Provider stream ended without an interaction identifier")

                canonical = await _get_canonical_interaction(
                    self.client,
                    interaction_id,
                    self.settings.gemini_max_output_tokens,
                )
                final_text, annotations = _canonical_output(canonical)
                accepted, token_limited = _is_accepted_interaction(
                    canonical,
                    final_text,
                    self.settings.gemini_max_output_tokens,
                )
                if not accepted:
                    if grounding_fallback is None and attempt + 1 < maximum_attempts:
                        terminal_retry_usage = normalize_usage(_value(canonical, "usage"))
                        suppress_retry_deltas = text_emitted
                        logger.warning(
                            "Gemini interaction ended without an accepted completion; retrying"
                        )
                        continue
                    raise GeminiServiceError(
                        code="provider_error",
                        user_message="No fue posible completar la respuesta.",
                        retryable=False,
                        transient=False,
                    )
                if token_limited:
                    logger.warning("Gemini response reached the configured output-token limit")
                try:
                    citations = normalize_citations(final_text, annotations)
                except CitationProcessingError as exc:
                    raise GeminiServiceError(
                        code="citation_processing_error",
                        user_message="No fue posible procesar las fuentes de la respuesta.",
                        retryable=False,
                        transient=False,
                    ) from exc
                completion = GeminiCompleted(
                    interaction_id=interaction_id,
                    final_text=final_text,
                    citations=citations,
                    usage=normalize_usage(_value(canonical, "usage")),
                )
                if terminal_retry_usage is not None:
                    completion = GeminiCompleted(
                        interaction_id=completion.interaction_id,
                        final_text=completion.final_text,
                        citations=completion.citations,
                        usage=_combine_usage(terminal_retry_usage, completion.usage),
                    )
                should_retry_grounding = (
                    not citations
                    and grounding_fallback is None
                    and previous_interaction_id is not None
                    and "?" in message
                    and attempt + 1 < maximum_attempts
                )
                if should_retry_grounding:
                    grounding_fallback = completion
                    logger.warning(
                        "Gemini follow-up omitted citations; retrying current-turn grounding"
                    )
                    continue
                if grounding_fallback is not None:
                    if citations:
                        completion = GeminiCompleted(
                            interaction_id=completion.interaction_id,
                            final_text=completion.final_text,
                            citations=completion.citations,
                            usage=_combine_usage(grounding_fallback.usage, completion.usage),
                        )
                    else:
                        completion = GeminiCompleted(
                            interaction_id=grounding_fallback.interaction_id,
                            final_text=grounding_fallback.final_text,
                            citations=grounding_fallback.citations,
                            usage=_combine_usage(grounding_fallback.usage, completion.usage),
                        )
                yield completion
                return
            except asyncio.CancelledError:
                if provider_stream is not None and hasattr(provider_stream, "aclose"):
                    await provider_stream.aclose()
                raise
            except GeminiServiceError:
                if grounding_fallback is not None:
                    yield grounding_fallback
                    return
                raise
            except Exception as exc:
                if grounding_fallback is not None:
                    yield grounding_fallback
                    return
                translated = _translate_provider_error(exc, text_emitted=text_emitted)
                can_retry = (
                    translated.transient and not text_emitted and attempt + 1 < maximum_attempts
                )
                if not can_retry:
                    raise translated from exc
            finally:
                if provider_stream is not None and hasattr(provider_stream, "aclose"):
                    await provider_stream.aclose()
