from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from artigas_mvp_backend.models import ErrorCode, UsagePayload

INPUT_USD_PER_MILLION = Decimal("1.50")
CACHED_INPUT_USD_PER_MILLION = Decimal("0.15")
OUTPUT_AND_THOUGHT_USD_PER_MILLION = Decimal("9.00")
MILLION = Decimal(1_000_000)

logger = logging.getLogger("artigas_mvp.usage")


@dataclass(frozen=True)
class NormalizedUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    thought_tokens: int
    total_tokens: int
    estimated_cost: Decimal

    def to_payload(self) -> UsagePayload:
        return UsagePayload(
            input_tokens=self.input_tokens,
            cached_input_tokens=self.cached_input_tokens,
            output_tokens=self.output_tokens,
            thought_tokens=self.thought_tokens,
            total_tokens=self.total_tokens,
            estimated_cost_usd=float(self.estimated_cost.quantize(Decimal("0.000001"))),
        )


def estimate_request_cost(
    input_tokens: int,
    output_tokens: int,
    thought_tokens: int,
    cached_input_tokens: int = 0,
    *,
    input_price_usd_per_million: Decimal = INPUT_USD_PER_MILLION,
    cached_input_price_usd_per_million: Decimal | None = CACHED_INPUT_USD_PER_MILLION,
    output_price_usd_per_million: Decimal = OUTPUT_AND_THOUGHT_USD_PER_MILLION,
) -> Decimal:
    uncached = max(input_tokens - cached_input_tokens, 0)
    input_cost = Decimal(uncached) * input_price_usd_per_million / MILLION
    cached_price = cached_input_price_usd_per_million or input_price_usd_per_million
    cached_cost = Decimal(cached_input_tokens) * cached_price / MILLION
    output_cost = Decimal(output_tokens + thought_tokens) * output_price_usd_per_million / MILLION
    return input_cost + cached_cost + output_cost


def _token_value(usage: object | None, *names: str) -> int:
    value: object = 0
    for name in names:
        if isinstance(usage, dict) and name in usage:
            value = usage[name]
            break
        candidate = getattr(usage, name, None) if usage is not None else None
        if candidate is not None:
            value = candidate
            break
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


def normalize_usage(
    provider_usage: object | None,
    *,
    input_price_usd_per_million: float | Decimal = INPUT_USD_PER_MILLION,
    cached_input_price_usd_per_million: float | Decimal = CACHED_INPUT_USD_PER_MILLION,
    output_price_usd_per_million: float | Decimal = OUTPUT_AND_THOUGHT_USD_PER_MILLION,
) -> NormalizedUsage:
    input_tokens = _token_value(provider_usage, "input_tokens", "total_input_tokens")
    cached_input_tokens = _token_value(provider_usage, "cached_input_tokens", "total_cached_tokens")
    if not cached_input_tokens and isinstance(provider_usage, dict):
        cached_input_tokens = _token_value(
            provider_usage.get("input_token_details"), "cache_read", "cached_tokens"
        )
    output_tokens = _token_value(provider_usage, "output_tokens", "total_output_tokens")
    thought_tokens = _token_value(provider_usage, "thought_tokens", "total_thought_tokens")
    nested_reasoning = False
    if not thought_tokens and isinstance(provider_usage, dict):
        thought_tokens = _token_value(
            provider_usage.get("output_token_details"), "reasoning", "reasoning_tokens"
        )
        nested_reasoning = thought_tokens > 0
    if nested_reasoning:
        output_tokens = max(output_tokens - thought_tokens, 0)
    provider_total = _token_value(provider_usage, "total_tokens")
    total_tokens = provider_total or input_tokens + output_tokens + thought_tokens
    return NormalizedUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        thought_tokens=thought_tokens,
        total_tokens=total_tokens,
        estimated_cost=estimate_request_cost(
            input_tokens,
            output_tokens,
            thought_tokens,
            cached_input_tokens,
            input_price_usd_per_million=Decimal(str(input_price_usd_per_million)),
            cached_input_price_usd_per_million=Decimal(str(cached_input_price_usd_per_million)),
            output_price_usd_per_million=Decimal(str(output_price_usd_per_million)),
        ),
    )


def _log_record(
    *,
    request_id: str,
    model: str,
    usage: NormalizedUsage,
    citation_count: int,
    latency_ms: int,
    error_code: ErrorCode | str | None,
    level: int,
) -> None:
    payload: dict[str, Any] = {
        "request_id": request_id,
        "model": model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "thought_tokens": usage.thought_tokens,
        "total_tokens": usage.total_tokens,
        "estimated_cost_usd": float(usage.estimated_cost.quantize(Decimal("0.000001"))),
        "citation_count": citation_count,
        "latency_ms": latency_ms,
        "error_code": error_code,
    }
    logger.log(level, json.dumps(payload, separators=(",", ":")))


def log_completion(
    request_id: str,
    model: str,
    usage: NormalizedUsage,
    citation_count: int,
    latency_ms: int,
    warning_threshold: Decimal,
) -> None:
    level = logging.WARNING if usage.estimated_cost > warning_threshold else logging.INFO
    _log_record(
        request_id=request_id,
        model=model,
        usage=usage,
        citation_count=citation_count,
        latency_ms=latency_ms,
        error_code=None,
        level=level,
    )


def log_error(
    *,
    request_id: str,
    model: str,
    error_code: ErrorCode,
    latency_ms: int,
    usage: NormalizedUsage | None = None,
) -> None:
    _log_record(
        request_id=request_id,
        model=model,
        usage=usage or normalize_usage(None),
        citation_count=0,
        latency_ms=latency_ms,
        error_code=error_code,
        level=logging.ERROR,
    )


def log_cancelled(*, request_id: str, model: str, latency_ms: int) -> None:
    _log_record(
        request_id=request_id,
        model=model,
        usage=normalize_usage(None),
        citation_count=0,
        latency_ms=latency_ms,
        error_code="cancelled",
        level=logging.INFO,
    )
