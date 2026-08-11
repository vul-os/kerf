"""A saved base_url must actually reach the provider SDK.

Settings offers a "Base URL" field next to every API key so a gateway or an
OpenAI-compatible endpoint can be used without editing config. A field that is
stored and then ignored is worse than no field at all — it looks configured and
silently talks to the vendor instead. These tests assert the value arrives at
the SDK client, and that omitting it leaves each SDK's own default alone.

Each provider takes it differently: Anthropic and OpenAI accept a base_url
kwarg, Moonshot substitutes its own default, and google-genai wants an
HttpOptions object. So this checks the constructor call, not just the
attribute.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from kerf_chat.llm import (  # noqa: E402
    AnthropicProvider,
    CompleteRequest,
    GeminiProvider,
    MoonshotProvider,
    OpenAIProvider,
)

_REQ = CompleteRequest(model="m", system="s", messages=[])
_GATEWAY = "https://gateway.internal/v1"


def _run_anthropic(provider: AnthropicProvider) -> dict:
    """Call complete() with the SDK mocked; return the client's kwargs."""
    fake = MagicMock()
    with patch.dict(sys.modules):
        mod = MagicMock()
        sys.modules["anthropic"] = mod
        mod.Anthropic.return_value = fake
        try:
            provider.complete(_REQ)
        except Exception:
            # The mocked response won't satisfy the parsing below complete();
            # the client construction has already happened by then, which is
            # all this asserts.
            pass
        return mod.Anthropic.call_args.kwargs


def _run_openai(provider) -> dict:
    fake = MagicMock()
    with patch.dict(sys.modules):
        mod = MagicMock()
        sys.modules["openai"] = mod
        mod.OpenAI.return_value = fake
        try:
            provider.complete(_REQ)
        except Exception:
            pass
        return mod.OpenAI.call_args.kwargs


def test_anthropic_uses_the_configured_base_url():
    kwargs = _run_anthropic(AnthropicProvider("k", base_url=_GATEWAY))
    assert kwargs["base_url"] == _GATEWAY


def test_anthropic_omits_base_url_when_unset():
    """Passing base_url=None/"" would override the SDK default with nothing."""
    kwargs = _run_anthropic(AnthropicProvider("k"))
    assert "base_url" not in kwargs


def test_openai_uses_the_configured_base_url():
    kwargs = _run_openai(OpenAIProvider("k", base_url=_GATEWAY))
    assert kwargs["base_url"] == _GATEWAY


def test_openai_omits_base_url_when_unset():
    kwargs = _run_openai(OpenAIProvider("k"))
    assert "base_url" not in kwargs


def test_moonshot_falls_back_to_its_own_endpoint():
    """Moonshot has no public default in the SDK — the provider supplies it."""
    assert MoonshotProvider("k").base_url == MoonshotProvider._DEFAULT_BASE_URL
    kwargs = _run_openai(MoonshotProvider("k"))
    assert kwargs["base_url"] == "https://api.moonshot.cn/v1"


def test_moonshot_configured_base_url_wins():
    kwargs = _run_openai(MoonshotProvider("k", base_url=_GATEWAY))
    assert kwargs["base_url"] == _GATEWAY


def test_gemini_passes_base_url_via_http_options():
    genai = pytest.importorskip("google.genai")

    with patch.object(genai, "Client") as client_cls:
        GeminiProvider("k", base_url=_GATEWAY)._client()
        assert client_cls.call_args.kwargs["http_options"].base_url == _GATEWAY


def test_gemini_omits_http_options_when_unset():
    genai = pytest.importorskip("google.genai")

    with patch.object(genai, "Client") as client_cls:
        GeminiProvider("k")._client()
        assert "http_options" not in client_cls.call_args.kwargs
