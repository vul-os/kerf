"""Regression: /api/models is DYNAMIC by configured provider keys.

It must reflect the LLM registry's available() (CATALOG filtered to
providers whose API key is set), not a hard-coded Anthropic-only list
(which is why only Anthropic showed despite other keys being present).
"""
import asyncio
from unittest.mock import MagicMock, patch

from kerf_api.routes import list_models


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _fake_registry(available):
    reg = MagicMock()
    reg.available.return_value = available
    reg.default.return_value = "claude-opus-4-7"
    return reg


def test_multi_provider_passthrough():
    avail = [
        {"id": "claude-opus-4-7", "provider": "anthropic", "label": "Claude Opus 4.7"},
        {"id": "gpt-4o", "provider": "openai", "label": "GPT-4o"},
        {"id": "gemini-2.5-pro", "provider": "gemini", "label": "Gemini 2.5 Pro"},
    ]
    with patch("kerf_api.routes._get_llm_registry", return_value=_fake_registry(avail)):
        out = _run(list_models())
    providers = {m["provider"] for m in out["models"]}
    assert providers == {"anthropic", "openai", "gemini"}, (
        f"not dynamic per configured providers: {providers}"
    )
    for m in out["models"]:
        assert m["id"] and m["name"] and m["label"]
    # No deprecated dated 4-series ids from the old stub.
    assert not any(i in ("claude-opus-4-20250514", "claude-sonnet-4-20250514")
                   for i in (m["id"] for m in out["models"]))


def test_only_configured_provider_shows():
    avail = [{"id": "gpt-4o", "provider": "openai", "label": "GPT-4o"}]
    with patch("kerf_api.routes._get_llm_registry", return_value=_fake_registry(avail)):
        out = _run(list_models())
    assert [m["provider"] for m in out["models"]] == ["openai"]


def test_no_keys_falls_back_nonempty():
    with patch("kerf_api.routes._get_llm_registry", return_value=_fake_registry([])):
        out = _run(list_models())
    assert len(out["models"]) >= 1  # dropdown never empty
