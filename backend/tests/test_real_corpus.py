import pytest

from artigas_mvp_backend.corpus import (
    CorpusPaths,
    load_learning_map,
    load_page_sidecar,
    load_source_manifest,
    validate_learning_map,
    validate_source_manifest,
)
from artigas_mvp_backend.corpus_models import AllowedOverlap
from artigas_mvp_backend.services.corpus import CorpusService

EXPECTED_RANGES = {
    "ART-001": (10, 12),
    "ART-002": (13, 16),
    "ART-003": (17, 20),
    "ART-004": (21, 23),
    "ART-005": (24, 28),
    "ART-006": (29, 33),
    "ART-007": (34, 36),
    "ART-008": (37, 40),
    "ART-009": (41, 44),
    "ART-010": (45, 48),
    "ART-011": (49, 51),
    "ART-012": (52, 57),
    "ART-013": (58, 63),
    "ART-014": (64, 66),
    "ART-015": (67, 70),
}

EXPECTED_LEARNING_TOPICS = {
    "sovereignty-and-legitimacy": "Soberanía y legitimidad política",
    "federalism-and-provincial-autonomy": "Federalismo y autonomía provincial",
    "instructions-republic-and-liberties": "Instrucciones, república y libertades",
    "buenos-aires-centralism-and-union": "Buenos Aires, centralismo y unión",
    "pueblos-libres-and-provincial-relations": "Pueblos Libres y relaciones provinciales",
    "land-society-and-marginalized-groups": "Tierra, sociedad y grupos marginados",
    "government-education-and-public-welfare": "Gobierno, educación y bienestar público",
    "economy-war-and-external-relations": "Economía, guerra y relaciones exteriores",
}

EXPECTED_CORRECTED_LEARNING_QUESTIONS = {
    "ir-09-compare-gobierno": (
        "¿Qué distancia se observa entre los principios republicanos de 1813 y las "
        "medidas concretas de gobierno de 1816?"
    ),
    "pl-06-deeper-crisis": (
        "¿Qué límites de la coordinación provincial aparecen en el documento atribuido de 1819?"
    ),
    "pl-08-compare-economia": (
        "¿Cómo conectan el reglamento aduanero y la carta atribuida la unión "
        "provincial con la guerra y las relaciones exteriores?"
    ),
    "ge-08-compare-economia": (
        "¿Cómo relacionan el reglamento comercial y el oficio sobre formación de "
        "magistrados la instrucción con los recursos aduaneros?"
    ),
    "ew-01-intro-aduanas": "¿Qué objetivos económicos y políticos cumple el arancel de 1816?",
    "ew-06-deeper-atribucion": (
        "¿Qué cautelas exige usar el documento atribuido de 1819 para estudiar "
        "relaciones exteriores?"
    ),
    "ew-09-compare-buenos-aires": (
        "¿Cómo se relacionan la libertad comercial y las tensiones con Buenos Aires "
        "en los documentos de 1815 y 1816?"
    ),
}


def test_real_corpus_service_loads_without_provider_and_resolves_all_documents() -> None:
    service = CorpusService.load(CorpusPaths.repository_defaults(), production_ready=True)

    assert service.sidecar.page_count == 74
    documents = [service.resolve_document(page) for page in range(10, 71)]
    assert all(document is not None for document in documents)
    assert {document.id for document in documents if document is not None} == set(EXPECTED_RANGES)
    assert service.resolve_document(1) is None
    assert service.resolve_document(74) is None
    assert all(service.resolve_sections(page) for page in range(1, 75))


def test_real_source_manifest_is_structurally_valid() -> None:
    paths = CorpusPaths.repository_defaults()
    sidecar = load_page_sidecar(paths.pages)
    manifest = load_source_manifest(paths.manifest)

    validate_source_manifest(manifest, sidecar, production=False)

    assert {
        document.id: (document.page_start, document.page_end) for document in manifest.documents
    } == EXPECTED_RANGES
    assert {document.id for document in manifest.documents} == set(EXPECTED_RANGES)
    assert {
        page
        for section in manifest.corpus_sections
        for page in range(section.page_start, section.page_end + 1)
    } == set(range(1, 10)) | set(range(71, 75))
    assert {section.section_type for section in manifest.sections} >= {
        "document_record",
        "authorship_and_provenance",
        "editorial_context",
        "primary_text",
        "reading_notes",
        "documentary_topics",
        "documentary_limitations",
        "sources",
    }


