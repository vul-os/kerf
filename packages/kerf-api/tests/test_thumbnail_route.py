"""Regression: GET /projects/{pid}/thumbnail must exist.

Live dev bug: project/Workshop thumbnails 404'd for ALL kinds because
only @router.post("/projects/{pid}/thumbnail") was defined — there was
no GET route, so every thumbnail_url fell through to the SPA 404.
This pins that both verbs are registered.
"""
from kerf_api.routes import router


def _methods_for(path: str) -> set[str]:
    methods: set[str] = set()
    for r in router.routes:
        if getattr(r, "path", None) == path:
            methods |= set(getattr(r, "methods", set()) or set())
    return methods


def test_thumbnail_has_both_get_and_post():
    m = _methods_for("/projects/{pid}/thumbnail")
    assert "POST" in m, "thumbnail upload route missing"
    assert "GET" in m, (
        "GET /projects/{pid}/thumbnail missing — thumbnails 404 for "
        "every project/Workshop card"
    )


def test_cover_get_still_present():
    # serve_project_cover is the template the thumbnail GET mirrors.
    assert "GET" in _methods_for("/projects/{pid}/cover")
