from typing import Literal

from pydantic import BaseModel, Field, field_validator

ErrorCode = Literal[
    "configuration_error",
    "invalid_request",
    "turn_limit_reached",
    "provider_timeout",
    "provider_rate_limit",
    "provider_error",
    "citation_processing_error",
]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    previous_interaction_id: str | None = None
    turn_number: int = Field(ge=1, le=12)

    @field_validator("message", mode="before")
    @classmethod
    def trim_message(cls, value: object) -> object:
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
    interaction_id: str
    final_text: str
    citations: list[Citation]
    usage: UsagePayload
