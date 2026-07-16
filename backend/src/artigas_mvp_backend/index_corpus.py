from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from artigas_mvp_backend.config import load_settings
from artigas_mvp_backend.corpus import CorpusPaths, sha256_file
from artigas_mvp_backend.services.corpus import CorpusService
from artigas_mvp_backend.services.embeddings import create_embeddings

COLLECTION_NAME = "artigas-corpus-v1"
INDEX_SCHEMA_VERSION = 2
CHUNK_SIZE = 400
CHUNK_OVERLAP = 60


def _collection_metadata(
    paths: CorpusPaths, embedding_model: str, dimensions: int
) -> dict[str, Any]:
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "corpus_sha256": sha256_file(paths.pdf),
        "embedding_provider": "voyage",
        "embedding_model": embedding_model,
        "embedding_dimensions": dimensions,
        "embedding_dtype": "float",
        "distance": "cosine",
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
    }


def _documents(paths: CorpusPaths, embedding_model: str) -> tuple[list[Document], list[str]]:
    corpus = CorpusService.load(paths)
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    documents: list[Document] = []
    identifiers: list[str] = []
    digest = corpus.sidecar.corpus_sha256
    for physical_page in corpus.sidecar.pages:
        document = corpus.resolve_document(physical_page.page)
        sections = corpus.resolve_sections(physical_page.page)
        chunks = splitter.split_text(physical_page.text)
        for chunk_index, chunk in enumerate(chunks):
            metadata: dict[str, Any] = {
                "page": physical_page.page,
                "document_id": document.id if document else "",
                "title": document.display_title
                if document
                else "Corpus documental de José Artigas",
                "section_id": sections[0].id if sections else "",
                "chunk": chunk_index,
                "corpus_sha256": digest,
                "schema_version": INDEX_SCHEMA_VERSION,
            }
            documents.append(Document(page_content=chunk, metadata=metadata))
            identifiers.append(
                sha256(f"{digest}:{physical_page.page}:{chunk_index}".encode()).hexdigest()
            )
    if not documents:
        raise ValueError("corpus produced no indexable chunks")
    return documents, identifiers


def _persistent_client(directory: Path) -> Any:
    return chromadb.PersistentClient(path=str(directory))


def open_index(
    paths: CorpusPaths,
    directory: Path,
    embeddings: Embeddings,
    *,
    embedding_model: str,
    dimensions: int,
) -> Chroma:
    if not directory.is_dir():
        raise ValueError("Chroma index is missing")
    client = _persistent_client(directory)
    if COLLECTION_NAME not in {collection.name for collection in client.list_collections()}:
        raise ValueError("Chroma collection is missing")
    collection = client.get_collection(COLLECTION_NAME)
    expected = _collection_metadata(paths, embedding_model, dimensions)
    actual = collection.metadata or {}
    labels = {
        "schema_version": "schema version",
        "corpus_sha256": "corpus SHA-256",
        "embedding_provider": "embedding provider",
        "embedding_model": "embedding model",
        "embedding_dimensions": "embedding dimensions",
        "embedding_dtype": "embedding dtype",
        "distance": "distance",
        "chunk_size": "chunk size",
        "chunk_overlap": "chunk overlap",
    }
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            raise ValueError(f"Chroma index {labels[key]} is stale")
    if collection.count() == 0:
        raise ValueError("Chroma collection is empty")
    if collection.configuration.get("hnsw", {}).get("space") != "cosine":
        raise ValueError("Chroma index distance is stale")
    return Chroma(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        create_collection_if_not_exists=False,
    )


def build_index(
    paths: CorpusPaths,
    directory: Path,
    embeddings: Embeddings,
    *,
    embedding_model: str,
    dimensions: int,
    replace: bool = False,
) -> Path:
    if directory.exists() and not replace:
        raise FileExistsError(f"index already exists: {directory}")
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{directory.name}.", dir=directory.parent))
    backup: Path | None = None
    try:
        documents, identifiers = _documents(paths, embedding_model)
        store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=str(temporary),
            collection_metadata=_collection_metadata(paths, embedding_model, dimensions),
            collection_configuration={"hnsw": {"space": "cosine"}},
        )
        store.add_documents(documents, ids=identifiers)
        open_index(
            paths,
            temporary,
            embeddings,
            embedding_model=embedding_model,
            dimensions=dimensions,
        )
        if directory.exists():
            backup = directory.with_name(f".{directory.name}.backup")
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(directory, backup)
        os.replace(temporary, directory)
        if backup is not None:
            shutil.rmtree(backup)
        return directory
    except BaseException:
        if backup is not None and backup.exists() and not directory.exists():
            os.replace(backup, directory)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local Artigas Chroma index")
    parser.add_argument("--replace", action="store_true")
    arguments = parser.parse_args()
    settings = load_settings()
    build_index(
        CorpusPaths.repository_defaults(),
        settings.chroma_persist_directory,
        create_embeddings(settings),
        embedding_model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        replace=arguments.replace,
    )


if __name__ == "__main__":
    main()
