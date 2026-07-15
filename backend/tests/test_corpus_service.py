from __future__ import annotations

import importlib
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest
from corpus_fixtures import make_corpus_paths

from artigas_mvp_backend.corpus import CorpusPaths
from artigas_mvp_backend.corpus import main as corpus_main
from artigas_mvp_backend.services.corpus import CorpusService


def test_service_loads_injected_paths_and_builds_deterministic_indexes(
    tmp_path: Path,
) -> None:
    paths = make_corpus_paths(tmp_path)

    service = CorpusService.load(paths)

    assert service.paths == paths
    assert service.resolve_document(2).id == "DOC-001"  # type: ignore[union-attr]
    assert service.resolve_document(4) is None
    assert [section.id for section in service.resolve_sections(2)] == ["DOC-001-primary"]
    assert [section.id for section in service.resolve_sections(3)] == [
        "DOC-001-primary",
        "DOC-001-context",
    ]
    assert service.resolve_sections(4) == ()
    assert service.resolve_document_metadata("DOC-001").display_title == "Documento federal"  # type: ignore[union-attr]
    assert service.resolve_document_metadata("missing") is None


def test_service_resolves_topics_excerpts_actions_and_urls(tmp_path: Path) -> None:
    service = CorpusService.load(make_corpus_paths(tmp_path))

    topics = service.resolve_learning_topics(["unknown", "DOC-001-primary"])
    assert [topic.id for topic in topics] == ["federalism-and-provincial-autonomy"]
    excerpt = service.select_verified_excerpt(
        "DOC-001-primary",
        "federalism-and-provincial-autonomy",
        "primary_text",
        2,
    )
    assert excerpt is not None
    assert excerpt.id == "excerpt-exact-a"
    assert (
        service.select_verified_excerpt(
            "DOC-001-primary",
            "federalism-and-provincial-autonomy",
            "editorial_context",
            2,
        )
        is None
    )
    assert (
        service.select_verified_excerpt(
            "DOC-001-primary",
            "sovereignty-and-legitimacy",
            "primary_text",
            2,
        )
        is None
    )
    assert service.validate_action_id("active-action").id == "active-action"  # type: ignore[union-attr]
    assert service.validate_action_id("draft-action") is None
    assert service.validate_action_id("missing") is None
    assert service.pdf_url(2) == "/api/corpus/artigas#page=2"


def test_excerpt_selection_does_not_fall_back_to_another_page(tmp_path: Path) -> None:
    service = CorpusService.load(make_corpus_paths(tmp_path))

    assert (
        service.select_verified_excerpt(
            "DOC-001-primary",
            "federalism-and-provincial-autonomy",
            "primary_text",
            3,
        )
        is None
    )


def test_service_indexes_and_fields_are_immutable(tmp_path: Path) -> None:
    service = CorpusService.load(make_corpus_paths(tmp_path))

    with pytest.raises(TypeError):
        cast(Any, service._documents_by_page)[1] = None
    with pytest.raises(FrozenInstanceError):
        cast(Any, service).paths = service.paths


def test_service_detects_missing_or_changed_pdf(tmp_path: Path) -> None:
    paths = make_corpus_paths(tmp_path)
    service = CorpusService.load(paths)
    service.assert_current_pdf()

    paths.pdf.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        service.assert_current_pdf()
    paths.pdf.unlink()
    with pytest.raises(ValueError, match="unavailable"):
        service.assert_current_pdf()


def test_service_refuses_to_load_stale_metadata_after_pdf_drift(tmp_path: Path) -> None:
    paths = make_corpus_paths(tmp_path)
    paths.pdf.write_bytes(b"replacement pdf")

    with pytest.raises(ValueError, match="SHA-256"):
        CorpusService.load(paths)


def test_validate_cli_refuses_stale_metadata_after_pdf_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = make_corpus_paths(tmp_path)
    paths.pdf.write_bytes(b"replacement pdf")
    monkeypatch.setattr(CorpusPaths, "repository_defaults", classmethod(lambda _cls: paths))

    with pytest.raises(ValueError, match="SHA-256"):
        corpus_main(["validate"])


def test_production_load_enforces_editorial_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import artigas_mvp_backend.services.corpus as corpus_module

    calls: list[bool] = []

    def validate_source(*_args, production: bool) -> None:
        calls.append(production)

    def validate_map(*_args, production: bool) -> None:
        calls.append(production)
        raise ValueError("production validation requires reviewed active actions")

    monkeypatch.setattr(corpus_module, "validate_source_manifest", validate_source)
    monkeypatch.setattr(corpus_module, "validate_learning_map", validate_map)

    with pytest.raises(ValueError, match="production"):
        CorpusService.load(make_corpus_paths(tmp_path), production_ready=True)
    assert calls == [True, True]


def test_import_does_not_load_corpus_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: pytest.fail("opened a file"))

    module = importlib.import_module("artigas_mvp_backend.services.corpus")
    importlib.reload(module)


def test_load_uses_injected_paths_not_repository_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = make_corpus_paths(tmp_path)
    monkeypatch.setattr(
        CorpusPaths,
        "repository_defaults",
        classmethod(lambda _cls: pytest.fail("used repository defaults")),
    )

    assert CorpusService.load(paths).paths == paths