def test_real_source_manifest_has_required_authorship_and_excerpts() -> None:
    paths = CorpusPaths.repository_defaults()
    sidecar = load_page_sidecar(paths.pages)
    manifest = load_source_manifest(paths.manifest)
    documents = {document.id: document for document in manifest.documents}

    assert documents["ART-004"].authorship_classification == "approved_by_collective_body"
    assert documents["ART-005"].authorship_classification == "approved_by_collective_body"
    for document_id in ("ART-008", "ART-012", "ART-013"):
        assert documents[document_id].authorship_classification == "issued_under_artigas_authority"
    assert documents["ART-015"].authorship_classification == "attributed_to_artigas"
    assert all(section.document_id is None for section in manifest.corpus_sections)
    assert all(section.corpus_parent == "corpus" for section in manifest.corpus_sections)

    counts = dict.fromkeys(EXPECTED_RANGES, 0)
    for excerpt in manifest.excerpts:
        counts[excerpt.document_id] += 1
    assert min(counts.values()) >= 1
    assert counts["ART-005"] >= 3
    assert counts["ART-012"] >= 3
    assert counts["ART-013"] >= 3

    validate_source_manifest(manifest, sidecar, production=False)


def test_production_validation_rejects_unreviewed_material() -> None:
    paths = CorpusPaths.repository_defaults()
    manifest = load_source_manifest(paths.manifest)
    draft = manifest.model_copy(
        update={
            "documents": (
                manifest.documents[0].model_copy(update={"review_status": "draft"}),
                *manifest.documents[1:],
            )
        }
    )
    with pytest.raises(ValueError, match=r"production.*reviewed"):
        validate_source_manifest(
            draft,
            load_page_sidecar(paths.pages),
            production=True,
        )


