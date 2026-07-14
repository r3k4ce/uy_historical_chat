from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from artigas_mvp_backend.config import Settings


def test_settings_defaults_allow_health_without_chat_configuration() -> None:
    settings = Settings()

    assert settings.gemini_api_key is None
    assert settings.gemini_file_search_store is None
    assert settings.gemini_model == "gemini-3.5-flash"
    assert settings.gemini_thinking_level == "low"
    assert settings.gemini_max_output_tokens == 4096
    assert settings.gemini_temperature == 0.4
    assert settings.max_user_message_chars == 2000
    assert settings.max_conversation_turns == 12
    assert settings.gemini_request_timeout_seconds == 45
    assert settings.gemini_max_retries == 1
    assert settings.cost_warning_usd_per_request == 0.05
    assert settings.chat_configuration_error() is not None


def test_settings_parse_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "GEMINI_API_KEY": "secret-value",
        "GEMINI_FILE_SEARCH_STORE": "fileSearchStores/private-store",
        "GEMINI_MODEL": "gemini-3.5-flash",
        "GEMINI_THINKING_LEVEL": "low",
        "GEMINI_MAX_OUTPUT_TOKENS": "600",
        "GEMINI_TEMPERATURE": "0.25",
        "MAX_USER_MESSAGE_CHARS": "1800",
        "MAX_CONVERSATION_TURNS": "10",
        "GEMINI_REQUEST_TIMEOUT_SECONDS": "30.5",
        "GEMINI_MAX_RETRIES": "0",
        "COST_WARNING_USD_PER_REQUEST": "0.03",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings.from_env()

    assert settings.gemini_api_key is not None
    assert settings.gemini_api_key.get_secret_value() == "secret-value"
    assert settings.gemini_file_search_store == "fileSearchStores/private-store"
    assert settings.gemini_max_output_tokens == 600
    assert settings.gemini_temperature == 0.25
    assert settings.max_user_message_chars == 1800
    assert settings.max_conversation_turns == 10
    assert settings.gemini_request_timeout_seconds == 30.5
    assert settings.gemini_max_retries == 0
    assert settings.cost_warning_usd_per_request == 0.03
    assert settings.chat_configuration_error() is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("gemini_model", "gemini-2.5-flash"),
        ("gemini_thinking_level", "high"),
        ("gemini_max_output_tokens", 0),
        ("gemini_max_output_tokens", 65_537),
        ("gemini_temperature", -0.01),
        ("gemini_temperature", 2.01),
        ("max_user_message_chars", 0),
        ("max_user_message_chars", 2001),
        ("max_conversation_turns", 0),
        ("max_conversation_turns", 13),
        ("gemini_request_timeout_seconds", 0),
        ("gemini_max_retries", -1),
        ("gemini_max_retries", 2),
        ("cost_warning_usd_per_request", -0.01),
    ],
)
def test_settings_reject_invalid_product_configuration(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})  # type: ignore[arg-type]


def test_settings_repr_and_validation_errors_do_not_reveal_resources() -> None:
    secret = "super-secret-api-key"
    store = "fileSearchStores/private-store-name"
    settings = Settings(gemini_api_key=SecretStr(secret), gemini_file_search_store=store)

    assert secret not in repr(settings)
    assert store not in repr(settings)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            gemini_api_key=SecretStr(secret),
            gemini_file_search_store=store,
            gemini_max_retries=2,
        )

    rendered_error = str(exc_info.value)
    assert secret not in rendered_error
    assert store not in rendered_error
