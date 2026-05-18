"""Regression: temperature must be OMITTED when unset, never null.

CompleteRequest.temperature defaults to 0.0. Every provider used to
pass `temperature=req.temperature if req.temperature > 0 else None`,
i.e. an explicit `temperature=None`. The Anthropic SDK serialises that
to JSON `null`, and the API now rejects it with HTTP 400
"temperature: Input should be a valid number" — which broke chat for
*every* model (surfaced to users as "The model returned an error").

Fix: only include temperature when explicitly set (>0); otherwise omit
the parameter entirely. Guards all three providers (Anthropic +
OpenAI + Moonshot) at the source level — same approach as
test_tool_choice_object.py.
"""
import ast
import pathlib

_LLM = (
    pathlib.Path(__file__).resolve().parents[1] / "src/kerf_chat/llm.py"
).read_text()


def test_no_explicit_none_temperature_anywhere():
    # The exact buggy pattern must be gone from every provider.
    assert "temperature=req.temperature if req.temperature > 0 else None" not in _LLM, (
        "explicit temperature=None is rejected by Anthropic (HTTP 400)"
    )


def test_temperature_is_conditionally_included():
    # Anthropic: built into the kwargs dict only when set.
    assert 'if req.temperature > 0:' in _LLM
    assert '_kw["temperature"] = req.temperature' in _LLM
    # OpenAI / Moonshot: folded into extra_body only when set.
    assert 'extra_body["temperature"] = req.temperature' in _LLM
    # Two OpenAI-compatible call sites both guarded.
    assert _LLM.count('extra_body["temperature"] = req.temperature') == 2


def test_llm_module_still_parses():
    ast.parse(_LLM)


# ── Behavioural: actually invoke the provider with a mocked client ──────
from unittest.mock import patch  # noqa: E402

from kerf_chat.llm import AnthropicProvider, CompleteRequest  # noqa: E402


class _Blk:
    type = "text"
    text = "hi"


class _Usage:
    input_tokens = 3
    output_tokens = 2


class _Resp:
    content = [_Blk()]
    stop_reason = "end_turn"
    usage = _Usage()


def _fake_anthropic(captured):
    class _Messages:
        def create(self, **kw):
            captured.update(kw)
            return _Resp()

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    return _Client


def _complete(temperature):
    captured: dict = {}
    req = CompleteRequest(model="claude-opus-4-7", system="sys", temperature=temperature)
    with patch("anthropic.Anthropic", _fake_anthropic(captured)):
        resp = AnthropicProvider(api_key="k", prompt_cache=False).complete(req)
    return captured, resp


def test_default_temperature_is_not_sent():
    # 0.0 default must NOT reach the API (this is the prod incident:
    # temperature=null → Anthropic 400 → "model returned an error").
    captured, resp = _complete(0.0)
    assert "temperature" not in captured
    assert resp.content == "hi"
    assert resp.input_tokens == 3 and resp.output_tokens == 2


def test_explicit_temperature_is_forwarded():
    captured, _ = _complete(0.7)
    assert captured.get("temperature") == 0.7
