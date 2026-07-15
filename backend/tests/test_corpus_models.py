import pytest
from pydantic import ValidationError

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


def test_page_sidecar_requires_contiguous_one_based_pages() -> None:
    with pytest.raises(ValidationError, match="numbered consecutively"):
        PageSidecar(
            schema_version=1,
            corpus_sha256="a" * 64,
            page_count=2,
            pages=(PageText(page=1, text="uno"), PageText(page=3, text="tres")),
        )


@pytest.mark.parametrize(
    ("page_count", "pages"),
    [
        (2, (PageText(page=1, text="uno"),)),
        (2, (PageText(page=1, text="uno"), PageText(page=1, text="duplicada"))),
    ],
)
def test_page_sidecar_rejects_missing_or_duplicate_pages(
    page_count: int, pages: tuple[PageText, ...]
) -> None:
    with pytest.raises(ValidationError):
        PageSidecar(
            schema_version=1,
            corpus_sha256="a" * 64,
            page_count=page_count,
            pages=pages,
        )


def test_page_sidecar_rejects_invalid_hash_and_empty_pages() -> None:
    with pytest.raises(ValidationError):
        PageSidecar(schema_version=1, corpus_sha256="changed", page_count=0, pages=())


def test_corpus_models_are_frozen() -> None:
    page = PageText(page=1, text="uno")
    sidecar = PageSidecar(
        schema_version=1,
        corpus_sha256="a" * 64,
        page_count=1,
        pages=(page,),
    )

    with pytest.raises(ValidationError, match="frozen_instance"):
        page.text = "cambiado"
    with pytest.raises(ValidationError, match="frozen_instance"):
        sidecar.page_count = 2


def test_source_manifest_models_are_frozen() -> None:
    section = ManifestSection(
        id="ART-001-primary",
        document_id="ART-001",
        corpus_parent=None,
        page_start=2,
        page_end=2,
        section_type="primary_text",
        documentary_topics=("Soberanía popular",),
        learning_topics=("sovereignty-and-legitimacy",),
        priority=10,
        review_status="draft",
    )
    document = ManifestDocument(
        id="ART-001",
        title="Documento",
        display_title="Documento",
        date="1811-04-11",
        date_precision="exact",
        place="Mercedes",
        document_type="Proclama",
        historical_period="Revolución oriental",
        issuing_authority="José Artigas",
        recipient=None,
        authorship_classification="dictated_or_signed_by_artigas",
        relationship_to_artigas="Firmado por Artigas.",
        provenance_summary="Impresión contemporánea.",
        textual_confidence="high",
        page_start=2,
        page_end=2,
        documentary_topics=("Soberanía popular",),
        learning_topics=("sovereignty-and-legitimacy",),
        priority=10,
        review_status="draft",
        section_ids=(section.id,),
    )
    excerpt = VerifiedExcerpt(
        id="ART-001-excerpt-01",
        document_id=document.id,
        page=2,
        section_id=section.id,
        evidence_type="primary_text",
        text="Texto documental único.",
        topics=("Soberanía popular",),
        concepts=("legitimidad",),
        priority=10,
        review_status="draft",
    )
    manifest = SourceManifest(
        schema_version=1,
        corpus_id="artigas",
        corpus_title="Corpus",
        corpus_pdf="data/artigas-corpus.pdf",
        corpus_sha256="a" * 64,
        page_count=74,
        review_status="draft",
        reviewed_by=None,
        reviewed_at=None,
        corpus_sections=(),
        documents=(document,),
        sections=(section,),
        excerpts=(excerpt,),
        allowed_overlaps=(),
    )

    with pytest.raises(ValidationError, match="frozen_instance"):
        manifest.review_status = "reviewed"


def test_manifest_ranges_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        ManifestSection(
            id="invalid",
            document_id=None,
            corpus_parent="corpus",
            page_start=2,
            page_end=1,
            section_type="front_matter",
            documentary_topics=(),
            learning_topics=(),
            priority=1,
            review_status="draft",
        )


def test_learning_map_models_are_frozen_and_require_nonblank_spanish_copy() -> None:
    topic = LearningTopic(
        id="sovereignty-and-legitimacy",
        title="Soberanía y legitimidad política",
        description="Examina cómo se funda la autoridad política.",
        priority=100,
        documentary_topics=("Soberanía popular",),
        document_ids=("ART-002",),
        section_ids=("ART-002-primary",),
        comparison_topic_ids=("federalism-and-provincial-autonomy",),
    )
    action = LearningAction(
        id="sovereignty-intro-01",
        topic_id=topic.id,
        depth="introductory",
        type="deepen",
        label="Reconocer la soberanía popular",
        question="¿Cómo vincula el documento al pueblo con la legitimidad política?",
        document_ids=("ART-002",),
        section_ids=("ART-002-primary",),
        concepts=("soberanía popular",),
        comparison_topic_id=None,
        priority=100,
        review_status="draft",
        active=False,
    )
    learning_map = LearningMap(
        schema_version=1,
        review_status="draft",
        reviewed_by=None,
        reviewed_at=None,
        topics=(topic,),
        actions=(action,),
    )

    with pytest.raises(ValidationError, match="frozen_instance"):
        learning_map.review_status = "reviewed"
    with pytest.raises(ValidationError):
        LearningAction.model_validate({**action.model_dump(), "question": "   "})
