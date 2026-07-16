from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Self

from dotenv import load_dotenv
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ENV_PATH = BACKEND_ROOT / ".env"
DEFAULT_CHAT_MODEL = "openai/gpt-oss-120b"
DEFAULT_INPUT_PRICE_USD_PER_MILLION = 0.15
DEFAULT_OUTPUT_PRICE_USD_PER_MILLION = 0.60


def load_backend_dotenv() -> None:
    """Load only backend/.env while preserving exported process variables."""
    load_dotenv(BACKEND_ENV_PATH, override=False)


class Settings(BaseModel):
    """Validated Groq and Voyage settings loaded without contacting either provider."""

    model_config = ConfigDict(frozen=True)

    chat_model: str = DEFAULT_CHAT_MODEL
    groq_api_key: SecretStr | None = Field(default=None, repr=False)
    voyage_api_key: SecretStr | None = Field(default=None, repr=False)
    embedding_model: str = "voyage-4-large"
    embedding_dimensions: int = 1024
    chroma_persist_directory: Path = BACKEND_ROOT / ".chroma" / "artigas"
    chat_temperature: float = Field(default=0.6, ge=0, le=2)
    chat_reasoning_effort: Literal["low", "medium", "high"] = "medium"
    chat_max_output_tokens: int = Field(default=4096, ge=1, le=65_536)
    chat_request_timeout_seconds: float = Field(default=45, gt=0)
    chat_max_retries: int = Field(default=1, ge=0, le=3)
    chat_input_price_usd_per_million: float | None = Field(default=None, ge=0)
    chat_output_price_usd_per_million: float | None = Field(default=None, ge=0)
    max_user_message_chars: int = Field(default=2000, ge=1, le=2000)
    max_conversation_turns: int = Field(default=12, ge=1, le=12)
    cost_warning_usd_per_request: float = Field(default=0.05, ge=0)

    @field_validator("groq_api_key", "voyage_api_key", mode="before")
    @classmethod
    def empty_secrets_are_absent(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("chat_model", "embedding_model")
    @classmethod
    def names_are_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("model names cannot be empty")
        return value

    @field_validator("embedding_dimensions")
    @classmethod
    def dimensions_are_supported(cls, value: int) -> int:
        if value not in {256, 512, 1024, 2048}:
            raise ValueError("embedding dimensions must be 256, 512, 1024, or 2048")
        return value

    @model_validator(mode="after")
    def require_explicit_non_default_pricing(self) -> Settings:
        is_default = self.chat_model == DEFAULT_CHAT_MODEL
        if not is_default and (
            self.chat_input_price_usd_per_million is None
            or self.chat_output_price_usd_per_million is None
        ):
            raise ValueError("non-default chat model pricing must be explicit")
        return self

    @property
    def input_price_usd_per_million(self) -> float:
        return (
            self.chat_input_price_usd_per_million
            if self.chat_input_price_usd_per_million is not None
            else DEFAULT_INPUT_PRICE_USD_PER_MILLION
        )

    @property
    def output_price_usd_per_million(self) -> float:
        return (
            self.chat_output_price_usd_per_million
            if self.chat_output_price_usd_per_million is not None
            else DEFAULT_OUTPUT_PRICE_USD_PER_MILLION
        )

    @classmethod
    def from_env(cls) -> Self:
        load_backend_dotenv()
        environment_names = {
            "chat_model": "CHAT_MODEL",
            "groq_api_key": "GROQ_API_KEY",
            "voyage_api_key": "VOYAGE_API_KEY",
            "embedding_model": "EMBEDDING_MODEL",
            "embedding_dimensions": "EMBEDDING_DIMENSIONS",
            "chroma_persist_directory": "CHROMA_PERSIST_DIRECTORY",
            "chat_temperature": "CHAT_TEMPERATURE",
            "chat_reasoning_effort": "CHAT_REASONING_EFFORT",
            "chat_max_output_tokens": "CHAT_MAX_OUTPUT_TOKENS",
            "chat_request_timeout_seconds": "CHAT_REQUEST_TIMEOUT_SECONDS",
            "chat_max_retries": "CHAT_MAX_RETRIES",
            "chat_input_price_usd_per_million": "CHAT_INPUT_PRICE_USD_PER_MILLION",
            "chat_output_price_usd_per_million": "CHAT_OUTPUT_PRICE_USD_PER_MILLION",
            "max_user_message_chars": "MAX_USER_MESSAGE_CHARS",
            "max_conversation_turns": "MAX_CONVERSATION_TURNS",
            "cost_warning_usd_per_request": "COST_WARNING_USD_PER_REQUEST",
        }
        values = {
            field_name: os.environ[environment_name]
            for field_name, environment_name in environment_names.items()
            if environment_name in os.environ
        }
        return cls.model_validate(values)

    def chat_configuration_error(self) -> str | None:
        if self.groq_api_key is None or self.voyage_api_key is None:
            return "La configuración del servicio de conversación no está completa."
        return None


def load_settings() -> Settings:
    return Settings.from_env()
