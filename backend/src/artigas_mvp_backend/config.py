from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Self

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

BACKEND_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def load_backend_dotenv() -> None:
    """Load only backend/.env while preserving exported process variables."""
    load_dotenv(BACKEND_ENV_PATH, override=False)


class Settings(BaseModel):
    """Validated application settings loaded without contacting Gemini."""

    model_config = ConfigDict(frozen=True)

    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_file_search_store: str | None = Field(default=None, repr=False)
    gemini_model: Literal["gemini-3.5-flash"] = "gemini-3.5-flash"
    gemini_thinking_level: Literal["low"] = "low"
    gemini_max_output_tokens: int = Field(default=4096, ge=1, le=65_536)
    gemini_temperature: float = Field(default=0.4, ge=0, le=2)
    max_user_message_chars: int = Field(default=2000, ge=1, le=2000)
    max_conversation_turns: int = Field(default=12, ge=1, le=12)
    gemini_request_timeout_seconds: float = Field(default=45, gt=0)
    gemini_max_retries: int = Field(default=1, ge=0, le=1)
    cost_warning_usd_per_request: float = Field(default=0.05, ge=0)

    @field_validator("gemini_api_key", "gemini_file_search_store", mode="before")
    @classmethod
    def empty_runtime_values_are_absent(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @classmethod
    def from_env(cls) -> Self:
        load_backend_dotenv()

        environment_names = {
            "gemini_api_key": "GEMINI_API_KEY",
            "gemini_file_search_store": "GEMINI_FILE_SEARCH_STORE",
            "gemini_model": "GEMINI_MODEL",
            "gemini_thinking_level": "GEMINI_THINKING_LEVEL",
            "gemini_max_output_tokens": "GEMINI_MAX_OUTPUT_TOKENS",
            "gemini_temperature": "GEMINI_TEMPERATURE",
            "max_user_message_chars": "MAX_USER_MESSAGE_CHARS",
            "max_conversation_turns": "MAX_CONVERSATION_TURNS",
            "gemini_request_timeout_seconds": "GEMINI_REQUEST_TIMEOUT_SECONDS",
            "gemini_max_retries": "GEMINI_MAX_RETRIES",
            "cost_warning_usd_per_request": "COST_WARNING_USD_PER_REQUEST",
        }
        values = {
            field_name: os.environ[environment_name]
            for field_name, environment_name in environment_names.items()
            if environment_name in os.environ
        }
        return cls.model_validate(values)

    def chat_configuration_error(self) -> str | None:
        if self.gemini_api_key is None or not self.gemini_file_search_store:
            return "La configuración de Gemini no está completa."
        return None


def load_settings() -> Settings:
    return Settings.from_env()
