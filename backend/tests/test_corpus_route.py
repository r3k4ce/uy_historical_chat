from pathlib import Path

import pytest
from corpus_fixtures import make_corpus_paths
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.main import create_app
from artigas_mvp_backend.services.corpus import CorpusService


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def corpus_app(tmp_path: Path) -> tuple[FastAPI, CorpusService]:
    service = CorpusService.load(make_corpus_paths(tmp_path, pdf_content=b"0123456789fixture"))
    return create_app(settings=Settings(), corpus_service=service), service


@pytest.mark.anyio
async def test_serves_validated_pdf_inline_with_native_range_support(
    corpus_app: tuple[FastAPI, CorpusService],
) -> None:
    app, service = corpus_app
    expected = service.paths.pdf.read_bytes()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/corpus/artigas")
        head = await client.head("/api/corpus/artigas")
        partial = await client.get("/api/corpus/artigas", headers={"Range": "bytes=0-9"})
        unsatisfiable = await client.get(
            "/api/corpus/artigas", headers={"Range": f"bytes={len(expected)}-"}
        )

    assert response.status_code == 200
    assert response.content == expected
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'inline; filename="artigas-corpus.pdf"'
    assert response.headers["accept-ranges"] == "bytes"
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(expected))
    assert partial.status_code == 206
    assert partial.content == expected[:10]
    assert partial.headers["content-range"] == f"bytes 0-9/{len(expected)}"
    assert unsatisfiable.status_code == 416


@pytest.mark.parametrize("failure", ["missing", "drift"])
@pytest.mark.anyio
async def test_returns_safe_json_when_corpus_is_unavailable(
    corpus_app: tuple[FastAPI, CorpusService], failure: str
) -> None:
    app, service = corpus_app
    if failure == "missing":
        service.paths.pdf.unlink()
    else:
        service.paths.pdf.write_bytes(b"changed")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/corpus/artigas")

    assert response.status_code == 503
    assert response.json() == {
        "code": "corpus_unavailable",
        "message": "El corpus documental no está disponible.",
        "retryable": False,
    }
