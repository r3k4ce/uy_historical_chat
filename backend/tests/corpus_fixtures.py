from pathlib import Path

import yaml

from artigas_mvp_backend.corpus import CorpusPaths, sha256_file
from artigas_mvp_backend.corpus_models import (
    LearningAction,
    LearningMap,
    LearningTopic,
    ManifestDocument,
    ManifestSection,
    PageSidecar,
    PageText,
    SourceManifest,
    VerifiedExcerpt,
)


def make_sidecar(*, corpus_sha256: str = "a" * 64, page_count: int = 2) -> PageSidecar:
    return PageSidecar(
        schema_version=1,
        corpus_sha256=corpus_sha256,
        page_count=page_count,
        pages=tuple(
            PageText(page=page, text=f"Página histórica {page}.")
            for page in range(1, page_count + 1)
        ),
    )


def write_pdf_placeholder(path: Path, content: bytes = b"test pdf") -> Path:
    path.write_bytes(content)
    return path


def make_corpus_paths(tmp_path: Path, *, pdf_content: bytes = b"test pdf") -> CorpusPaths:
    pdf = write_pdf_placeholder(tmp_path / "corpus.pdf", pdf_content)
    digest = sha256_file(pdf)
    sidecar = make_sidecar(corpus_sha256=digest, page_count=74)
    pages = tmp_path / "pages.json"
    pages.write_text(sidecar.model_dump_json(indent=2) + "\n", encoding="utf-8")

    primary = ManifestSection(
        id="DOC-001-primary",
        document_id="DOC-001",
        corpus_parent=None,
        page_start=1,
        page_end=3,
        section_type="primary_text",
        documentary_topics=("Federalismo",),
        learning_topics=("federalism-and-provincial-autonomy",),
        priority=50,
        review_status="reviewed",
    )
    editorial = ManifestSection(
        id="DOC-001-context",
        document_id="DOC-001",
        corpus_parent=None,
        page_start=3,
        page_end=3,
        section_type="editorial_context",
        documentary_topics=("Federalismo",),
        learning_topics=("federalism-and-provincial-autonomy",),
        priority=20,
        review_status="reviewed",
    )
    document = ManifestDocument(
        id="DOC-001",
        title="Documento federal",
        display_title="Documento federal",
        date="1813",
        date_precision="year",
        place="Banda Oriental",
        document_type="Documento",
        historical_period="Revolución oriental",
        issuing_authority="José Artigas",
        recipient=None,
        authorship_classification="dictated_or_signed_by_artigas",
        relationship_to_artigas="Firmado por Artigas.",
        provenance_summary="Copia histórica.",
        textual_confidence="high",
        page_start=1,
        page_end=3,
        documentary_topics=("Federalismo",),
        learning_topics=("federalism-and-provincial-autonomy",),
        priority=70,
        review_status="reviewed",
        section_ids=(primary.id, editorial.id),
    )
    excerpts = (
        VerifiedExcerpt(
            id="excerpt-low",
            document_id=document.id,
            page=1,
            section_id=primary.id,
            evidence_type="primary_text",
            text="Fragmento uno.",
            topics=("Federalismo",),
            concepts=("autonomía",),
            priority=10,
            review_status="reviewed",
        ),
        VerifiedExcerpt(
            id="excerpt-exact",
            document_id=document.id,
            page=2,
            section_id=primary.id,
            evidence_type="primary_text",
            text="Fragmento dos.",
            topics=("Federalismo",),
            concepts=("autonomía",),
            priority=5,
            review_status="reviewed",
        ),
        VerifiedExcerpt(
            id="excerpt-exact-a",
            document_id=document.id,
            page=2,
            section_id=primary.id,
            evidence_type="primary_text",
            text="Fragmento dos A.",
            topics=("Federalismo",),
            concepts=("autonomía",),
            priority=20,
            review_status="reviewed",
        ),
        VerifiedExcerpt(
            id="excerpt-exact-z",
            document_id=document.id,
            page=2,
            section_id=primary.id,
            evidence_type="primary_text",
            text="Fragmento dos Z.",
            topics=("Federalismo",),
            concepts=("autonomía",),
            priority=20,
            review_status="reviewed",
        ),
        VerifiedExcerpt(
            id="excerpt-draft",
            document_id=document.id,
            page=2,
            section_id=primary.id,
            evidence_type="primary_text",
            text="Borrador.",
            topics=("Federalismo",),
            concepts=("autonomía",),
            priority=100,
            review_status="draft",
        ),
    )
    manifest = SourceManifest(
        schema_version=1,
        corpus_id="artigas",
        corpus_title="Fixture",
        corpus_pdf="data/artigas-corpus.pdf",
        corpus_sha256=digest,
        page_count=74,
        review_status="draft",
        reviewed_by=None,
        reviewed_at=None,
        corpus_sections=(),
        documents=(document,),
        sections=(primary, editorial),
        excerpts=excerpts,
        allowed_overlaps=(),
    )
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    topic = LearningTopic(
        id="federalism-and-provincial-autonomy",
        title="Federalismo y autonomía provincial",
        description="Fixture.",
        priority=70,
        documentary_topics=("Federalismo",),
        document_ids=(document.id,),
        section_ids=(primary.id,),
        comparison_topic_ids=("sovereignty-and-legitimacy",),
    )
    actions = (
        LearningAction(
            id="active-action",
            topic_id=topic.id,
            depth="introductory",
            type="deepen",
            label="Profundizar",
            question="¿Cómo se expresa la autonomía?",
            document_ids=(document.id,),
            section_ids=(primary.id,),
            concepts=("autonomía",),
            comparison_topic_id=None,
            priority=10,
            review_status="reviewed",
            active=True,
        ),
        LearningAction(
            id="draft-action",
            topic_id=topic.id,
            depth="introductory",
            type="deepen",
            label="Profundizar",
            question="¿Qué dice el borrador?",
            document_ids=(document.id,),
            section_ids=(primary.id,),
            concepts=("autonomía",),
            comparison_topic_id=None,
            priority=20,
            review_status="draft",
            active=False,
        ),
    )
    learning_map = LearningMap(
        schema_version=1,
        review_status="draft",
        reviewed_by=None,
        reviewed_at=None,
        topics=(topic,),
        actions=actions,
    )
    learning_path = tmp_path / "learning.yaml"
    learning_path.write_text(
        yaml.safe_dump(learning_map.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return CorpusPaths(
        pdf=pdf,
        pages=pages,
        manifest=manifest_path,
        learning_map=learning_path,
    )


def make_distinct_evidence_paths(tmp_path: Path) -> CorpusPaths:
    paths = make_corpus_paths(tmp_path)
    manifest = yaml.safe_load(paths.manifest.read_text(encoding="utf-8"))
    primary, editorial = manifest["sections"]
    primary["page_end"] = 2
    editorial["page_start"] = 3
    editorial["page_end"] = 3
    manifest["excerpts"].append(
        {
            "id": "excerpt-editorial",
            "document_id": "DOC-001",
            "page": 3,
            "section_id": "DOC-001-context",
            "evidence_type": "editorial_context",
            "text": "Contexto editorial verificado.",
            "topics": ["Federalismo"],
            "concepts": ["contexto"],
            "priority": 20,
            "review_status": "reviewed",
        }
    )
    paths.manifest.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return paths
