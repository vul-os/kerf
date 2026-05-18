"""Regression: /api/models must return current, resolvable model IDs.

The old stub hard-coded deprecated 2025-05-14 IDs, so chat picked an
unresolvable model AND (with the frontend not unwrapping {models})
there was no model dropdown at all.
"""
import asyncio

from kerf_api.routes import list_models


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_models_payload_shape_and_currency():
    out = _run(list_models())
    assert "models" in out and isinstance(out["models"], list)
    ids = [m["id"] for m in out["models"]]
    assert ids, "no models returned — dropdown would be empty"
    # The specific deprecated stub IDs must be gone.
    assert "claude-opus-4-20250514" not in ids
    assert "claude-sonnet-4-20250514" not in ids
    # Current flagship present.
    assert "claude-opus-4-7" in ids
    for m in out["models"]:
        assert m.get("id") and m.get("name")