def test_validation_rejects_hash_drift_and_undeclared_or_stale_overlaps() -> None:
    paths = CorpusPaths.repository_defaults()
    sidecar = load_page_sidecar(paths.pages)
    manifest = load_source_manifest(paths.manifest)

    with pytest.raises(ValueError, match="SHA-256"):
        validate_source_manifest(
            manifest.model_copy(update={"corpus_sha256": "b" * 64}),
            sidecar,
            production=False,
        )

    first = manifest.sections[0]
    second = manifest.sections[1].model_copy(
        update={"page_start": first.page_start, "page_end": first.page_start}
    )
    broken = manifest.model_copy(
        update={"sections": (first, second, *manifest.sections[2:]), "allowed_overlaps": ()}
    )
    with pytest.raises(ValueError, match="undeclared overlap"):
        validate_source_manifest(broken, sidecar, production=False)

    stale = manifest.model_copy(
        update={
            "allowed_overlaps": (
                *manifest.allowed_overlaps,
                AllowedOverlap(
                    section_ids=("ART-001-record", "ART-001-sources"),
                    pages=(10,),
                    reason="Declaración obsoleta.",
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="stale overlap"):
        validate_source_manifest(stale, sidecar, production=False)


def test_validation_rejects_duplicate_document_section_and_excerpt_ids() -> None:
    paths = CorpusPaths.repository_defaults()
    sidecar = load_page_sidecar(paths.pages)
    manifest = load_source_manifest(paths.manifest)

    mutations = (
        manifest.model_copy(update={"documents": (*manifest.documents, manifest.documents[0])}),
        manifest.model_copy(update={"sections": (*manifest.sections, manifest.sections[0])}),
        manifest.model_copy(update={"excerpts": (*manifest.excerpts, manifest.excerpts[0])}),
    )
    for mutation in mutations:
        with pytest.raises(ValueError, match="globally unique"):
            validate_source_manifest(mutation, sidecar, production=False)


def test_validation_rejects_reverse_section_reference_and_repository_layout() -> None:
    paths = CorpusPaths.repository_defaults()
    sidecar = load_page_sidecar(paths.pages)
    manifest = load_source_manifest(paths.manifest)
    document = manifest.documents[0]

    missing_reverse_reference = manifest.model_copy(
        update={
            "documents": (
                document.model_copy(update={"section_ids": document.section_ids[:-1]}),
                *manifest.documents[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="not referenced by its document"):
        validate_source_manifest(missing_reverse_reference, sidecar, production=False)

    bad_forward_reference = manifest.model_copy(
        update={
            "documents": (
                document.model_copy(update={"section_ids": ("unknown-section",)}),
                *manifest.documents[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="invalid section reference"):
        validate_source_manifest(bad_forward_reference, sidecar, production=False)

    wrong_id = manifest.model_copy(
        update={
            "documents": (
                document.model_copy(update={"id": "ART-999"}),
                *manifest.documents[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="ART-001 through ART-015"):
        validate_source_manifest(wrong_id, sidecar, production=False)

    wrong_range = manifest.model_copy(
        update={
            "documents": (
                document.model_copy(update={"page_end": 13}),
                *manifest.documents[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="physical document ranges"):
        validate_source_manifest(wrong_range, sidecar, production=False)

    wrong_corpus_page = manifest.model_copy(
        update={
            "corpus_sections": (
                manifest.corpus_sections[0].model_copy(update={"page_start": 10, "page_end": 10}),
                *manifest.corpus_sections[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="corpus-level pages"):
        validate_source_manifest(wrong_corpus_page, sidecar, production=False)

    last_section = manifest.sections[-1]
    missing_page = manifest.model_copy(
        update={
            "sections": (
                *manifest.sections[:-1],
                last_section.model_copy(update={"page_start": 69, "page_end": 69}),
            )
        }
    )
    with pytest.raises(ValueError, match="do not cover corpus pages"):
        validate_source_manifest(missing_page, sidecar, production=False)


def test_validation_rejects_excerpt_reference_type_and_topic_mismatches() -> None:
    paths = CorpusPaths.repository_defaults()
    sidecar = load_page_sidecar(paths.pages)
    manifest = load_source_manifest(paths.manifest)
    excerpt = manifest.excerpts[0]

    mutations = (
        (
            excerpt.model_copy(update={"section_id": "ART-002-primary"}),
            "outside its declared section",
        ),
        (
            excerpt.model_copy(update={"evidence_type": "editorial_context"}),
            "evidence type",
        ),
        (
            excerpt.model_copy(update={"text": "Texto que no está en la página."}),
            "must occur exactly once",
        ),
        (
            excerpt.model_copy(update={"topics": ("Federalismo",)}),
            "not declared by its section and document",
        ),
        (
            excerpt.model_copy(update={"topics": ("Buenos Aires",), "text": "Union"}),
            "suitable wording",
        ),
    )
    for changed_excerpt, message in mutations:
        changed = manifest.model_copy(
            update={"excerpts": (changed_excerpt, *manifest.excerpts[1:])}
        )
        with pytest.raises(ValueError, match=message):
            validate_source_manifest(changed, sidecar, production=False)


def test_production_validation_rejects_whitespace_reviewer_identity() -> None:
    paths = CorpusPaths.repository_defaults()
    sidecar = load_page_sidecar(paths.pages)
    manifest = load_source_manifest(paths.manifest)
    reviewed = manifest.model_copy(
        update={
            "review_status": "reviewed",
            "reviewed_by": "   ",
            "reviewed_at": "2026-07-14T12:00:00Z",
            "corpus_sections": tuple(
                section.model_copy(update={"review_status": "reviewed"})
                for section in manifest.corpus_sections
            ),
            "documents": tuple(
                document.model_copy(update={"review_status": "reviewed"})
                for document in manifest.documents
            ),
            "sections": tuple(
                section.model_copy(update={"review_status": "reviewed"})
                for section in manifest.sections
            ),
            "excerpts": tuple(
                excerpt.model_copy(update={"review_status": "reviewed"})
                for excerpt in manifest.excerpts
            ),
        }
    )

    with pytest.raises(ValueError, match="reviewer identity"):
        validate_source_manifest(reviewed, sidecar, production=True)


def test_real_learning_map_has_fixed_topics_and_exact_action_matrix() -> None:
    paths = CorpusPaths.repository_defaults()
    manifest = load_source_manifest(paths.manifest)
    learning_map = load_learning_map(paths.learning_map)

    validate_learning_map(learning_map, manifest, production=False)

    assert {topic.id: topic.title for topic in learning_map.topics} == EXPECTED_LEARNING_TOPICS
    assert len(learning_map.actions) == 72
    assert len({action.id for action in learning_map.actions}) == 72
    for topic_id in EXPECTED_LEARNING_TOPICS:
        actions = [action for action in learning_map.actions if action.topic_id == topic_id]
        assert len(actions) == 9
        assert sum(action.depth == "introductory" for action in actions) == 3
        assert sum(action.depth == "deeper" for action in actions) == 3
        assert sum(action.depth == "comparative" for action in actions) == 3
        assert all(
            action.type == ("compare" if action.depth == "comparative" else "deepen")
            for action in actions
        )
    assert learning_map.review_status == "reviewed"
    assert learning_map.reviewed_by == "Codex"
    assert learning_map.reviewed_at is not None
    assert learning_map.reviewed_at.isoformat() == "2026-07-15T00:42:46-03:00"
    assert all(
        action.active and action.review_status == "reviewed" for action in learning_map.actions
    )
    assert all(
        action.label.strip() and action.question.startswith("¿") for action in learning_map.actions
    )
    assert all(
        "voz opositora" not in action.question.casefold()
        and "testimonio contrario" not in action.question.casefold()
        for action in learning_map.actions
        if action.depth == "comparative"
    )
    questions_by_id = {action.id: action.question for action in learning_map.actions}
    assert {
        action_id: questions_by_id[action_id] for action_id in EXPECTED_CORRECTED_LEARNING_QUESTIONS
    } == EXPECTED_CORRECTED_LEARNING_QUESTIONS


def test_learning_map_validation_rejects_bad_references_and_action_contracts() -> None:
    paths = CorpusPaths.repository_defaults()
    manifest = load_source_manifest(paths.manifest)
    learning_map = load_learning_map(paths.learning_map)
    action = learning_map.actions[0]
    topic = learning_map.topics[0]
    comparative_action = next(
        candidate for candidate in learning_map.actions if candidate.depth == "comparative"
    )

    mutations = (
        (
            learning_map.model_copy(
                update={
                    "actions": (
                        action.model_copy(update={"document_ids": ("ART-999",)}),
                        *learning_map.actions[1:],
                    )
                }
            ),
            "unknown document",
        ),
        (
            learning_map.model_copy(
                update={
                    "actions": (
                        action.model_copy(update={"section_ids": ("unknown",)}),
                        *learning_map.actions[1:],
                    )
                }
            ),
            "unknown section",
        ),
        (
            learning_map.model_copy(
                update={
                    "actions": (
                        action.model_copy(update={"concepts": ("concepto inexistente",)}),
                        *learning_map.actions[1:],
                    )
                }
            ),
            "unknown concept",
        ),
        (
            learning_map.model_copy(
                update={
                    "actions": tuple(
                        comparative_action.model_copy(update={"type": "deepen"})
                        if candidate.id == comparative_action.id
                        else candidate
                        for candidate in learning_map.actions
                    )
                }
            ),
            "comparative actions",
        ),
        (
            learning_map.model_copy(
                update={
                    "topics": (
                        topic.model_copy(update={"documentary_topics": ("Tema inexistente",)}),
                        *learning_map.topics[1:],
                    )
                }
            ),
            "unknown documentary topic",
        ),
    )
    for changed, message in mutations:
        with pytest.raises(ValueError, match=message):
            validate_learning_map(changed, manifest, production=False)

    unsupported_comparison = learning_map.model_copy(
        update={
            "actions": tuple(
                comparative_action.model_copy(
                    update={
                        "document_ids": ("ART-003",),
                        "section_ids": ("ART-003-primary",),
                    }
                )
                if candidate.id == comparative_action.id
                else candidate
                for candidate in learning_map.actions
            )
        }
    )
    with pytest.raises(ValueError, match="both learning topics"):
        validate_learning_map(unsupported_comparison, manifest, production=False)


def test_learning_map_order_and_production_review_contract() -> None:
    paths = CorpusPaths.repository_defaults()
    manifest = load_source_manifest(paths.manifest)
    learning_map = load_learning_map(paths.learning_map)

    assert list(learning_map.actions) == sorted(
        learning_map.actions, key=lambda action: (-action.priority, action.id)
    )
    validate_learning_map(learning_map, manifest, production=True)

    active_draft = learning_map.model_copy(
        update={
            "actions": (
                learning_map.actions[0].model_copy(update={"review_status": "draft"}),
                *learning_map.actions[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="active actions must be reviewed"):
        validate_learning_map(active_draft, manifest, production=False)

    inactive_reviewed = learning_map.model_copy(
        update={
            "actions": (
                learning_map.actions[0].model_copy(update={"active": False}),
                *learning_map.actions[1:],
            )
        }
    )
    with pytest.raises(ValueError, match=r"production.*reviewed active actions"):
        validate_learning_map(inactive_reviewed, manifest, production=True)
