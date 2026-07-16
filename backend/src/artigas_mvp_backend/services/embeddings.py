from __future__ import annotations

from typing import Any

from langchain_core.embeddings import Embeddings
from voyageai.client import Client

from artigas_mvp_backend.config import Settings


class VoyageEmbeddings(Embeddings):
    """LangChain embedding adapter with the index's fixed Voyage policies."""

    def __init__(
        self,
        client: Any,
        *,
        model: str,
        dimensions: int,
        batch_size: int = 128,
    ) -> None:
        self.client = client
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size

    def _embed(self, texts: list[str], *, input_type: str) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.embed(
            texts,
            model=self.model,
            input_type=input_type,
            output_dimension=self.dimensions,
            output_dtype="float",
            truncation=False,
        )
        vectors = response.embeddings
        if len(vectors) != len(texts) or any(len(vector) != self.dimensions for vector in vectors):
            raise ValueError("Voyage embedding response shape does not match the request")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(
                self._embed(texts[start : start + self.batch_size], input_type="document")
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], input_type="query")[0]


def create_embeddings(settings: Settings) -> VoyageEmbeddings:
    if settings.voyage_api_key is None:
        raise ValueError("VOYAGE_API_KEY is required to use the corpus index")
    client = Client(
        api_key=settings.voyage_api_key.get_secret_value(),
        timeout=settings.chat_request_timeout_seconds,
        max_retries=settings.chat_max_retries,
    )
    return VoyageEmbeddings(
        client,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
