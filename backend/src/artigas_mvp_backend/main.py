from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from artigas_mvp_backend.api.chat import router as chat_router
from artigas_mvp_backend.api.corpus import router as corpus_router
from artigas_mvp_backend.config import Settings, load_settings
from artigas_mvp_backend.corpus import CorpusPaths
from artigas_mvp_backend.models import ErrorPayload
from artigas_mvp_backend.services.corpus import CorpusService
from artigas_mvp_backend.services.gemini import GeminiService


def _validation_payload(exc: RequestValidationError) -> tuple[int, ErrorPayload]:
    errors = exc.errors()
    for error in errors:
        location = error.get("loc", ())
        if "turn_number" in location and error.get("type") == "less_than_equal":
            return 409, ErrorPayload(
                code="turn_limit_reached",
                message=(
                    "Esta conversación alcanzó el límite de 12 preguntas. "
                    "Inicie una nueva conversación para continuar."
                ),
                retryable=False,
            )
        if "message" in location and error.get("type") == "string_too_long":
            return 422, ErrorPayload(
                code="invalid_request",
                message="La pregunta no puede superar los 2.000 caracteres.",
                retryable=False,
            )
    return 422, ErrorPayload(
        code="invalid_request", message="La pregunta no es válida.", retryable=False
    )


def create_app(
    settings: Settings | None = None,
    gemini_service: GeminiService | Any | None = None,
    corpus_service: CorpusService | Any | None = None,
    corpus_paths: CorpusPaths | None = None,
) -> FastAPI:
    application_settings = settings or load_settings()
    application_corpus_paths = corpus_paths or CorpusPaths.repository_defaults()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        owned_service: GeminiService | None = None
        if corpus_service is None:
            application.state.corpus_service = CorpusService.load(application_corpus_paths)
        if gemini_service is None and application_settings.chat_configuration_error() is None:
            owned_service = GeminiService(application_settings)
            application.state.gemini_service = owned_service
        try:
            yield
        finally:
            if owned_service is not None:
                aio_client = getattr(owned_service.client, "aio", None)
                close = getattr(aio_client, "aclose", None)
                if close is not None:
                    await close()

    app = FastAPI(title="artigas-mvp", lifespan=lifespan)
    app.state.settings = application_settings
    app.state.gemini_service = gemini_service
    app.state.corpus_service = corpus_service

    @app.exception_handler(RequestValidationError)
    async def chat_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        if request.url.path != "/api/chat":
            return await request_validation_exception_handler(request, exc)
        status, payload = _validation_payload(exc)
        return JSONResponse(status_code=status, content=payload.model_dump())

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "project": "artigas-mvp"}

    app.include_router(chat_router)
    app.include_router(corpus_router)
    return app


app = create_app()


def health() -> dict[str, str]:
    """Backward-compatible direct health helper retained for the initial scaffold test."""
    return {"status": "ok", "project": "artigas-mvp"}
