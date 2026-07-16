from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.services.embeddings import VoyageEmbeddings, create_embeddings


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def embed(self, texts: list[str], **kwargs: Any) -> Any:
        self.calls.append((texts, kwargs))
        dimensions = kwargs["output_dimension"]
        return SimpleNamespace(
            embeddings=[[float(index)] * dimensions for index, _ in enumerate(texts)]
        )


def test_documents_are_batched_with_fixed_voyage_options() -> None:
    client = FakeClient()
    embeddings = VoyageEmbeddings(client, model="voyage-4-large", dimensions=256)

    result = embeddings.embed_documents([str(index) for index in range(129)])

    assert len(result) == 129
    assert [len(texts) for texts, _ in client.calls] == [128, 1]
    assert all(
        options
        == {
            "model": "voyage-4-large",
            "input_type": "document",
            "output_dimension": 256,
            "output_dtype": "float",
            "truncation": False,
        }
        for _, options in client.calls
    )


def test_query_uses_query_role_and_empty_documents_skip_the_client() -> None:
    client = FakeClient()
    embeddings = VoyageEmbeddings(client, model="voyage-4-large", dimensions=512)

    assert embeddings.embed_documents([]) == []
    assert embeddings.embed_query("consulta") == [0.0] * 512
    assert client.calls[0][0] == ["consulta"]
    assert client.calls[0][1]["input_type"] == "query"


@pytest.mark.parametrize("response", [[], [[0.0], [1.0]], [[0.0] * 7]])
def test_malformed_responses_are_rejected(response: list[list[float]]) -> None:
    class MalformedClient:
        def embed(self, _texts: list[str], **_kwargs: Any) -> Any:
            return SimpleNamespace(embeddings=response)

    embeddings = VoyageEmbeddings(MalformedClient(), model="voyage-4-large", dimensions=8)

    with pytest.raises(ValueError, match="Voyage embedding response"):
        embeddings.embed_documents(["document"])


def test_factory_constructs_one_retry_timeout_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("artigas_mvp_backend.services.embeddings.Client", Client)
    settings = Settings(
        groq_api_key=SecretStr("groq"),
        voyage_api_key=SecretStr("voyage"),
        embedding_dimensions=2048,
    )

    adapter = create_embeddings(settings)

    assert captured == {"api_key": "voyage", "timeout": 45.0, "max_retries": 1}
    assert adapter.model == "voyage-4-large"
    assert adapter.dimensions == 2048


def test_factory_requires_voyage_credentials() -> None:
    with pytest.raises(ValueError, match="VOYAGE_API_KEY"):
        create_embeddings(Settings())
