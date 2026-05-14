"""Tests for the workshop gallery set-primary toggle logic.

The endpoint uses toggle semantics:
  - Calling set-primary on a non-primary image → pins it, clears the previous primary.
  - Calling set-primary on the already-primary image → unpins it (no primary).

Because kerf-api tests run without a live database, these tests exercise the
pure-logic invariants by simulating the DB state transitions that the route
handler performs inside its transaction.
"""


# ---------------------------------------------------------------------------
# Helpers (mirror the backend toggle logic for offline verification)
# ---------------------------------------------------------------------------

def apply_set_primary(images: list[dict], target_id: str) -> list[dict]:
    """Pure-Python replica of the SQL transaction in set_primary_workshop_image.

    Steps:
      1. Find the target image; raise if missing.
      2. Remember whether it was already primary.
      3. Clear is_primary on every row in the project.
      4. If the target was NOT already primary, set is_primary = True on it.
    Returns the updated list (does not mutate the input).
    """
    import copy
    images = copy.deepcopy(images)
    target = next((img for img in images if img["id"] == target_id), None)
    if target is None:
        raise KeyError(f"image {target_id!r} not found")

    was_primary = target["is_primary"]

    # Step 3: clear all primaries.
    for img in images:
        img["is_primary"] = False

    # Step 4: promote unless it was already primary (toggle / unpin).
    if not was_primary:
        target["is_primary"] = True

    return images


def make_images(n: int) -> list[dict]:
    return [
        {"id": f"img-{i}", "sort_order": i, "is_primary": False, "caption": None}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Tests: pin
# ---------------------------------------------------------------------------

def test_pin_non_primary_sets_it_as_primary():
    images = make_images(3)
    result = apply_set_primary(images, "img-1")
    primary = [img for img in result if img["is_primary"]]
    assert len(primary) == 1
    assert primary[0]["id"] == "img-1"


def test_pin_clears_previous_primary():
    images = make_images(3)
    images[0]["is_primary"] = True  # img-0 is currently primary

    result = apply_set_primary(images, "img-2")
    # img-2 should now be primary; img-0 should be cleared.
    assert result[0]["is_primary"] is False
    assert result[2]["is_primary"] is True


def test_only_one_primary_after_pin():
    """Invariant: at most one image may be primary after any operation."""
    images = make_images(5)
    images[2]["is_primary"] = True

    result = apply_set_primary(images, "img-4")
    primaries = [img for img in result if img["is_primary"]]
    assert len(primaries) == 1


# ---------------------------------------------------------------------------
# Tests: toggle / unpin
# ---------------------------------------------------------------------------

def test_unpin_already_primary_leaves_no_primary():
    images = make_images(3)
    images[1]["is_primary"] = True  # img-1 is currently primary

    result = apply_set_primary(images, "img-1")
    primaries = [img for img in result if img["is_primary"]]
    assert primaries == [], "calling set-primary on the current primary should unpin it"


# ---------------------------------------------------------------------------
# Tests: error cases
# ---------------------------------------------------------------------------

def test_set_primary_missing_image_raises():
    images = make_images(2)
    try:
        apply_set_primary(images, "img-999")
        assert False, "should have raised KeyError"
    except KeyError:
        pass


# ---------------------------------------------------------------------------
# Tests: thumbnail URL resolution
# ---------------------------------------------------------------------------

def _resolve_thumbnail_url(project_id: str, primary_image_id, thumbnail_storage_key):
    """Mirrors the priority logic in _project_to_workshop_row."""
    pid = project_id
    if primary_image_id:
        return f"/api/projects/{pid}/workshop-images/{primary_image_id}/file"
    elif thumbnail_storage_key:
        return f"/api/projects/{pid}/thumbnail"
    return None


def test_pinned_primary_beats_auto_thumbnail():
    url = _resolve_thumbnail_url("proj-1", "img-abc", "storage/thumb.jpg")
    assert "workshop-images/img-abc/file" in url


def test_auto_thumbnail_used_when_no_primary():
    url = _resolve_thumbnail_url("proj-1", None, "storage/thumb.jpg")
    assert url == "/api/projects/proj-1/thumbnail"


def test_no_thumbnail_returns_none():
    url = _resolve_thumbnail_url("proj-1", None, None)
    assert url is None
