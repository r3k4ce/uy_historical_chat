import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter

from artigas_mvp_backend.corpus import (
    CorpusPaths,
    extract_page_sidecar,
    normalize_extracted_text,
    sha256_file,
    write_page_sidecar,
)
from artigas_mvp_backend.corpus_models import PageSidecar, PageText

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SHA256 = "d27cad55d58cf92ec30d48852fb6a46fada9ac4766d9144366e8775dbc723797"


def test_repository_defaults_point_to_active_corpus() -> None:
    paths = CorpusPaths.repository_defaults()
    assert paths.pdf == ROOT / "data" / "artigas-corpus.pdf"
    assert paths.pages == ROOT / "data" / "artigas-pages.json"


def test_real_corpus_extracts_expected_physical_pages() -> None:
    paths = CorpusPaths.repository_defaults()
    sidecar = extract_page_sidecar(paths.pdf)

    assert sidecar.corpus_sha256 == EXPECTED_SHA256
    assert sidecar.page_count == 74
    assert [page.page for page in sidecar.pages] == list(range(1, 75))
    assert "José Gervasio Artigas" in sidecar.pages[0].text
    assert "Instrucciones" in sidecar.pages[25].text
    assert "Reglam" in sidecar.pages[53].text
    assert "Cantidad total de páginas PDF: 74" in sidecar.pages[73].text
    assert sha256_file(paths.pdf) == EXPECTED_SHA256


def test_committed_sidecar_matches_fresh_extraction_exactly() -> None:
    paths = CorpusPaths.repository_defaults()
    committed = PageSidecar.model_validate_json(paths.pages.read_text(encoding="utf-8"))
    extracted = extract_page_sidecar(paths.pdf)

    assert committed == extracted
    assert committed.pages[0].text == extracted.pages[0].text
    assert committed.pages[25].text == extracted.pages[25].text
    assert committed.pages[53].text == extracted.pages[53].text
    assert committed.pages[73].text == extracted.pages[73].text


def test_normalization_is_conservative_and_deterministic() -> None:
    raw = "  Jose\u0301\u00a0Gervasio\r\nArtigas\u00ad;  q.e.\tV.E.  "
    assert normalize_extracted_text(raw) == "José Gervasio Artigas; q.e. V.E."


