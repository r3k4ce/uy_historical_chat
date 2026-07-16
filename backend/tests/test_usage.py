import json
import logging
from decimal import Decimal
from types import SimpleNamespace

from artigas_mvp_backend.services.usage import (
    estimate_request_cost,
    log_completion,
    log_error,
    normalize_usage,
)


def test_estimate_request_cost_includes_thought_tokens_once() -> None:
    assert estimate_request_cost(4200, 510, 380) == Decimal("0.01431")


def test_estimate_request_cost_prices_cached_input_separately() -> None:
    assert estimate_request_cost(1000, 0, 0, 400) == Decimal("0.00096")


def test_normalize_usage_uses_provider_total_when_present() -> None:
    usage = normalize_usage(
        SimpleNamespace(
            total_input_tokens=100,
            total_cached_tokens=20,
            total_output_tokens=30,
            total_thought_tokens=10,
            total_tokens=999,
        )
    )
    assert usage.total_tokens == 999
    assert usage.to_payload().estimated_cost_usd == 0.000483


def test_normalize_usage_defaults_components_and_calculates_total() -> None:
    empty = normalize_usage(None)
    assert empty.total_tokens == 0
    assert empty.estimated_cost == Decimal(0)

    partial = normalize_usage(SimpleNamespace(total_input_tokens=2))
    assert partial.total_tokens == 2


def test_normalize_usage_reads_langchain_cache_and_reasoning_details() -> None:
    usage = normalize_usage(
        {
            "input_tokens": 100,
            "output_tokens": 30,
            "total_tokens": 130,
            "input_token_details": {"cache_read": 20},
            "output_token_details": {"reasoning": 8},
        }
    )

    assert usage.cached_input_tokens == 20
    assert usage.thought_tokens == 8
    assert usage.output_tokens == 22
    assert usage.total_tokens == 130


def test_completion_log_contains_only_safe_metadata(caplog) -> None:
    usage = normalize_usage(SimpleNamespace(total_input_tokens=10))
    with caplog.at_level(logging.INFO, logger="artigas_mvp.usage"):
        log_completion(
            request_id="request-1",
            model="openai/gpt-oss-120b",
            usage=usage,
            citation_count=2,
            latency_ms=15,
            warning_threshold=Decimal("0"),
        )

    record = json.loads(caplog.records[-1].message)
    assert caplog.records[-1].levelno == logging.WARNING
    assert record == {
        "request_id": "request-1",
        "model": "openai/gpt-oss-120b",
        "input_tokens": 10,
        "output_tokens": 0,
        "thought_tokens": 0,
        "total_tokens": 10,
        "estimated_cost_usd": 0.000015,
        "citation_count": 2,
        "latency_ms": 15,
        "error_code": None,
    }
    assert "prompt" not in caplog.text
    assert "store" not in caplog.text
    assert "api_key" not in caplog.text


def test_warning_threshold_is_strictly_greater(caplog) -> None:
    usage = normalize_usage(SimpleNamespace(total_input_tokens=1_000_000))
    with caplog.at_level(logging.INFO, logger="artigas_mvp.usage"):
        log_completion("r", "openai/gpt-oss-120b", usage, 0, 1, Decimal("1.50"))
    assert caplog.records[-1].levelno == logging.INFO


def test_error_log_uses_same_safe_shape(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="artigas_mvp.usage"):
        log_error(
            request_id="request-2",
            model="openai/gpt-oss-120b",
            error_code="provider_timeout",
            latency_ms=20,
        )
    record = json.loads(caplog.records[-1].message)
    assert record["error_code"] == "provider_timeout"
    assert record["input_tokens"] == 0
    assert record["citation_count"] == 0
