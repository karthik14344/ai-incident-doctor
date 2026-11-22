"""The Claude provider (DOCTOR_PROVIDER=anthropic), without calling the API."""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app import llm
from app.settings import ProviderConfig, provider_config

CFG = ProviderConfig(provider="anthropic", model="claude-opus-5-5", api_key="test-key",
                     price_in=4.0, price_out=20.0)


class FakeClient:
    """Stands in for anthropic.Anthropic; records the request, returns a canned reply."""

    def __init__(self, reply=None, error=None, **client_kwargs):
        self.client_kwargs, self.sent = client_kwargs, None
        outer = self

        class Messages:
            def create(self, **kwargs):
                outer.sent = kwargs
                if error:
                    raise error
                return reply

        self.beta = SimpleNamespace(messages=Messages())


def reply(text='{"summary": "x"}', stop_reason="end_turn"):
    return SimpleNamespace(
        model="claude-opus-5-5", stop_reason=stop_reason, stop_details=SimpleNamespace(category="cyber"),
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=800, cache_read_input_tokens=200,
                              cache_creation_input_tokens=0))


def install(monkeypatch, **fake):
    made = {}

    def factory(**kwargs):
        made["client"] = FakeClient(**fake, **kwargs)
        return made["client"]

    monkeypatch.setattr(anthropic, "Anthropic", factory)
    return made


def test_make_provider_picks_the_anthropic_sdk():
    assert isinstance(llm.make_provider(CFG), llm.AnthropicProvider)


def test_request_fits_claude_opus_5_5(monkeypatch):
    made = install(monkeypatch, reply=reply())
    comp = llm.make_provider(CFG).complete("SYS", "USER", {}, llm.CallBudget(3), max_tokens=2500)
    sent = made["client"].sent
    assert "temperature" not in sent and "thinking" not in sent      # thinking is always on; temperature 400s
    assert sent["max_tokens"] >= llm.AnthropicProvider.MIN_MAX_TOKENS  # room for thinking + the answer
    assert sent["output_config"]["effort"] == "high"                  # Opus 5.5 would default to medium
    assert sent["fallbacks"] == "default" and sent["betas"] == ["server-side-fallback-2026-07-01"]
    assert made["client"].client_kwargs["max_retries"] == 0           # the doctor does its own retries
    assert comp.text == '{"summary": "x"}' and comp.provider == "anthropic"
    assert comp.prompt_tokens == 1200 and comp.completion_tokens == 800
    assert comp.cost_usd == round(1200 / 1e6 * 4.0 + 800 / 1e6 * 20.0, 6)


def test_a_refusal_is_not_retried(monkeypatch):
    install(monkeypatch, reply=reply(text="", stop_reason="refusal"))
    budget = llm.CallBudget(5)
    with pytest.raises(llm.ProviderError) as exc:
        llm.make_provider(CFG).complete("SYS", "USER", {}, budget)
    assert not exc.value.retryable and "refused" in str(exc.value) and budget.used == 1


def test_rate_limits_are_retried(monkeypatch):
    resp = httpx2.Response(429, headers={"retry-after": "0"},
                           request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    install(monkeypatch, error=anthropic.RateLimitError("slow down", response=resp, body=None))
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    budget = llm.CallBudget(10)
    with pytest.raises(llm.ProviderError):
        llm.AnthropicProvider(CFG, max_attempts=3).complete("SYS", "USER", {}, budget)
    assert budget.used == 3


def test_claude_prices_come_from_the_model(monkeypatch):
    monkeypatch.setenv("DOCTOR_PROVIDER", "anthropic")
    monkeypatch.setenv("DOCTOR_MODEL", "claude-opus-5-5")
    cfg = provider_config("DOCTOR")
    assert (cfg.price_in, cfg.price_out) == (4.0, 20.0)