def test_write_page_sidecar_is_stable_utf8_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "corpus.pdf"
    pdf.write_bytes(b"pdf")
    pages = tmp_path / "pages.json"
    paths = CorpusPaths(pdf=pdf, pages=pages)
    sidecar = PageSidecar(
        schema_version=1,
        corpus_sha256="a" * 64,
        page_count=1,
        pages=(PageText(page=1, text="José Artigas"),),
    )
    monkeypatch.setattr("artigas_mvp_backend.corpus.extract_page_sidecar", lambda _: sidecar)

    assert write_page_sidecar(paths) == pages
    first = pages.read_bytes()
    write_page_sidecar(paths)

    assert pages.read_bytes() == first
    assert first.endswith(b"\n")
    assert b"Jos\xc3\xa9" in first
    assert json.loads(first) == sidecar.model_dump(mode="json")
    assert (
        first
        == (
            json.dumps(sidecar.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        ).encode()
    )


def test_repository_sidecar_detects_hash_and_page_count_drift() -> None:
    paths = CorpusPaths.repository_defaults()
    stored = PageSidecar.model_validate_json(paths.pages.read_text(encoding="utf-8"))
    assert stored.corpus_sha256 == sha256_file(paths.pdf)
    assert stored.page_count == 74
    assert len(stored.pages) == stored.page_count

    with pytest.raises(ValidationError):
        PageSidecar.model_validate({**stored.model_dump(), "page_count": 73})
    drifted = stored.model_copy(update={"corpus_sha256": "b" * 64})
    assert drifted.corpus_sha256 != extract_page_sidecar(paths.pdf).corpus_sha256


def test_extract_rejects_unreadable_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "unreadable.pdf"
    pdf.write_bytes(b"not a PDF")

    with pytest.raises(ValueError, match="could not read corpus PDF"):
        extract_page_sidecar(pdf)


def test_extract_rejects_encrypted_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("secret")
    writer.write(pdf)

    with pytest.raises(ValueError, match="encrypted corpus PDFs are not supported"):
        extract_page_sidecar(pdf)


def test_extract_rejects_pdf_without_pages(tmp_path: Path) -> None:
    pdf = tmp_path / "empty.pdf"
    PdfWriter().write(pdf)

    with pytest.raises(ValueError, match="corpus PDF contains no pages"):
        extract_page_sidecar(pdf)


class FakeReader:
    is_encrypted = False

    def __init__(self, pages: list[Any]) -> None:
        self.pages = pages


class FailingPage:
    def extract_text(self) -> str:
        raise RuntimeError("text layer failed")


class TextPage:
    def extract_text(self) -> str:
        return "página"


def test_extract_wraps_page_extraction_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "corpus.pdf"
    pdf.write_bytes(b"placeholder")
    monkeypatch.setattr(
        "artigas_mvp_backend.corpus.PdfReader", lambda _: FakeReader([FailingPage()])
    )

    with pytest.raises(ValueError, match="could not extract corpus PDF text"):
        extract_page_sidecar(pdf)


def test_repository_extraction_rejects_page_count_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = CorpusPaths.repository_defaults()
    monkeypatch.setattr("artigas_mvp_backend.corpus.PdfReader", lambda _: FakeReader([TextPage()]))

    with pytest.raises(ValueError, match="repository corpus must contain 74 pages; found 1"):
        extract_page_sidecar(paths.pdf)


def test_atomic_write_uses_sibling_temp_fsync_and_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "corpus.pdf"
    pdf.write_bytes(b"pdf")
    output = tmp_path / "nested" / "pages.json"
    paths = CorpusPaths(pdf=pdf, pages=output)
    sidecar = PageSidecar(
        schema_version=1,
        corpus_sha256="a" * 64,
        page_count=1,
        pages=(PageText(page=1, text="José Artigas"),),
    )
    monkeypatch.setattr("artigas_mvp_backend.corpus.extract_page_sidecar", lambda _: sidecar)
    fsync_calls: list[int] = []
    replace_calls: list[tuple[Path, Path]] = []
    real_replace = os.replace
    monkeypatch.setattr("artigas_mvp_backend.corpus.os.fsync", fsync_calls.append)

    def observed_replace(source: Path, target: Path) -> None:
        replace_calls.append((Path(source), Path(target)))
        assert Path(source).parent == output.parent
        assert Path(source).read_bytes().endswith(b"\n")
        real_replace(source, target)

    monkeypatch.setattr("artigas_mvp_backend.corpus.os.replace", observed_replace)

    write_page_sidecar(paths)

    assert len(fsync_calls) == 1
    assert replace_calls == [(replace_calls[0][0], output)]
    assert output.is_file()
    assert not list(output.parent.glob(f".{output.name}.*"))


def test_atomic_write_cleans_temp_and_preserves_target_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "corpus.pdf"
    pdf.write_bytes(b"pdf")
    output = tmp_path / "pages.json"
    output.write_text("existing\n", encoding="utf-8")
    paths = CorpusPaths(pdf=pdf, pages=output)
    sidecar = PageSidecar(
        schema_version=1,
        corpus_sha256="a" * 64,
        page_count=1,
        pages=(PageText(page=1, text="José Artigas"),),
    )
    monkeypatch.setattr("artigas_mvp_backend.corpus.extract_page_sidecar", lambda _: sidecar)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("artigas_mvp_backend.corpus.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_page_sidecar(paths)

    assert output.read_text(encoding="utf-8") == "existing\n"
    assert not list(tmp_path.glob(f".{output.name}.*"))
