from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from artigas_mvp_backend.corpus import (
    CorpusPaths,
    load_learning_map,
    load_page_sidecar,
    load_source_manifest,
    sha256_file,
    validate_learning_map,
    validate_pdf_identity,
    validate_source_manifest,
)
from artigas_mvp_backend.corpus_models import (
    LearningAction,
    LearningMap,
    LearningTopic,
    LearningTopicId,
    ManifestDocument,
    ManifestSection,
    PageSidecar,
    SectionType,
    SourceManifest,
    VerifiedExcerpt,
)

_REPOSITORY_PATHS = CorpusPaths.repository_defaults()


@dataclass(frozen=True)
class CorpusService:
    paths: CorpusPaths
    sidecar: PageSidecar
    manifest: SourceManifest
    learning_map: LearningMap
    _documents_by_page: Mapping[int, ManifestDocument]
    _documents_by_id: Mapping[str, ManifestDocument]
    _sections_by_page: Mapping[int, tuple[ManifestSection, ...]]
    _sections_by_id: Mapping[str, ManifestSection]
    _topics_by_id: Mapping[LearningTopicId, LearningTopic]
    _topics_by_section: Mapping[str, tuple[LearningTopic, ...]]
    _reviewed_excerpts: tuple[VerifiedExcerpt, ...]
    _active_actions_by_id: Mapping[str, LearningAction]

    @classmethod
    def load(cls, paths: CorpusPaths, *, production_ready: bool = False) -> CorpusService:
        sidecar = load_page_sidecar(paths.pages)
        validate_pdf_identity(paths.pdf, sidecar)
        manifest = load_source_manifest(paths.manifest)
        learning_map = load_learning_map(paths.learning_map)

        if manifest.corpus_sha256 != sidecar.corpus_sha256:
            raise ValueError("manifest SHA-256 does not match the page sidecar")
        if manifest.page_count != sidecar.page_count:
            raise ValueError("manifest page count does not match the page sidecar")

        is_repository_data = all(
            supplied.resolve() == expected.resolve()
            for supplied, expected in (
                (paths.pdf, _REPOSITORY_PATHS.pdf),
                (paths.pages, _REPOSITORY_PATHS.pages),
                (paths.manifest, _REPOSITORY_PATHS.manifest),
                (paths.learning_map, _REPOSITORY_PATHS.learning_map),
            )
        )
        if is_repository_data or production_ready:
            validate_source_manifest(manifest, sidecar, production=production_ready)
            validate_learning_map(learning_map, manifest, production=production_ready)

        documents_by_id = {document.id: document for document in manifest.documents}
        documents_by_page = {
            page: document
            for document in manifest.documents
            for page in range(document.page_start, document.page_end + 1)
        }
        sections = (*manifest.corpus_sections, *manifest.sections)
        sections_by_id = {section.id: section for section in sections}
        sections_by_page: dict[int, list[ManifestSection]] = {}
        for section in sections:
            for page in range(section.page_start, section.page_end + 1):
                sections_by_page.setdefault(page, []).append(section)
        frozen_sections_by_page = {
            page: tuple(sorted(page_sections, key=lambda item: (-item.priority, item.id)))
            for page, page_sections in sections_by_page.items()
        }

        topics_by_id: dict[LearningTopicId, LearningTopic] = {
            topic.id: topic for topic in learning_map.topics
        }
        topics_by_section: dict[str, tuple[LearningTopic, ...]] = {}
        for section in sections:
            topic_ids = set(section.learning_topics)
            topic_ids.update(
                topic.id for topic in learning_map.topics if section.id in topic.section_ids
            )
            topics_by_section[section.id] = tuple(
                sorted(
                    (
                        topics_by_id[cast(LearningTopicId, topic_id)]
                        for topic_id in topic_ids
                        if topic_id in topics_by_id
                    ),
                    key=lambda topic: (-topic.priority, topic.id),
                )
            )

        reviewed_excerpts = tuple(
            excerpt for excerpt in manifest.excerpts if excerpt.review_status == "reviewed"
        )
        active_actions_by_id = {
            action.id: action
            for action in learning_map.actions
            if action.active and action.review_status == "reviewed"
        }
        return cls(
            paths=paths,
            sidecar=sidecar,
            manifest=manifest,
            learning_map=learning_map,
            _documents_by_page=MappingProxyType(documents_by_page),
            _documents_by_id=MappingProxyType(documents_by_id),
            _sections_by_page=MappingProxyType(frozen_sections_by_page),
            _sections_by_id=MappingProxyType(sections_by_id),
            _topics_by_id=MappingProxyType(topics_by_id),
            _topics_by_section=MappingProxyType(topics_by_section),
            _reviewed_excerpts=reviewed_excerpts,
            _active_actions_by_id=MappingProxyType(active_actions_by_id),
        )

    def resolve_document(self, page: int) -> ManifestDocument | None:
        return self._documents_by_page.get(page)

    def resolve_sections(self, page: int) -> tuple[ManifestSection, ...]:
        return self._sections_by_page.get(page, ())

    def resolve_document_metadata(self, document_id: str) -> ManifestDocument | None:
        return self._documents_by_id.get(document_id)

    def resolve_learning_topics(self, section_ids: Iterable[str]) -> tuple[LearningTopic, ...]:
        resolved = {
            topic.id: topic
            for section_id in section_ids
            for topic in self._topics_by_section.get(section_id, ())
        }
        return tuple(sorted(resolved.values(), key=lambda topic: (-topic.priority, topic.id)))

    def select_verified_excerpt(
        self,
        section_id: str,
        topic_id: LearningTopicId,
        evidence_type: SectionType,
        cited_page: int,
    ) -> VerifiedExcerpt | None:
        topic = self._topics_by_id.get(topic_id)
        section = self._sections_by_id.get(section_id)
        if (
            topic is None
            or section is None
            or topic not in self._topics_by_section.get(section_id, ())
        ):
            return None
        candidates = [
            excerpt
            for excerpt in self._reviewed_excerpts
            if excerpt.section_id == section_id
            and excerpt.evidence_type == evidence_type
            and excerpt.page == cited_page
            and bool(set(excerpt.topics) & set(topic.documentary_topics))
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda excerpt: (-excerpt.priority, excerpt.id))

    def pdf_url(self, page: int) -> str:
        if page < 1 or page > self.sidecar.page_count:
            raise ValueError("PDF page is outside the corpus")
        return f"/api/corpus/artigas#page={page}"

    def validate_action_id(self, action_id: str) -> LearningAction | None:
        return self._active_actions_by_id.get(action_id)

    def assert_current_pdf(self) -> None:
        try:
            digest = sha256_file(self.paths.pdf)
        except OSError as error:
            raise ValueError("corpus PDF is unavailable") from error
        if digest != self.sidecar.corpus_sha256:
            raise ValueError("corpus PDF SHA-256 does not match validated metadata")
