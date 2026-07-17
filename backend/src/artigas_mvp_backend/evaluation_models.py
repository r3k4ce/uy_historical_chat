from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from artigas_mvp_backend.corpus_models import LearningTopicId, SectionType
from artigas_mvp_backend.models import AnswerStatus, LearningState

RubricCategory = Literal[
    "historical_accuracy",
    "source_interpretation",
    "educational_usefulness",
    "character_fidelity",
    "conversational_presence",
]
EvaluationActionType = Literal["deepen", "compare", "source"]


def category_notes_are_valid(
    notes: object,
    categories: Sequence[str],
    scores: object,
) -> bool:
    if notes is None:
        return True
    return bool(
        isinstance(notes, dict)
        and isinstance(scores, dict)
        and all(
            isinstance(category, str)
            and category in categories
            and isinstance(note, str)
            and bool(note.strip())
            and note.splitlines() == [note]
            and scores.get(category) == 2
            for category, note in notes.items()
        )
    )


class TurnExpectation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_status: AnswerStatus
    expected_document_ids: tuple[str, ...]
    expected_section_types: tuple[SectionType, ...]
    expected_topics: tuple[LearningTopicId, ...]
    required_concepts: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    minimum_citations: int = Field(ge=0)
    maximum_visible_words: int | None = Field(default=None, gt=0)
    expected_action_types: tuple[EvaluationActionType, ...]


class EvaluationTurn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1)
    submitted_action_id: str | None
    learning_state: LearningState | None
    expect: TurnExpectation


class EvaluationCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    execution: Literal["live", "fixture"]
    fixture_file: str | None
    turns: tuple[EvaluationTurn, ...] = Field(min_length=1)
    critical: bool
    core_historical: bool
    human_review: tuple[RubricCategory, ...]

    @model_validator(mode="after")
    def validate_execution_source(self) -> Self:
        if self.execution == "fixture" and not self.fixture_file:
            raise ValueError("fixture cases require fixture_file")
        if self.execution == "live" and self.fixture_file is not None:
            raise ValueError("live cases cannot reference a fixture_file")
        if len(self.human_review) != len(set(self.human_review)):
            raise ValueError("human review categories must be unique")
        if self.execution == "fixture" and self.human_review:
            raise ValueError("fixture cases cannot require human review")
        if self.execution == "live" and self.human_review.count("character_fidelity") != 1:
            raise ValueError("live cases require character_fidelity exactly once")
        return self


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[2]
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> Self:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation case IDs must be unique")
        return self


class RubricCategoryDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    scores: dict[Literal[1, 2, 3, 4], str]

    @model_validator(mode="after")
    def validate_all_scores(self) -> Self:
        if set(self.scores) != {1, 2, 3, 4}:
            raise ValueError("rubric categories require scores 1 through 4")
        if any(not description.strip() for description in self.scores.values()):
            raise ValueError("rubric score descriptions cannot be blank")
        return self


class HumanRubric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    categories: dict[RubricCategory, RubricCategoryDefinition]

    @model_validator(mode="after")
    def validate_all_categories(self) -> Self:
        required = {
            "historical_accuracy",
            "source_interpretation",
            "educational_usefulness",
            "character_fidelity",
            "conversational_presence",
        }
        if set(self.categories) != required:
            raise ValueError("rubric must define all five review categories")
        return self
