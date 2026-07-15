from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ReviewStatus = Literal["draft", "reviewed"]
DatePrecision = Literal["exact", "month", "year", "approximate", "range", "unknown"]
TextualConfidence = Literal["very_high", "high", "medium", "low"]
AuthorshipClassification = Literal[
    "dictated_or_signed_by_artigas",
    "issued_under_artigas_authority",
    "approved_by_collective_body",
    "attributed_to_artigas",
    "modern_editorial_material",
    "other_historical_actor_or_institution",
]
SectionType = Literal[
    "front_matter",
    "editorial_notice",
    "methodology",
    "chronology",
    "thematic_index",
    "document_index",
    "document_record",
    "authorship_and_provenance",
    "editorial_context",
    "primary_text",
    "reading_notes",
    "documentary_topics",
    "documentary_limitations",
    "sources",
    "bibliography",
    "general_limitations",
    "colophon",
]
TopicDepth = Literal["introductory", "deeper", "comparative"]
LearningActionType = Literal["deepen", "compare"]
LearningTopicId = Literal[
    "sovereignty-and-legitimacy",
    "federalism-and-provincial-autonomy",
    "instructions-republic-and-liberties",
    "buenos-aires-centralism-and-union",
    "pueblos-libres-and-provincial-relations",
    "land-society-and-marginalized-groups",
    "government-education-and-public-welfare",
    "economy-war-and-external-relations",
]


class PageText(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = Field(gt=0)
    text: str


class PageSidecar(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1]
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(gt=0)
    pages: tuple[PageText, ...]

    @model_validator(mode="after")
    def validate_page_sequence(self) -> Self:
        expected = list(range(1, self.page_count + 1))
        actual = [page.page for page in self.pages]
        if actual != expected:
            raise ValueError("pages must be numbered consecutively from 1 through page_count")
        return self


class ManifestSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    document_id: str | None
    corpus_parent: Literal["corpus"] | None
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    section_type: SectionType
    documentary_topics: tuple[str, ...]
    learning_topics: tuple[str, ...]
    priority: int
    review_status: ReviewStatus

    @model_validator(mode="after")
    def validate_range_and_owner(self) -> Self:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        if (self.document_id is None) == (self.corpus_parent is None):
            raise ValueError("section must belong to exactly one document or the corpus")
        return self


class ManifestDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    display_title: str = Field(min_length=1)
    date: str = Field(min_length=1)
    date_precision: DatePrecision
    place: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    historical_period: str = Field(min_length=1)
    issuing_authority: str = Field(min_length=1)
    recipient: str | None
    authorship_classification: AuthorshipClassification
    relationship_to_artigas: str = Field(min_length=1)
    provenance_summary: str = Field(min_length=1)
    textual_confidence: TextualConfidence
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    documentary_topics: tuple[str, ...]
    learning_topics: tuple[str, ...]
    priority: int
    review_status: ReviewStatus
    section_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class VerifiedExcerpt(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    page: int = Field(gt=0)
    section_id: str = Field(min_length=1)
    evidence_type: SectionType
    text: str = Field(min_length=1)
    topics: tuple[str, ...]
    concepts: tuple[str, ...]
    priority: int
    review_status: ReviewStatus


class AllowedOverlap(BaseModel):
    model_config = ConfigDict(frozen=True)

    section_ids: tuple[str, str]
    pages: tuple[int, ...]
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_overlap(self) -> Self:
        first, second = self.section_ids
        if first == second:
            raise ValueError("overlap must reference two different sections")
        if tuple(sorted(set(self.pages))) != self.pages or not self.pages:
            raise ValueError("overlap pages must be unique and ordered")
        return self


class SourceManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1]
    corpus_id: Literal["artigas"]
    corpus_title: str = Field(min_length=1)
    corpus_pdf: Literal["data/artigas-corpus.pdf"]
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: Literal[74]
    review_status: ReviewStatus
    reviewed_by: str | None
    reviewed_at: datetime | None
    corpus_sections: tuple[ManifestSection, ...]
    documents: tuple[ManifestDocument, ...]
    sections: tuple[ManifestSection, ...]
    excerpts: tuple[VerifiedExcerpt, ...]
    allowed_overlaps: tuple[AllowedOverlap, ...]


class LearningTopic(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: LearningTopicId
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    priority: int
    documentary_topics: tuple[str, ...]
    document_ids: tuple[str, ...]
    section_ids: tuple[str, ...]
    comparison_topic_ids: tuple[LearningTopicId, ...]

    @field_validator("title", "description")
    @classmethod
    def reject_blank_copy(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("learning topic copy must not be blank")
        return value


class LearningAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    topic_id: LearningTopicId
    depth: TopicDepth
    type: LearningActionType
    label: str = Field(min_length=1)
    question: str = Field(min_length=1)
    document_ids: tuple[str, ...]
    section_ids: tuple[str, ...]
    concepts: tuple[str, ...]
    comparison_topic_id: LearningTopicId | None
    priority: int
    review_status: ReviewStatus
    active: bool

    @field_validator("id", "label", "question")
    @classmethod
    def reject_blank_copy(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("learning action copy must not be blank")
        return value

    @model_validator(mode="after")
    def validate_depth_contract(self) -> Self:
        if self.depth == "comparative":
            if self.type != "compare" or self.comparison_topic_id is None:
                raise ValueError("comparative actions require type compare and a comparison topic")
        elif self.type != "deepen" or self.comparison_topic_id is not None:
            raise ValueError(
                "introductory and deeper actions require type deepen without comparison"
            )
        return self


class LearningMap(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1]
    review_status: ReviewStatus
    reviewed_by: str | None
    reviewed_at: datetime | None
    topics: tuple[LearningTopic, ...]
    actions: tuple[LearningAction, ...]
