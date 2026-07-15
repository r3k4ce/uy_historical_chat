from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.models import (
    ChatRequest,
    CompleteEventData,
    ErrorPayload,
    TextEventData,
)
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
from artigas_mvp_backend.services.gemini import (
    GeminiCompleted,
    GeminiService,
    GeminiServiceError,
    GeminiTextDelta,
)
from artigas_mvp_backend.services.usage import log_cancelled, log_completion, log_error

router = APIRouter()


def encode_sse(event_name: str, payload: BaseModel) -> str:
    return f"event: {event_name}\ndata: {payload.model_dump_json()}\n\n"


@router.post("/api/chat", response_model=None)
async def chat(request: Request, payload: ChatRequest) -> StreamingResponse | JSONResponse:
    settings: Settings = request.app.state.settings
    configuration_error = settings.chat_configuration_error()
    service: GeminiService | Any | None = getattr(request.app.state, "gemini_service", None)
    if configuration_error or service is None:
        return JSONResponse(
            status_code=503,
            content=ErrorPayload(
                code="configuration_error",
                message=configuration_error or "La configuración de Gemini no está completa.",
                retryable=False,
            ).model_dump(),
        )

    request_id = str(uuid4())
    started = time.monotonic()

    async def events():
        # turn_number is an unauthenticated MVP UX guardrail, not secure rate limiting.
        iterator: Any = service.stream(
            message=payload.message,
            previous_interaction_id=payload.previous_interaction_id,
        )
        terminal = False
        try:
            async for event in iterator:
                if await request.is_disconnected():
                    log_cancelled(
                        request_id=request_id,
                        model=settings.gemini_model,
                        latency_ms=int((time.monotonic() - started) * 1000),
                    )
                    return
                if isinstance(event, GeminiTextDelta):
                    yield encode_sse("text", TextEventData(delta=event.delta))
                elif isinstance(event, GeminiCompleted):
                    terminal = True
                    citations = list(event.citations)
                    final_text = canonicalize_answer_text(event.final_text, citations)
                    corpus = request.app.state.corpus_service
                    try:
                        learning_state = advance_learning_state(
                            normalize_learning_state(payload.learning_state, corpus),
                            corpus,
                        )
                        analysis = analyze_citations(citations, corpus)
                        answer_status = classify_answer(final_text, citations)
                        educational_actions = select_educational_actions(
                            answer_status=answer_status,
                            analysis=analysis,
                            state=learning_state,
                            corpus=corpus,
                        )
                        completion = CompleteEventData(
                            interaction_id=event.interaction_id,
                            final_text=final_text,
                            citations=citations,
                            answer_status=answer_status,
                            sources=list(
                                build_source_cards(
                                    final_text,
                                    citations,
                                    analysis,
                                    corpus,
                                )
                            ),
                            educational_actions=list(educational_actions),
                            learning_state=learning_state,
                            usage=event.usage.to_payload(),
                        )
                    except Exception as exc:
                        raise GeminiServiceError(
                            code="corpus_unavailable",
                            user_message="El corpus documental no está disponible.",
                            retryable=False,
                            transient=False,
                        ) from exc
                    log_completion(
                        request_id,
                        settings.gemini_model,
                        event.usage,
                        len(event.citations),
                        int((time.monotonic() - started) * 1000),
                        Decimal(str(settings.cost_warning_usd_per_request)),
                    )
                    yield encode_sse("complete", completion)
                    return
            if not terminal:
                raise GeminiServiceError(
                    code="provider_error",
                    user_message="No fue posible completar la respuesta.",
                    retryable=True,
                    transient=True,
                )
        except GeminiServiceError as exc:
            log_error(
                request_id=request_id,
                model=settings.gemini_model,
                error_code=exc.code,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            yield encode_sse(
                "error",
                ErrorPayload(code=exc.code, message=exc.user_message, retryable=exc.retryable),
            )
        finally:
            if hasattr(iterator, "aclose"):
                await iterator.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
