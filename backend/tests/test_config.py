from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from artigas_mvp_backend import config
from artigas_mvp_backend.config import Settings, load_backend_dotenv


def test_settings_defaults_allow_health_without_chat_configuration() -> None:
    settings = Settings()

    assert settings.chat_model == "openai/gpt-oss-120b"
    assert settings.groq_api_key is None
    assert settings.voyage_api_key is None
    assert settings.embedding_model == "voyage-4-large"
    assert settings.embedding_dimensions == 1024
    assert settings.chroma_persist_directory == config.BACKEND_ROOT / ".chroma" / "artigas"
    assert settings.chat_max_output_tokens == 4096
    assert settings.chat_temperature == 0.6
    assert settings.chat_reasoning_effort == "medium"
    assert settings.chat_request_timeout_seconds == 45
    assert settings.chat_max_retries == 1
    assert settings.input_price_usd_per_million == 0.15
    assert settings.output_price_usd_per_million == 0.60
    assert settings.chat_configuration_error() is not None


def test_settings_parse_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "CHAT_MODEL": "gpt-5-mini",
        "GROQ_API_KEY": "groq-secret",
        "VOYAGE_API_KEY": "voyage-secret",
        "EMBEDDING_MODEL": "voyage-4-large",
        "EMBEDDING_DIMENSIONS": "512",
        "CHROMA_PERSIST_DIRECTORY": "/tmp/artigas-index",
        "CHAT_MAX_OUTPUT_TOKENS": "600",
        "CHAT_TEMPERATURE": "0.25",
        "CHAT_REASONING_EFFORT": "high",
        "CHAT_REQUEST_TIMEOUT_SECONDS": "30.5",
        "CHAT_MAX_RETRIES": "0",
        "CHAT_INPUT_PRICE_USD_PER_MILLION": "0.25",
        "CHAT_OUTPUT_PRICE_USD_PER_MILLION": "2.0",
        "MAX_USER_MESSAGE_CHARS": "1800",
        "MAX_CONVERSATION_TURNS": "10",
        "COST_WARNING_USD_PER_REQUEST": "0.03",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings.from_env()

    assert settings.chat_model == "gpt-5-mini"
    assert settings.groq_api_key.get_secret_value() == "groq-secret"  # type: ignore[union-attr]
    assert settings.voyage_api_key.get_secret_value() == "voyage-secret"  # type: ignore[union-attr]
    assert settings.embedding_dimensions == 512
    assert settings.chroma_persist_directory == Path("/tmp/artigas-index")
    assert settings.chat_max_output_tokens == 600
    assert settings.chat_temperature == 0.25
    assert settings.chat_reasoning_effort == "high"
    assert settings.chat_request_timeout_seconds == 30.5
    assert settings.chat_max_retries == 0
    assert settings.input_price_usd_per_million == 0.25
    assert settings.output_price_usd_per_million == 2.0
    assert settings.chat_configuration_error() is None


def test_backend_dotenv_uses_only_the_explicit_backend_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_env = tmp_path / "backend" / ".env"
    backend_env.parent.mkdir()
    backend_env.write_text("GROQ_API_KEY=backend-key\n", encoding="utf-8")
    (tmp_path / ".env").write_text("GROQ_API_KEY=root-key\n", encoding="utf-8")
    working_directory = tmp_path / "elsewhere"
    working_directory.mkdir()
    (working_directory / ".env").write_text("GROQ_API_KEY=cwd-key\n", encoding="utf-8")
    monkeypatch.chdir(working_directory)
    monkeypatch.setattr(config, "BACKEND_ENV_PATH", backend_env)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    load_backend_dotenv()

    assert os.environ["GROQ_API_KEY"] == "backend-key"


def test_backend_dotenv_preserves_exported_process_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_env = tmp_path / ".env"
    backend_env.write_text("VOYAGE_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setattr(config, "BACKEND_ENV_PATH", backend_env)
    monkeypatch.setenv("VOYAGE_API_KEY", "process-key")

    load_backend_dotenv()

    assert os.environ["VOYAGE_API_KEY"] == "process-key"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chat_model", " "),
        ("embedding_model", ""),
        ("embedding_dimensions", 255),
        ("embedding_dimensions", 768),
        ("chat_max_output_tokens", 0),
        ("chat_max_output_tokens", 65_537),
        ("chat_temperature", -0.01),
        ("chat_temperature", 2.01),
        ("chat_reasoning_effort", "minimal"),
        ("chat_reasoning_effort", "HIGH"),
        ("max_user_message_chars", 0),
        ("max_user_message_chars", 2001),
        ("max_conversation_turns", 0),
        ("max_conversation_turns", 13),
        ("chat_request_timeout_seconds", 0),
        ("chat_max_retries", -1),
        ("chat_max_retries", 4),
        ("cost_warning_usd_per_request", -0.01),
    ],
)
def test_settings_reject_invalid_product_configuration(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})  # type: ignore[arg-type]


def test_settings_repr_and_validation_errors_do_not_reveal_secrets() -> None:
    groq_secret = "super-secret-groq-key"
    voyage_secret = "super-secret-voyage-key"
    settings = Settings(
        groq_api_key=SecretStr(groq_secret), voyage_api_key=SecretStr(voyage_secret)
    )

    assert groq_secret not in repr(settings)
    assert voyage_secret not in repr(settings)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            groq_api_key=SecretStr(groq_secret),
            voyage_api_key=SecretStr(voyage_secret),
            chat_max_retries=4,
        )

    rendered_error = str(exc_info.value)
    assert groq_secret not in rendered_error
    assert voyage_secret not in rendered_error
