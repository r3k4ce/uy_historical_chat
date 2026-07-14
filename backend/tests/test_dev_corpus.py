from pathlib import Path

from artigas_mvp_backend.dev_corpus import SECTION_IDS, generate_dev_corpus


def test_dev_corpus_is_deterministic_seven_page_pdf(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"

    generate_dev_corpus(first)
    generate_dev_corpus(second)

    content = first.read_bytes()
    assert content == second.read_bytes()
    assert content.startswith(b"%PDF-")
    assert content.count(b"\n  /Type /Page\n") == 7


def test_dev_corpus_contains_every_synthetic_section_uncompressed(tmp_path: Path) -> None:
    output = tmp_path / "corpus.pdf"

    generate_dev_corpus(output)

    content = output.read_bytes()
    for section_id in SECTION_IDS:
        assert section_id.encode("ascii") in content
    assert b"SINTETICO" in content
    assert b"Guerra Fria" not in content
    assert b"inteligencia artificial" not in content.lower()
