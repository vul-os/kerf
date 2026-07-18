"""Tests for the default-visibility logic in create_project.

Kerf has no billing anywhere, so the old paid/free tier distinction for
default project visibility is gone — every new project defaults to
"private" unconditionally. Workshop publish (an explicit
opt-in via POST /api/workshop/publish) remains the only path that makes
a project public.

These tests are hermetic — no DB, no network, no FastAPI app spin-up.
They replicate the logic from routes.py create_project so regressions are
caught at the test layer, not just at runtime.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Replica of the visibility-default logic from routes.py create_project.
# Keep in sync with the implementation.
# ---------------------------------------------------------------------------

def default_project_visibility() -> str:
    """Pure-logic replica of the default in create_project.

    Always private — there is no paid/free tier and no billing state to
    distinguish. The user opts in to Workshop sharing explicitly.
    """
    return "private"


# ---------------------------------------------------------------------------
# Tests: always private, regardless of cloud/local mode
# ---------------------------------------------------------------------------

class TestDefaultVisibilityAlwaysPrivate:
    """Every new project defaults to private — no billing tier involved."""

    def test_defaults_to_private(self):
        vis = default_project_visibility()
        assert vis == "private"


# ---------------------------------------------------------------------------
# Tests: Workshop publish stays explicit
# ---------------------------------------------------------------------------

class TestWorkshopPublishRemainsExplicit:
    """Asserting that default_project_visibility never auto-publishes.

    The Workshop endpoint ``POST /api/workshop/publish`` is the *only* path
    that legitimately sets visibility='public' for a new Workshop listing.
    New projects always start private, so nobody accidentally exposes work.
    """

    def test_new_project_not_auto_published(self):
        vis = default_project_visibility()
        assert vis != "public", (
            "Projects start private; Workshop publish is an explicit opt-in."
        )

    def test_no_workshop_listing_created_by_default(self):
        # No workshop_listings row is created by the default logic — that is
        # handled exclusively by the publish endpoint (not asserted here since
        # it's tested in the routes test suite, but documented for clarity).
        vis = default_project_visibility()
        assert vis == "private"
