import argparse
import hashlib
import json
import os
import tempfile
import unicodedata
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml
from pypdf import PdfReader

from artigas_mvp_backend.corpus_models import (
    AllowedOverlap,
    LearningMap,
    ManifestSection,
    PageSidecar,
    PageText,
    SourceManifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_REPOSITORY_PAGE_COUNT = 74
EXPECTED_DOCUMENT_RANGES = {
    f"ART-{number:03d}": page_range
    for number, page_range in enumerate(
        (
            (10, 12),
            (13, 16),
            (17, 20),
            (21, 23),
            (24, 28),
            (29, 33),
            (34, 36),
            (37, 40),
            (41, 44),
            (45, 48),
            (49, 51),
            (52, 57),
            (58, 63),
            (64, 66),
            (67, 70),
        ),
        start=1,
    )
}
EXPECTED_CORPUS_PAGES = set(range(1, 10)) | set(range(71, 75))
EXPECTED_LEARNING_TOPIC_TITLES = {
    "sovereignty-and-legitimacy": "Soberanía y legitimidad política",
    "federalism-and-provincial-autonomy": "Federalismo y autonomía provincial",
    "instructions-republic-and-liberties": "Instrucciones, república y libertades",
    "buenos-aires-centralism-and-union": "Buenos Aires, centralismo y unión",
    "pueblos-libres-and-provincial-relations": "Pueblos Libres y relaciones provinciales",
    "land-society-and-marginalized-groups": "Tierra, sociedad y grupos marginados",
    "government-education-and-public-welfare": "Gobierno, educación y bienestar público",
    "economy-war-and-external-relations": "Economía, guerra y relaciones exteriores",
}

# This is deliberately a narrow lexical guard, not a semantic judge. Editorially
# assigned topic tags must contain at least one visible corpus term associated
# with that topic; a human reviewer remains responsible for historical meaning.
DOCUMENTARY_TOPIC_WORDING = {
    "Aduanas y comercio": ("buque", "comerc", "derecho", "puerto", "trafico"),
    "Autoridad civil y militar": (
        "alc.e",
        "alcalde",
        "autoridad",
        "gob",
        "jefe",
        "orden",
        "tropa",
    ),
    "Biblioteca pública": ("biblioteca", "libreria"),
    "Buenos Aires": (
        "buenos aires",
        "buenos ayres",
        "buenos-ayres",
        "buen.s a.s",
        "b.s a.s",
        "b.s-ayres",
    ),
    "Centralismo": (
        "buenos aires",
        "buenos ayres",
        "buenos-ayres",
        "buen.s a.s",
        "b.s a.s",
        "b.s-ayres",
        "subyug",
    ),
    "Distribución de tierras": ("terreno", "estancia", "agraci"),
    "Educación": ("biblioteca", "libro", "historia", "ideas", "artes y ciencias"),
    "Federalismo": ("confeder", "federacion", "federación", "liga"),
    "Gobierno republicano": (
        "govierno",
        "gobierno",
        "legislativo",
        "executivo",
        "judicial",
        "magistrad",
    ),
    "Grupos marginados": (
        "esclav",
        "ezclav",
        "indios",
        "infelices",
        "negros",
        "sambos",
        "pobres",
    ),
    "Libertad civil": ("libertad", "derechos", "dros"),
    "Libertad religiosa": ("religiosa", "religion"),
    "Liga de los Pueblos Libres": ("pueblos libres", "confeder", "federacion", "liga"),
    "Pueblos indígenas": ("indios", "indian"),
    "Sociedad rural": ("campaña", "estancia", "hacend", "labrador"),
    "Soberanía popular": ("pueblo", "vosotros", "vra voluntad", "voluntad gral"),
    "Soberanía provincial": ("provincia", "pueblo oriental", "pueblos", "vanda oriental"),
}


@dataclass(frozen=True)
class CorpusPaths:
    pdf: Path
    pages: Path
    manifest: Path = Path("source-manifest.yaml")
    learning_map: Path = Path("learning-map.yaml")

    @classmethod
    def repository_defaults(cls) -> "CorpusPaths":
        data = REPOSITORY_ROOT / "data"
        return cls(
            pdf=data / "artigas-corpus.pdf",
            pages=data / "artigas-pages.json",
            manifest=data / "source-manifest.yaml",
            learning_map=data / "learning-map.yaml",
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pdf_identity(pdf_path: Path, sidecar: PageSidecar) -> None:
    """Require the current PDF bytes to match the reviewed extracted sidecar."""
    try:
        digest = sha256_file(pdf_path)
    except OSError as exc:
        raise ValueError("corpus PDF is unavailable") from exc
    if digest != sidecar.corpus_sha256:
        raise ValueError("corpus PDF SHA-256 does not match the page sidecar")


def normalize_extracted_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\N{SOFT HYPHEN}", "")
    return " ".join(normalized.split())


def extract_page_sidecar(pdf_path: Path) -> PageSidecar:
    try:
        reader = PdfReader(pdf_path)
    except Exception as error:
        raise ValueError(f"could not read corpus PDF: {pdf_path}") from error
    if reader.is_encrypted:
        raise ValueError("encrypted corpus PDFs are not supported")
    if not reader.pages:
        raise ValueError("corpus PDF contains no pages")

    pages: list[PageText] = []
    try:
        for page_number, page in enumerate(reader.pages, start=1):
            pages.append(PageText(page=page_number, text=page.extract_text() or ""))
    except Exception as error:
        raise ValueError(f"could not extract corpus PDF text: {pdf_path}") from error

    defaults = CorpusPaths.repository_defaults()
    is_repository_corpus = pdf_path.resolve() == defaults.pdf.resolve()
    if is_repository_corpus and len(pages) != EXPECTED_REPOSITORY_PAGE_COUNT:
        raise ValueError(
            f"repository corpus must contain {EXPECTED_REPOSITORY_PAGE_COUNT} pages; "
            f"found {len(pages)}"
        )
    return PageSidecar(
        schema_version=1,
        corpus_sha256=sha256_file(pdf_path),
        page_count=len(pages),
        pages=tuple(pages),
    )


def write_page_sidecar(paths: CorpusPaths) -> Path:
    sidecar = extract_page_sidecar(paths.pdf)
    serialized = (
        json.dumps(sidecar.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    paths.pages.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=paths.pages.parent, prefix=f".{paths.pages.name}.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, paths.pages)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return paths.pages


def load_page_sidecar(path: Path) -> PageSidecar:
    with path.open(encoding="utf-8") as source:
        return PageSidecar.model_validate(json.load(source))


def load_source_manifest(path: Path) -> SourceManifest:
    with path.open(encoding="utf-8") as source:
        data: Any = yaml.safe_load(source)
    return SourceManifest.model_validate(data)


def load_learning_map(path: Path) -> LearningMap:
    with path.open(encoding="utf-8") as source:
        data: Any = yaml.safe_load(source)
    return LearningMap.model_validate(data)


def _section_pages(section: ManifestSection) -> set[int]:
    return set(range(section.page_start, section.page_end + 1))


def _overlap_key(overlap: AllowedOverlap) -> tuple[tuple[str, str], tuple[int, ...]]:
    first, second = overlap.section_ids
    pair = (first, second) if first < second else (second, first)
    return pair, overlap.pages


def validate_source_manifest(
    manifest: SourceManifest, sidecar: PageSidecar, *, production: bool
) -> None:
    if manifest.corpus_sha256 != sidecar.corpus_sha256:
        raise ValueError("manifest SHA-256 does not match the page sidecar")
    if manifest.page_count != sidecar.page_count:
        raise ValueError("manifest page count does not match the page sidecar")

    document_ids = [document.id for document in manifest.documents]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("document IDs must be globally unique")
    section_list = (*manifest.corpus_sections, *manifest.sections)
    section_ids = [section.id for section in section_list]
    if len(section_ids) != len(set(section_ids)):
        raise ValueError("section IDs must be globally unique")
    excerpt_ids = [excerpt.id for excerpt in manifest.excerpts]
    if len(excerpt_ids) != len(set(excerpt_ids)):
        raise ValueError("excerpt IDs must be globally unique")

    ranges = {
        document.id: (document.page_start, document.page_end) for document in manifest.documents
    }
    if set(document_ids) != set(EXPECTED_DOCUMENT_RANGES):
        raise ValueError("repository manifest must contain exactly ART-001 through ART-015")
    if ranges != EXPECTED_DOCUMENT_RANGES:
        raise ValueError("repository manifest physical document ranges do not match the corpus")
    corpus_pages = {
        page for section in manifest.corpus_sections for page in _section_pages(section)
    }
    if corpus_pages != EXPECTED_CORPUS_PAGES:
        raise ValueError("repository corpus sections must own exactly the corpus-level pages")

    document_by_id = {document.id: document for document in manifest.documents}
    section_by_id = {section.id: section for section in section_list}
    for document in manifest.documents:
        if document.page_end > manifest.page_count:
            raise ValueError(f"document {document.id} is outside the corpus")
        if len(document.section_ids) != len(set(document.section_ids)):
            raise ValueError(f"document {document.id} repeats section references")
        for section_id in document.section_ids:
            section = section_by_id.get(section_id)
            if section is None or section.document_id != document.id:
                raise ValueError(
                    f"document {document.id} has invalid section reference {section_id}"
                )

    covered_pages: set[int] = set()
    for section in section_list:
        if section.page_end > manifest.page_count:
            raise ValueError(f"section {section.id} is outside the corpus")
        covered_pages.update(_section_pages(section))
        if section.document_id is not None:
            document = document_by_id.get(section.document_id)
            if document is None:
                raise ValueError(f"section {section.id} references an unknown document")
            if section.page_start < document.page_start or section.page_end > document.page_end:
                raise ValueError(f"section {section.id} is outside its document range")
            if section.id not in document.section_ids:
                raise ValueError(f"section {section.id} is not referenced by its document")
    expected_pages = set(range(1, manifest.page_count + 1))
    if covered_pages != expected_pages:
        missing = sorted(expected_pages - covered_pages)
        raise ValueError(f"manifest sections do not cover corpus pages: {missing}")

    actual_overlaps: set[tuple[tuple[str, str], tuple[int, ...]]] = set()
    for first, second in combinations(section_list, 2):
        pages = tuple(sorted(_section_pages(first) & _section_pages(second)))
        if pages:
            pair = (first.id, second.id) if first.id < second.id else (second.id, first.id)
            actual_overlaps.add((pair, pages))
    declared_overlaps = {_overlap_key(overlap) for overlap in manifest.allowed_overlaps}
    if len(declared_overlaps) != len(manifest.allowed_overlaps):
        raise ValueError("overlaps must be declared exactly once")
    undeclared = actual_overlaps - declared_overlaps
    if undeclared:
        raise ValueError(f"undeclared overlap: {sorted(undeclared)[0]}")
    stale = declared_overlaps - actual_overlaps
    if stale:
        raise ValueError(f"stale overlap declaration: {sorted(stale)[0]}")

    page_text = {page.page: normalize_extracted_text(page.text) for page in sidecar.pages}
    evidenced_topics: set[str] = set()
    for excerpt in manifest.excerpts:
        document = document_by_id.get(excerpt.document_id)
        section = section_by_id.get(excerpt.section_id)
        if document is None or section is None:
            raise ValueError(f"excerpt {excerpt.id} has an unknown reference")
        if section.document_id != document.id or excerpt.page not in _section_pages(section):
            raise ValueError(f"excerpt {excerpt.id} is outside its declared section")
        if excerpt.evidence_type != section.section_type:
            raise ValueError(f"excerpt {excerpt.id} evidence type does not match its section")
        valid_topics = set(document.documentary_topics) & set(section.documentary_topics)
        invalid_topics = set(excerpt.topics) - valid_topics
        if invalid_topics:
            raise ValueError(
                f"excerpt {excerpt.id} topics are not declared by its section and document: "
                f"{sorted(invalid_topics)}"
            )
        normalized_excerpt = normalize_extracted_text(excerpt.text)
        if page_text[excerpt.page].count(normalized_excerpt) != 1:
            raise ValueError(f"excerpt {excerpt.id} must occur exactly once on page {excerpt.page}")
        folded_excerpt = normalized_excerpt.casefold()
        for topic in excerpt.topics:
            wording = DOCUMENTARY_TOPIC_WORDING.get(topic)
            if wording is None or not any(term.casefold() in folded_excerpt for term in wording):
                raise ValueError(f"excerpt {excerpt.id} lacks suitable wording for topic {topic}")
        evidenced_topics.update(excerpt.topics)
    declared_topics = {
        topic for document in manifest.documents for topic in document.documentary_topics
    }
    missing_topics = declared_topics - evidenced_topics
    if missing_topics:
        raise ValueError(
            "manifest lacks suitable-wording excerpt coverage for documentary topics: "
            f"{sorted(missing_topics)}"
        )

    if production:
        reviewed_entries = [manifest.review_status]
        reviewed_entries.extend(section.review_status for section in section_list)
        reviewed_entries.extend(document.review_status for document in manifest.documents)
        reviewed_entries.extend(excerpt.review_status for excerpt in manifest.excerpts)
        if any(status != "reviewed" for status in reviewed_entries) or manifest.reviewed_at is None:
            raise ValueError(
                "production validation requires reviewed material and reviewer metadata"
            )
        if manifest.reviewed_by is None or not manifest.reviewed_by.strip():
            raise ValueError("production validation requires a nonblank reviewer identity")


def validate_learning_map(
    learning_map: LearningMap, manifest: SourceManifest, *, production: bool
) -> None:
    topic_ids = [topic.id for topic in learning_map.topics]
    topic_titles = {topic.id: topic.title for topic in learning_map.topics}
    if topic_titles != EXPECTED_LEARNING_TOPIC_TITLES or len(topic_ids) != 8:
        raise ValueError("learning map must contain exactly the eight fixed topics and titles")
    if len(topic_ids) != len(set(topic_ids)):
        raise ValueError("learning topic IDs must be unique")

    document_by_id = {document.id: document for document in manifest.documents}
    section_by_id = {
        section.id: section for section in (*manifest.corpus_sections, *manifest.sections)
    }
    documentary_topics = {
        topic for document in manifest.documents for topic in document.documentary_topics
    }
    concepts = {concept for excerpt in manifest.excerpts for concept in excerpt.concepts}
    topic_id_set = set(topic_ids)
    topic_by_id = {topic.id: topic for topic in learning_map.topics}
    if list(learning_map.topics) != sorted(
        learning_map.topics, key=lambda topic: (-topic.priority, topic.id)
    ):
        raise ValueError("learning topics must be ordered by descending priority then topic ID")

    def section_supports_topic(section_id: str, topic_id: str) -> bool:
        section = section_by_id[section_id]
        topic = topic_by_id[topic_id]
        return topic_id in section.learning_topics or bool(
            set(section.documentary_topics) & set(topic.documentary_topics)
        )

    for topic in learning_map.topics:
        unknown_documentary_topics = set(topic.documentary_topics) - documentary_topics
        if unknown_documentary_topics:
            raise ValueError(
                f"topic {topic.id} references an unknown documentary topic: "
                f"{sorted(unknown_documentary_topics)}"
            )
        unknown_documents = set(topic.document_ids) - set(document_by_id)
        if unknown_documents:
            raise ValueError(f"topic {topic.id} references an unknown document")
        unknown_sections = set(topic.section_ids) - set(section_by_id)
        if unknown_sections:
            raise ValueError(f"topic {topic.id} references an unknown section")
        if set(topic.comparison_topic_ids) - topic_id_set:
            raise ValueError(f"topic {topic.id} references an unknown comparison topic")
        if topic.id in topic.comparison_topic_ids:
            raise ValueError(f"topic {topic.id} cannot compare with itself")
        if not topic.document_ids or not topic.section_ids or not topic.documentary_topics:
            raise ValueError(f"topic {topic.id} must reference reviewed corpus evidence")
        for document_id in topic.document_ids:
            if topic.id not in document_by_id[document_id].learning_topics:
                raise ValueError(f"topic {topic.id} has an unrelated document reference")
        for section_id in topic.section_ids:
            if not section_supports_topic(section_id, topic.id):
                raise ValueError(f"topic {topic.id} has an unrelated section reference")

    action_ids = [action.id for action in learning_map.actions]
    if len(action_ids) != 72 or len(action_ids) != len(set(action_ids)):
        raise ValueError("learning map must contain exactly 72 unique action IDs")
    if list(learning_map.actions) != sorted(
        learning_map.actions, key=lambda action: (-action.priority, action.id)
    ):
        raise ValueError("learning actions must be ordered by descending priority then action ID")

    for topic_id in topic_ids:
        actions = [action for action in learning_map.actions if action.topic_id == topic_id]
        if len(actions) != 9:
            raise ValueError(f"topic {topic_id} must contain exactly nine actions")
        depth_counts = {
            depth: sum(action.depth == depth for action in actions)
            for depth in ("introductory", "deeper", "comparative")
        }
        if depth_counts != {"introductory": 3, "deeper": 3, "comparative": 3}:
            raise ValueError(f"topic {topic_id} must contain exactly three actions per depth")

    for action in learning_map.actions:
        if action.depth == "comparative":
            if action.type != "compare" or action.comparison_topic_id is None:
                raise ValueError("comparative actions require type compare and a comparison topic")
        elif action.type != "deepen" or action.comparison_topic_id is not None:
            raise ValueError(
                "introductory and deeper actions require type deepen without comparison"
            )
        unknown_documents = set(action.document_ids) - set(document_by_id)
        if unknown_documents:
            raise ValueError(f"action {action.id} references an unknown document")
        unknown_sections = set(action.section_ids) - set(section_by_id)
        if unknown_sections:
            raise ValueError(f"action {action.id} references an unknown section")
        unknown_concepts = set(action.concepts) - concepts
        if unknown_concepts:
            raise ValueError(f"action {action.id} references an unknown concept")
        if not action.document_ids or not action.section_ids or not action.concepts:
            raise ValueError(f"action {action.id} must reference reviewed corpus evidence")
        permitted_topics = {action.topic_id}
        if action.comparison_topic_id is not None:
            permitted_topics.add(action.comparison_topic_id)
        if (
            action.comparison_topic_id is not None
            and action.comparison_topic_id not in topic_id_set
        ):
            raise ValueError(f"action {action.id} references an unknown comparison topic")
        if (
            action.comparison_topic_id is not None
            and action.comparison_topic_id not in topic_by_id[action.topic_id].comparison_topic_ids
        ):
            raise ValueError(f"action {action.id} uses an undeclared comparison topic")
        if not action.question.startswith("¿") or not action.question.endswith("?"):
            raise ValueError(f"action {action.id} must contain a Spanish-formatted question")
        for document_id in action.document_ids:
            if not permitted_topics.intersection(document_by_id[document_id].learning_topics):
                raise ValueError(f"action {action.id} has an unrelated document reference")
        for section_id in action.section_ids:
            if not any(
                section_supports_topic(section_id, topic_id) for topic_id in permitted_topics
            ):
                raise ValueError(f"action {action.id} has an unrelated section reference")
        if action.comparison_topic_id is not None and any(
            not any(
                topic_id in document_by_id[document_id].learning_topics
                for document_id in action.document_ids
            )
            or not any(
                topic_id in section_by_id[section_id].learning_topics
                for section_id in action.section_ids
            )
            for topic_id in permitted_topics
        ):
            raise ValueError(
                f"comparative action {action.id} must cite evidence for both learning topics"
            )
        if action.active and action.review_status != "reviewed":
            raise ValueError("active actions must be reviewed")

    if production and (
        learning_map.review_status != "reviewed"
        or learning_map.reviewed_at is None
        or learning_map.reviewed_by is None
        or not learning_map.reviewed_by.strip()
        or any(
            action.review_status != "reviewed" or not action.active
            for action in learning_map.actions
        )
    ):
        raise ValueError(
            "production validation requires reviewed active actions and reviewer metadata"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepara metadatos deterministas del corpus.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="Extrae el texto del PDF activo por página.")
    validate_parser = subparsers.add_parser(
        "validate", help="Valida el manifiesto contra el texto extraído."
    )
    validate_parser.add_argument(
        "--production",
        action="store_true",
        help="Exige revisión humana completa y metadatos del revisor.",
    )
    arguments = parser.parse_args(argv)
    if arguments.command == "prepare":
        output = write_page_sidecar(CorpusPaths.repository_defaults())
        print(output)
    elif arguments.command == "validate":
        paths = CorpusPaths.repository_defaults()
        sidecar = load_page_sidecar(paths.pages)
        validate_pdf_identity(paths.pdf, sidecar)
        manifest = load_source_manifest(paths.manifest)
        validate_source_manifest(
            manifest,
            sidecar,
            production=arguments.production,
        )
        validate_learning_map(
            load_learning_map(paths.learning_map),
            manifest,
            production=arguments.production,
        )
        print(paths.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
