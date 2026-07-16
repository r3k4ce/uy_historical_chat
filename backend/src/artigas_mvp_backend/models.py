from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from artigas_mvp_backend.corpus_models import (
    AuthorshipClassification,
    LearningTopicId,
    SectionType,
    TopicDepth,
)

AnswerStatus = Literal[
    "documented",
    "contemporary_reconstruction",
    "documentary_limitation",
    "conversational",
]

ErrorCode = Literal[
    "configuration_error",
    "corpus_unavailable",
    "invalid_request",
    "turn_limit_reached",
    "provider_timeout",
    "provider_rate_limit",
    "provider_error",
    "citation_processing_error",
]


class LearningState(BaseModel):
    shown_action_ids: list[str] = Field(default_factory=list)
    selected_action_ids: list[str] = Field(default_factory=list)
    submitted_action_id: str | None = None
    topic_depths: dict[LearningTopicId, TopicDepth] = Field(default_factory=dict)

    @field_validator("topic_depths", mode="before")
    @classmethod
    def discard_unknown_topic_ids(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        known_topics = set(LearningTopicId.__args__)
        return {key: depth for key, depth in value.items() if key in known_topics}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list["HistoryMessage"] = Field(default_factory=list)
    turn_number: int = Field(ge=1, le=12)
    learning_state: LearningState = Field(default_factory=LearningState)

    @field_validator("message", mode="before")
    @classmethod
    def trim_message(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_completed_history(self) -> "ChatRequest":
        if len(self.history) % 2:
            raise ValueError("history must contain completed user/assistant pairs")
        expected_roles = ("user", "assistant")
        if any(item.role != expected_roles[index % 2] for index, item in enumerate(self.history)):
            raise ValueError("history must alternate user and assistant messages")
        if len(self.history) // 2 != self.turn_number - 1:
            raise ValueError("history does not match turn_number")
        return self


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12_000)

    @field_validator("content", mode="before")
    @classmethod
    def trim_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ErrorPayload(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool


class Citation(BaseModel):
    number: int = Field(ge=1)
    title: str
    page: int | None
    supported_text: str
    start_index: int = Field(ge=0)
    end_index: int = Field(ge=0)


class EvidenceBlock(BaseModel):
    id: str
    citation_numbers: list[int]
    section_id: str | None
    evidence_type: SectionType | None
    page: int | None
    excerpt_id: str | None
    excerpt: str | None
    supported_text: str
    learning_topic_ids: list[LearningTopicId]


class SourceCard(BaseModel):
    id: str
    citation_numbers: list[int]
    document_id: str | None
    title: str
    date: str | None
    document_type: str | None
    authorship_classification: AuthorshipClassification | None
    relationship_to_artigas: str | None
    pages: list[int]
    pdf_url: str | None
    evidence_blocks: list[EvidenceBlock]


class EducationalAction(BaseModel):
    type: Literal["deepen", "compare", "source"]
    label: Literal["Profundizar", "Contrastar", "Examinar la fuente"]
    action_id: str | None = None
    question: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def validate_slot_shape(self) -> "EducationalAction":
        if self.type == "source":
            if (
                self.label != "Examinar la fuente"
                or self.action_id is not None
                or self.question is not None
                or self.url is None
            ):
                raise ValueError("source actions require only a corpus URL")
        elif (
            self.label != ("Profundizar" if self.type == "deepen" else "Contrastar")
            or self.action_id is None
            or self.question is None
            or self.url is not None
        ):
            raise ValueError("question actions require an action ID and question")
        return self


class UsagePayload(BaseModel):
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    thought_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)


class TextEventData(BaseModel):
    delta: str


class CompleteEventData(BaseModel):
    final_text: str
    citations: list[Citation]
    answer_status: AnswerStatus
    sources: list[SourceCard]
    educational_actions: list[EducationalAction]
    learning_state: LearningState
    usage: UsagePayload
