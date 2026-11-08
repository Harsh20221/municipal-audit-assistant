"""LLM client. The provider is chosen from the environment. Keys stay out of code."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from core.config import LLMSettings, load_settings

logger = logging.getLogger("core.llm")
_RETRYABLE = {"APITimeoutError", "APIConnectionError", "RateLimitError", "InternalServerError"}
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_GROQ_MODEL = "openai/gpt-oss-120b"


@dataclass
class UsageTotals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cache_hits: int = 0
    cached_input_tokens: int = 0
    cached_output_tokens: int = 0
    fresh_calls: int = 0
    fresh_input_tokens: int = 0
    fresh_output_tokens: int = 0
    fresh_cost_usd: float = 0.0

    def add(self, response: LLMResponse) -> None:
        self.calls += 1
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        self.cost_usd += response.cost_usd
        if response.cached:
            self.cache_hits += 1
            self.cached_input_tokens += response.input_tokens
            self.cached_output_tokens += response.output_tokens
        else:
            self.fresh_calls += 1
            self.fresh_input_tokens += response.input_tokens
            self.fresh_output_tokens += response.output_tokens
            self.fresh_cost_usd += response.cost_usd


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    cached: bool = False
    json_data: dict | list | None = None


@dataclass
class LLMClient(ABC):
    settings: LLMSettings
    totals: UsageTotals = field(default_factory=UsageTotals)

    def complete_text(self, prompt: str) -> LLMResponse:
        return self._cached(prompt, json_mode=False)

    def complete_json(self, prompt: str) -> LLMResponse:
        response = self._cached(prompt, json_mode=True)
        response.json_data = parse_json_text(response.text)
        return response

    @abstractmethod
    def _complete_uncached(self, prompt: str, *, json_mode: bool) -> LLMResponse:
        """Call the provider. Do not read or log API keys."""

    def cache_model(self) -> str:
        return self.settings.model

    def _cached(self, prompt: str, *, json_mode: bool) -> LLMResponse:
        key = hashlib.sha256(
            f"{self.cache_model()}\n{int(json_mode)}\n{prompt}".encode()
        ).hexdigest()
        path = self.settings.cache_dir / f"{key}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            response = LLMResponse(
                text=payload["text"],
                input_tokens=int(payload["input_tokens"]),
                output_tokens=int(payload["output_tokens"]),
                cost_usd=0.0,
                model=payload["model"],
                cached=True,
            )
            self.totals.add(response)
            logger.info(
                "llm cache hit model=%s input_tokens=%s output_tokens=%s",
                response.model,
                response.input_tokens,
                response.output_tokens,
            )
            return response
        response = self._complete_with_retry(prompt, json_mode=json_mode)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "text": response.text,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "model": response.model,
                }
            ),
            encoding="utf-8",
        )
        self.totals.add(response)
        logger.info(
            "llm call model=%s input_tokens=%s output_tokens=%s cost_usd=%.6f",
            response.model,
            response.input_tokens,
            response.output_tokens,
            response.cost_usd,
        )
        return response

    def _complete_with_retry(self, prompt: str, *, json_mode: bool) -> LLMResponse:
        delay = 0.5
        attempt = 0
        while True:
            try:
                return self._complete_uncached(prompt, json_mode=json_mode)
            except Exception as exc:
                if not _should_retry(exc, attempt, 8):
                    raise
                wait = _retry_delay(exc, delay)
                logger.info("llm retry in %.1fs after %s", wait, type(exc).__name__)
                time.sleep(wait)
                delay = min(delay * 2, 20)
                attempt += 1


class FakeLLMClient(LLMClient):
    """Reads labeled lines from the document block. Tests may pass a script instead."""

    def __init__(self, settings: LLMSettings | None = None, script: list[str] | None = None):
        super().__init__(settings or load_settings().llm)
        self.script = list(script) if script is not None else None

    def cache_model(self) -> str:
        return "fake"

    def _cached(self, prompt: str, *, json_mode: bool) -> LLMResponse:
        if self.script is not None:
            response = self._complete_with_retry(prompt, json_mode=json_mode)
            self.totals.add(response)
            return response
        return super()._cached(prompt, json_mode=json_mode)

    def _complete_uncached(self, prompt: str, *, json_mode: bool) -> LLMResponse:
        if self.script is not None:
            if not self.script:
                raise RuntimeError("FakeLLMClient script is empty")
            text = self.script.pop(0)
        elif json_mode:
            text = json.dumps(parse_document_fields(prompt))
        else:
            text = _fake_classification(prompt)
        return LLMResponse(
            text=text,
            input_tokens=_estimate_tokens(prompt),
            output_tokens=_estimate_tokens(text),
            cost_usd=0.0,
            model="fake",
        )


class OpenAIClient(LLMClient):
    """OpenAI-compatible chat client. Groq uses the same SDK with its own base URL."""

    def __init__(self, settings: LLMSettings | None = None):
        super().__init__(settings or load_settings().llm)
        self.provider = _live_provider()
        if self.provider == "groq":
            key = os.getenv("GROQ_API_KEY", "").strip()
            if not key:
                raise RuntimeError(
                    "GROQ_API_KEY is missing. Add it to .env. It is not read from code."
                )
            base_url = _GROQ_BASE_URL
            self._model = _groq_model(self.settings.model)
        else:
            key = os.getenv("OPENAI_API_KEY", "").strip()
            if not key:
                raise RuntimeError(
                    "OPENAI_API_KEY is missing. Add it to .env. It is not read from code."
                )
            base_url = None
            self._model = self.settings.model
        from openai import OpenAI

        self._client = OpenAI(
            api_key=key,
            base_url=base_url,
            timeout=self.settings.timeout_seconds,
            max_retries=0,
        )

    def cache_model(self) -> str:
        return self._model

    def _complete_uncached(self, prompt: str, *, json_mode: bool) -> LLMResponse:
        try:
            completion = self._create(prompt, json_mode=json_mode)
        except Exception as exc:
            if not json_mode or "response_format" not in str(exc):
                raise
            completion = self._create(prompt, json_mode=False)
        text = completion.choices[0].message.content or ""
        usage = completion.usage
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        if self.provider == "openai":
            cost = (
                input_tokens * self.settings.input_cost_per_million
                + output_tokens * self.settings.output_cost_per_million
            ) / 1_000_000
        else:
            cost = 0.0
        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=self._model,
        )

    def _create(self, prompt: str, *, json_mode: bool):
        kwargs = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return self._client.chat.completions.create(**kwargs)


def make_client(*, live: bool, settings: LLMSettings | None = None) -> LLMClient:
    loaded = settings or load_settings().llm
    if live:
        return OpenAIClient(loaded)
    return FakeLLMClient(loaded)


def _live_provider() -> str:
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if provider in {"openai", "groq"}:
        return provider
    if os.getenv("GROQ_API_KEY", "").strip():
        return "groq"
    return "openai"


def _groq_model(configured: str) -> str:
    model = (os.getenv("LLM_MODEL") or configured or "").strip()
    if not model or model.startswith("gpt-"):
        return _GROQ_MODEL
    return model


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "insufficient_quota" in text or "credit_balance_exhausted" in text


def _should_retry(exc: Exception, attempt: int, attempts: int) -> bool:
    if attempt >= attempts - 1 or _is_quota_error(exc):
        return False
    return type(exc).__name__ in _RETRYABLE


def _retry_delay(exc: Exception, fallback: float) -> float:
    match = re.search(r"try again in ([0-9]+(?:\.[0-9]+)?)s", str(exc), re.IGNORECASE)
    if match:
        return float(match.group(1)) + 0.5
    return fallback


def parse_json_text(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("Extraction JSON must be an object")
    return payload


def parse_document_fields(prompt: str) -> dict[str, str]:
    match = re.search(r"DOCUMENT_TEXT_START\n(.*)\nDOCUMENT_TEXT_END", prompt, re.DOTALL)
    if match is None:
        return {}
    fields: dict[str, str] = {}
    chunks: list[str] = []
    for line in match.group(1).splitlines():
        if " | " in line and ":" in line:
            chunks.extend(part.strip() for part in line.split(" | "))
        else:
            chunks.append(line.strip())
    for chunk in chunks:
        found = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", chunk)
        if found:
            fields[found.group(1)] = found.group(2).strip()
    return fields


def _fake_classification(prompt: str) -> str:
    lowered = prompt.lower()
    for name in (
        "assessment_form",
        "tax_bill",
        "payment_receipt",
        "tender_award_notice",
        "work_order",
        "invoice",
        "progress_report",
    ):
        if name in lowered:
            return name
    return "unknown"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def cache_dir_from(settings: LLMSettings, override: Path | None = None) -> LLMSettings:
    if override is None:
        return settings
    return LLMSettings(
        provider=settings.provider,
        model=settings.model,
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
        cache_dir=override,
        input_cost_per_million=settings.input_cost_per_million,
        output_cost_per_million=settings.output_cost_per_million,
    )
