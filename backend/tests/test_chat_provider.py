from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from artigas_mvp_backend.config import Settings
from artigas_mvp_backend.services.chat import create_chat_model


def configured(**changes: Any) -> Settings:
    return Settings(
        groq_api_key=SecretStr("groq-secret"),
        voyage_api_key=SecretStr("voyage-secret"),
        **changes,
    )


def test_default_configuration_selects_groq_gpt_oss(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeGroq:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("artigas_mvp_backend.services.chat.ChatGroq", FakeGroq)

    create_chat_model(configured())

    api_key = captured.pop("api_key")
    assert isinstance(api_key, SecretStr)
    assert api_key.get_secret_value() == "groq-secret"
    assert captured == {
        "model": "openai/gpt-oss-120b",
        "temperature": 0.6,
        "reasoning_effort": "medium",
        "max_tokens": 4096,
        "timeout": 45.0,
        "max_retries": 1,
    }


def test_chat_generation_controls_are_passed_to_groq_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeGroq:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("artigas_mvp_backend.services.chat.ChatGroq", FakeGroq)

    create_chat_model(configured(chat_temperature=0.8, chat_reasoning_effort="high"))

    assert captured["temperature"] == 0.8
    assert captured["reasoning_effort"] == "high"
    assert "reasoning_format" not in captured


def test_non_default_model_requires_explicit_pricing() -> None:
    with pytest.raises(ValidationError, match="pricing"):
        configured(chat_model="different-model")


def test_settings_repr_does_not_reveal_provider_secrets() -> None:
    settings = configured()

    rendered = repr(settings)

    assert "groq-secret" not in rendered
    assert "voyage-secret" not in rendered
