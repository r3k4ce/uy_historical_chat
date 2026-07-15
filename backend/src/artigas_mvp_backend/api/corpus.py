from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from artigas_mvp_backend.models import ErrorPayload
from artigas_mvp_backend.services.corpus import CorpusService

router = APIRouter(prefix="/api/corpus")


@router.api_route("/artigas", methods=["GET", "HEAD"], response_model=None)
def serve_artigas_corpus(request: Request) -> Response:
    corpus: CorpusService = request.app.state.corpus_service
    try:
        corpus.assert_current_pdf()
    except ValueError:
        payload = ErrorPayload(
            code="corpus_unavailable",
            message="El corpus documental no está disponible.",
            retryable=False,
        )
        return JSONResponse(status_code=503, content=payload.model_dump())
    return FileResponse(
        corpus.paths.pdf,
        media_type="application/pdf",
        filename="artigas-corpus.pdf",
        content_disposition_type="inline",
    )
