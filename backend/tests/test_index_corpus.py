from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from corpus_fixtures import make_corpus_paths
from langchain_core.embeddings import Embeddings

from artigas_mvp_backend.index_corpus import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    COLLECTION_NAME,
    INDEX_SCHEMA_VERSION,
    build_index,
    open_index,
)


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = sha256(text.encode()).digest()
        return [float(value) / 255 for value in digest[:8]]


def test_builds_persistent_index_with_stable_page_metadata(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    paths = make_corpus_paths(corpus_dir)
    destination = tmp_path / "index"

    build_index(paths, destination, FakeEmbeddings(), embedding_model="fake-model", dimensions=8)
    store = open_index(
        paths,
        destination,
        FakeEmbeddings(),
        embedding_model="fake-model",
        dimensions=8,
    )

    collection = store._collection
    assert collection.name == COLLECTION_NAME
    assert collection.metadata == {
        "schema_version": INDEX_SCHEMA_VERSION,
        "corpus_sha256": sha256(paths.pdf.read_bytes()).hexdigest(),
        "embedding_provider": "voyage",
        "embedding_model": "fake-model",
        "embedding_dimensions": 8,
        "embedding_dtype": "float",
        "distance": "cosine",
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
    }
    first = collection.get(include=["metadatas"])
    assert first["ids"]
    metadatas = first["metadatas"]
    assert metadatas is not None
    assert all(
        isinstance(page := metadata.get("page"), int) and page >= 1 for metadata in metadatas
    )
    assert len(first["ids"]) == len(set(first["ids"]))


def test_open_rejects_missing_and_stale_indexes(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    paths = make_corpus_paths(corpus_dir)
    destination = tmp_path / "index"

    with pytest.raises(ValueError, match="missing"):
        open_index(paths, destination, FakeEmbeddings(), embedding_model="fake-model", dimensions=8)

    build_index(paths, destination, FakeEmbeddings(), embedding_model="fake-model", dimensions=8)
    with pytest.raises(ValueError, match="embedding model"):
        open_index(
            paths, destination, FakeEmbeddings(), embedding_model="other-model", dimensions=8
        )
    with pytest.raises(ValueError, match="embedding dimensions"):
        open_index(
            paths, destination, FakeEmbeddings(), embedding_model="fake-model", dimensions=16
        )

    client = __import__("chromadb").PersistentClient(path=str(destination))
    collection = client.get_collection(COLLECTION_NAME)
    collection.modify(metadata={**collection.metadata, "distance": "l2"})
    with pytest.raises(ValueError, match="distance"):
        open_index(paths, destination, FakeEmbeddings(), embedding_model="fake-model", dimensions=8)
    collection.modify(
        metadata={**collection.metadata, "embedding_provider": "openai", "distance": "cosine"}
    )
    with pytest.raises(ValueError, match="embedding provider"):
        open_index(paths, destination, FakeEmbeddings(), embedding_model="fake-model", dimensions=8)


def test_replace_is_required_and_failed_replacement_preserves_index(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    paths = make_corpus_paths(corpus_dir)
    destination = tmp_path / "index"
    build_index(paths, destination, FakeEmbeddings(), embedding_model="fake-model", dimensions=8)
    original_files = sorted(path.relative_to(destination) for path in destination.rglob("*"))

    with pytest.raises(FileExistsError):
        build_index(
            paths, destination, FakeEmbeddings(), embedding_model="fake-model", dimensions=8
        )

    class BrokenEmbeddings(FakeEmbeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding failed")

    with pytest.raises(RuntimeError, match="embedding failed"):
        build_index(
            paths,
            destination,
            BrokenEmbeddings(),
            embedding_model="fake-model",
            dimensions=8,
            replace=True,
        )

    assert (
        sorted(path.relative_to(destination) for path in destination.rglob("*")) == original_files
    )
    open_index(paths, destination, FakeEmbeddings(), embedding_model="fake-model", dimensions=8)
