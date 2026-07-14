from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from artigas_mvp_backend.ingest import IngestionError, ingest_pdf, main, validate_pdf_path


class FakeOperations:
    def __init__(self, operations: list[Any]) -> None:
        self.operations = operations
        self.seen: list[Any] = []

    def get(self, operation: Any) -> Any:
        self.seen.append(operation)
        return self.operations.pop(0)


class FakeStores:
    def __init__(self, operation: Any) -> None:
        self.operation = operation
        self.create_calls: list[dict[str, Any]] = []
        self.upload_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.failed_documents_count = 0

    def create(self, *, config: dict[str, Any]) -> Any:
        self.create_calls.append(config)
        return SimpleNamespace(name="fileSearchStores/new-store")

    def upload_to_file_search_store(self, **kwargs: Any) -> Any:
        self.upload_calls.append(kwargs)
        return self.operation

    def get(self, **kwargs: Any) -> Any:
        self.get_calls.append(kwargs)
        return SimpleNamespace(failed_documents_count=self.failed_documents_count)


class FakeClient:
    def __init__(self, operations: list[Any]) -> None:
        initial = SimpleNamespace(name="operations/1", done=False)
        self.file_search_stores = FakeStores(initial)
        self.operations = FakeOperations(operations)


def write_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.7\nfixture")
    return path


@pytest.mark.parametrize("kind", ["missing", "directory", "extension", "header"])
def test_validate_pdf_path_rejects_invalid_inputs(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "document.pdf"
    if kind == "directory":
        path.mkdir()
    elif kind == "extension":
        path = tmp_path / "document.txt"
        write_pdf(path)
    elif kind == "header":
        path.write_bytes(b"not a pdf")

    with pytest.raises(IngestionError):
        validate_pdf_path(path)


def test_validate_pdf_path_accepts_case_insensitive_pdf_suffix(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "document.PDF")
    assert validate_pdf_path(path) == path


def test_ingest_creates_store_uploads_pdf_and_polls(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "artigas.pdf")
    complete = SimpleNamespace(done=True, error=None, response={})
    client = FakeClient([complete])
    sleeps: list[float] = []

    store_name = ingest_pdf(path, client=client, sleep_fn=sleeps.append)

    assert store_name == "fileSearchStores/new-store"
    assert client.file_search_stores.create_calls[0]["display_name"].startswith("artigas-mvp-")
    upload = client.file_search_stores.upload_calls[0]
    assert upload["file"] == str(path)
    assert upload["file_search_store_name"] == store_name
    assert upload["config"] == {
        "display_name": "artigas.pdf",
        "mime_type": "application/pdf",
        "chunking_config": {
            "white_space_config": {
                "max_tokens_per_chunk": 400,
                "max_overlap_tokens": 60,
            }
        },
    }
    assert sleeps == [5]
    assert len(client.operations.seen) == 1
    assert client.file_search_stores.get_calls == [{"name": store_name}]


@pytest.mark.parametrize(
    "terminal",
    [
        SimpleNamespace(done=True, error={"message": "provider detail"}, response=None),
        SimpleNamespace(done=True, error={"code": "FAILED"}, response=None),
    ],
)
def test_ingest_reports_failed_indexing_without_deleting_store(
    tmp_path: Path, terminal: Any
) -> None:
    path = write_pdf(tmp_path / "artigas.pdf")
    client = FakeClient([terminal])

    with pytest.raises(IngestionError) as exc_info:
        ingest_pdf(path, client=client, sleep_fn=lambda _: None)

    assert exc_info.value.store_name == "fileSearchStores/new-store"
    assert not hasattr(client.file_search_stores, "delete")


def test_ingest_rejects_failed_documents_reported_by_store(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "artigas.pdf")
    client = FakeClient([SimpleNamespace(done=True, error=None, response={})])
    client.file_search_stores.failed_documents_count = 1

    with pytest.raises(IngestionError):
        ingest_pdf(path, client=client, sleep_fn=lambda _: None)


def test_main_requires_api_key_before_constructing_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_pdf(tmp_path / "artigas.pdf")
    dotenv_calls: list[None] = []
    monkeypatch.setattr(
        "artigas_mvp_backend.ingest.load_backend_dotenv",
        lambda: dotenv_calls.append(None),
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    calls: list[str] = []
    stderr = io.StringIO()

    result = main(
        [str(path)],
        client_factory=lambda key: calls.append(key),
        stderr=stderr,
    )

    assert result != 0
    assert dotenv_calls == [None]
    assert calls == []
    assert "GEMINI_API_KEY" in stderr.getvalue()


def test_main_prints_assignment_without_secret_or_writing_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_pdf(tmp_path / "artigas.pdf")
    secret = "secret-test-key"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    client = FakeClient([SimpleNamespace(done=True, error=None, response={})])
    stdout = io.StringIO()
    stderr = io.StringIO()

    result = main(
        [str(path)],
        client_factory=lambda key: client if key == secret else None,
        sleep_fn=lambda _: None,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "GEMINI_FILE_SEARCH_STORE=fileSearchStores/new-store" in stdout.getvalue()
    assert "copie" in stdout.getvalue().lower()
    assert secret not in stdout.getvalue() + stderr.getvalue()
    assert not (tmp_path / ".env").exists()


def test_main_failure_after_creation_prints_only_safe_store_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_pdf(tmp_path / "artigas.pdf")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-test-key")
    client = FakeClient(
        [SimpleNamespace(done=True, error={"message": "sensitive detail"}, response=None)]
    )
    stderr = io.StringIO()

    result = main(
        [str(path)],
        client_factory=lambda _: client,
        sleep_fn=lambda _: None,
        stderr=stderr,
    )

    assert result != 0
    assert "fileSearchStores/new-store" in stderr.getvalue()
    assert "sensitive detail" not in stderr.getvalue()
