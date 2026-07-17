"""Regression: chat-model CATALOG must list the latest provider models.

User report (2026-05-19): "gemini latest aren't picking up". The CATALOG
used to top out at gemini-2.5-pro / gemini-2.5-flash even though the rest
of the system already knew about Gemini 3 — the model picker didn't.

This test pins the catalog so a refactor can't silently drop the latest
ids again.
"""
from __future__ import annotations

from kerf_chat.llm import CATALOG


def _ids() -> set[str]:
    return {m["id"] for m in CATALOG}


def _by_provider(provider: str) -> list[dict]:
    return [m for m in CATALOG if m["provider"] == provider]


# ── Gemini ─────────────────────────────────────────────────────────────────


def test_catalog_lists_gemini_3_flash_preview():
    """Gemini 3 Flash (preview) — explicitly requested by the user."""
    assert "gemini-3-flash-preview" in _ids(), (
        f"gemini-3-flash-preview must be in CATALOG; ids={sorted(_ids())}"
    )


def test_catalog_lists_gemini_3_pro_preview():
    assert "gemini-3-pro-preview" in _ids()


def test_catalog_keeps_gemini_2_5():
    """Don't drop 2.5 — it's the stable line; 3.x is preview."""
    assert "gemini-2.5-pro" in _ids()
    assert "gemini-2.5-flash" in _ids()


def test_gemini_provider_has_at_least_4_models():
    gemini = _by_provider("gemini")
    assert len(gemini) >= 4, (
        f"expected ≥4 Gemini models (3-pro, 3-flash, 2.5-pro, 2.5-flash); "
        f"got {[m['id'] for m in gemini]}"
    )


# ── Anthropic ──────────────────────────────────────────────────────────────


def test_catalog_lists_claude_4_lineup():
    """Claude 4.x is the current generation per CLAUDE.md."""
    assert "claude-opus-4-7" in _ids()
    assert "claude-sonnet-4-6" in _ids()
    assert "claude-haiku-4-5" in _ids()


# ── Provider-label consistency ────────────────────────────────────────────


def test_every_model_has_a_label_and_context_window():
    for m in CATALOG:
        assert "id" in m and m["id"], f"missing id: {m}"
        assert "provider" in m and m["provider"], f"missing provider: {m}"
        assert "label" in m and m["label"], f"missing label: {m}"
        assert m.get("context_window", 0) > 0, f"context_window must be positive: {m}"


def test_no_duplicate_ids():
    ids = [m["id"] for m in CATALOG]
    assert len(ids) == len(set(ids)), f"duplicate ids: {sorted(ids)}"
