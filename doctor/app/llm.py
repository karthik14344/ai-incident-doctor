"""Pluggable reasoning providers: GLM, Gemini, Groq, OpenAI (all through the
OpenAI-compatible client) and local Ollama.

Selected in .env:
    DOCTOR_PROVIDER=glm            DOCTOR_MODEL=glm-4.6     DOCTOR_API_KEY=...
    DOCTOR_FALLBACK_PROVIDER=ollama DOCTOR_FALLBACK_MODEL=llama3.2

Ollama is the one exception to "OpenAI-compatible": its /v1 endpoint silently
truncates every prompt to 2048 tokens and ignores num_ctx (measured - see
DECISIONS.md), which would hand a local model only the tail of the evidence.
The Ollama provider therefore uses the native /api/chat with an explicit
context size and the JSON schema as its `format` (constrained decoding).

Every provider gets: retry with exponential backoff and jitter on rate limits,
timeouts and 5xx (honouring Retry-After), and a per-run call budget, because
the evaluation makes hundreds of calls in a row.
"""

import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from app.settings import ProviderConfig


class BudgetExceeded(RuntimeError):
    pass


class ProviderError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class CallBudget:
    max_calls: int
    used: int = 0

    def take(self) -> None:
        if self.used >= self.max_calls:
            raise BudgetExceeded(f"call budget of {self.max_calls} exhausted")
        self.used += 1


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    attempts: int = 1
    cost_usd: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


def _sleep_for(attempt: int, retry_after: Optional[str]) -> float:
    if retry_after:
        try:
            return min(float(retry_after), 60.0)
        except ValueError:
            pass
    return min(2 ** attempt, 60) + random.uniform(0, 1)


class Provider:
    def __init__(self, cfg: ProviderConfig, timeout_s: float = 240, max_attempts: int = 5):
        self.cfg = cfg
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts

    def complete(self, system: str, user: str, schema: Dict[str, Any], budget: CallBudget,
                 max_tokens: int = 2500, temperature: float = 0.2, seed: int = 7) -> Completion:
        last: Optional[Exception] = None
        for attempt in range(self.max_attempts):
            budget.take()
            started = time.perf_counter()
            try:
                result = self._call(system, user, schema, max_tokens, temperature, seed)
                result.seconds = round(time.perf_counter() - started, 2)
                result.attempts = attempt + 1
                result.cost_usd = round(result.prompt_tokens / 1e6 * self.cfg.price_in
                                        + result.completion_tokens / 1e6 * self.cfg.price_out, 6)
                return result
            except ProviderError as exc:
                last = exc
                if not exc.retryable or attempt == self.max_attempts - 1:
                    raise
                time.sleep(_sleep_for(attempt, getattr(exc, "retry_after", None)))
        raise ProviderError(f"gave up after {self.max_attempts} attempts: {last}")

    def _call(self, system, user, schema, max_tokens, temperature, seed) -> Completion:
        raise NotImplementedError


# Verified by request: Gemini's OpenAI-compatible endpoint honours json_schema
# (4/4 schema-valid answers, against 0/3 usable with json_object; D-83).
STRUCTURED_OUTPUT_PROVIDERS = {"gemini", "openai"}

# Extra request fields per provider. GLM's flash models think by default; on a
# real doctor prompt the thinking used the whole 2,500-token allowance and left
# an empty answer (78 s), while with thinking disabled the answer was complete in
# 28 s. The local models do not think either, so this keeps the comparison even (D-84).
PROVIDER_EXTRA_BODY = {"glm": {"thinking": {"type": "disabled"}}}


class OpenAICompatible(Provider):
    def _call(self, system, user, schema, max_tokens, temperature, seed) -> Completion:
        import openai

        if not self.cfg.api_key:
            raise ProviderError(f"{self.cfg.provider}: no API key (DOCTOR_API_KEY)", retryable=False)
        client = openai.OpenAI(base_url=self.cfg.base_url, api_key=self.cfg.api_key,
                               timeout=self.timeout_s, max_retries=0)
        # Providers that accept a JSON schema get the same constraint Ollama gets
        # through `format`; the others can only be asked for "a JSON object".
        if self.cfg.provider in STRUCTURED_OUTPUT_PROVIDERS and schema:
            response_format = {"type": "json_schema", "json_schema": {"name": "diagnosis", "schema": schema}}
        else:
            response_format = {"type": "json_object"}
        try:
            r = client.chat.completions.create(
                model=self.cfg.model, temperature=temperature, max_tokens=max_tokens,
                response_format=response_format, extra_body=PROVIDER_EXTRA_BODY.get(self.cfg.provider),
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        except (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
                openai.InternalServerError) as exc:
            err = ProviderError(f"{type(exc).__name__}: {exc}", retryable=True)
            response = getattr(exc, "response", None)
            err.retry_after = response.headers.get("retry-after") if response is not None else None
            raise err from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"HTTP {exc.status_code}: {str(exc)[:300]}", retryable=False) from exc
        usage = r.usage
        return Completion(text=r.choices[0].message.content or "", provider=self.cfg.provider, model=self.cfg.model,
                          prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                          completion_tokens=getattr(usage, "completion_tokens", 0) or 0)


class OllamaNative(Provider):
    def _call(self, system, user, schema, max_tokens, temperature, seed) -> Completion:
        from app.settings import SETTINGS

        body = {"model": self.cfg.model, "stream": False, "format": schema,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"num_ctx": SETTINGS.ollama_num_ctx, "temperature": temperature,
                            "num_predict": max_tokens, "seed": seed}}
        try:
            r = httpx.post(f"{self.cfg.base_url}/api/chat", json=body, timeout=self.timeout_s, trust_env=False)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}", retryable=True) from exc
        if r.status_code >= 500 or r.status_code == 429:
            raise ProviderError(f"HTTP {r.status_code}: {r.text[:200]}", retryable=True)
        if r.status_code >= 400:
            raise ProviderError(f"HTTP {r.status_code}: {r.text[:200]}", retryable=False)
        data = r.json()
        return Completion(text=(data.get("message") or {}).get("content", ""), provider="ollama",
                          model=self.cfg.model, prompt_tokens=data.get("prompt_eval_count", 0) or 0,
                          completion_tokens=data.get("eval_count", 0) or 0,
                          raw={"total_duration_ms": (data.get("total_duration") or 0) / 1e6})


def make_provider(cfg: ProviderConfig) -> Provider:
    return OllamaNative(cfg) if cfg.provider == "ollama" else OpenAICompatible(cfg)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str) -> Any:
    """The model's JSON, tolerating code fences, reasoning preambles and trailing prose."""
    text = (text or "").strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object in model output")


def providers_in_order(primary: Optional[ProviderConfig], fallback: Optional[ProviderConfig]) -> List[ProviderConfig]:
    return [p for p in (primary, fallback) if p is not None]
