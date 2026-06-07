"""
test_worksharing.py — pytest suite for kerf_bim.worksharing.

Tests
-----
1.  workset_create adds a workset to the manifest
2.  workset_create raises on duplicate workset_id
3.  workset_assign_element moves element into workset
4.  workset_assign_element returns False for unknown workset
5.  workset_set_owner sets owner on unowned workset
6.  workset_set_owner enforces current-owner check
7.  borrow_element succeeds for unlocked element
8.  borrow_element BLOCKS second borrower (conflict)
9.  release_element frees the borrow
10. release_element returns False if wrong user
11. borrow_element: re-borrow by same user refreshes expiry
12. borrow_element respects workset-level ownership borrow
13. update_local_data stores edit payload for borrower
14. update_local_data fails for non-borrower
15. sync_to_central pushes non-conflicting edits to central
16. sync_to_central detects conflict when two users edited the same element
17. sync_to_central releases borrows after successful sync
18. sync_to_central pulls all central elements for the syncing user
19. worksharing_status returns correct counts
20. WorksharingManifest round-trips through JSON
21. workset_assign_element removes element from previous workset
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest

from kerf_bim.worksharing import (
    WorksharingManifest,
    Workset,
    ElementBorrowEntry,
    ConflictRecord,
    SyncResult,
    workset_create,
    workset_assign_element,
    workset_set_owner,
    borrow_element,
    release_element,
    update_local_data,
    sync_to_central,
    worksharing_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _iso(dt: datetime) -> str:
    return dt.strftime(_FMT)


def _past(hours: float = 1.0) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(hours=hours))


def _future(hours: float = 8.0) -> str:
    return _iso(datetime.now(timezone.utc) + timedelta(hours=hours))


def _now() -> str:
    return _iso(datetime.now(timezone.utc))


def _empty_manifest(project_id: str = "proj-1") -> WorksharingManifest:
    return WorksharingManifest(project_id=project_id)


# ---------------------------------------------------------------------------
# 1. workset_create adds workset
# ---------------------------------------------------------------------------

class TestWorksetCreate:
    def test_create_adds_workset(self):
        m = _empty_manifest()
        ws = workset_create(m, "ws-arch", "Architecture", "alice@test.com")
        assert ws.workset_id == "ws-arch"
        assert ws.name == "Architecture"
        assert ws.owner_email == "alice@test.com"
        assert len(m.worksets) == 1

    def test_create_raises_on_duplicate(self):
        m = _empty_manifest()
        workset_create(m, "ws-arch", "Architecture")
        with pytest.raises(ValueError, match="ws-arch"):
            workset_create(m, "ws-arch", "Architecture 2")

    def test_create_raises_on_empty_id(self):
        m = _empty_manifest()
        with pytest.raises(ValueError):
            workset_create(m, "", "Bad")


# ---------------------------------------------------------------------------
# 3 & 4. workset_assign_element
# ---------------------------------------------------------------------------

class TestWorksetAssignElement:
    def test_assign_element_succeeds(self):
        m = _empty_manifest()
        workset_create(m, "ws-arch", "Architecture")
        ok = workset_assign_element(m, "wall-001", "ws-arch")
        assert ok is True
        ws = m._find_workset("ws-arch")
        assert "wall-001" in ws.element_ids

    def test_assign_element_fails_for_unknown_workset(self):
        m = _empty_manifest()
        ok = workset_assign_element(m, "wall-001", "ws-ghost")
        assert ok is False

    def test_assign_moves_from_previous_workset(self):
        m = _empty_manifest()
        workset_create(m, "ws-arch", "Architecture")
        workset_create(m, "ws-str", "Structure")
        workset_assign_element(m, "wall-001", "ws-arch")
        workset_assign_element(m, "wall-001", "ws-str")  # reassign
        arch_ws = m._find_workset("ws-arch")
        str_ws = m._find_workset("ws-str")
        assert "wall-001" not in arch_ws.element_ids
        assert "wall-001" in str_ws.element_ids


# ---------------------------------------------------------------------------
# 5 & 6. workset_set_owner
# ---------------------------------------------------------------------------

class TestWorksetSetOwner:
    def test_set_owner_on_unowned_workset(self):
        m = _empty_manifest()
        workset_create(m, "ws-arch", "Architecture")
        ok = workset_set_owner(m, "ws-arch", "alice@test.com")
        assert ok is True
        ws = m._find_workset("ws-arch")
        assert ws.owner_email == "alice@test.com"

    def test_set_owner_enforces_current_owner(self):
        m = _empty_manifest()
        workset_create(m, "ws-arch", "Architecture", "alice@test.com")
        # bob cannot take ownership from alice
        ok = workset_set_owner(m, "ws-arch", "bob@test.com", requesting_email="bob@test.com")
        assert ok is False
        ws = m._find_workset("ws-arch")
        assert ws.owner_email == "alice@test.com"

    def test_set_owner_transfer_by_current_owner(self):
        m = _empty_manifest()
        workset_create(m, "ws-arch", "Architecture", "alice@test.com")
        ok = workset_set_owner(m, "ws-arch", "bob@test.com", requesting_email="alice@test.com")
        assert ok is True
        ws = m._find_workset("ws-arch")
        assert ws.owner_email == "bob@test.com"


# ---------------------------------------------------------------------------
# 7-12. borrow_element
# ---------------------------------------------------------------------------

class TestBorrowElement:
    def test_borrow_succeeds_for_free_element(self):
        m = _empty_manifest()
        ok, reason = borrow_element(m, "wall-001", "alice@test.com")
        assert ok is True
        assert reason == ""
        assert len(m.borrows) == 1
        assert m.borrows[0].borrowed_by_email == "alice@test.com"

    def test_borrow_blocks_second_user(self):
        m = _empty_manifest()
        borrow_element(m, "wall-001", "alice@test.com")
        ok, reason = borrow_element(m, "wall-001", "bob@test.com")
        assert ok is False
        assert "alice@test.com" in reason
        # Manifest still has only Alice's borrow
        assert len(m.borrows) == 1
        assert m.borrows[0].borrowed_by_email == "alice@test.com"

    def test_release_frees_element(self):
        m = _empty_manifest()
        borrow_element(m, "wall-001", "alice@test.com")
        ok = release_element(m, "wall-001", "alice@test.com")
        assert ok is True
        assert len(m.borrows) == 0

    def test_release_wrong_user_fails(self):
        m = _empty_manifest()
        borrow_element(m, "wall-001", "alice@test.com")
        ok = release_element(m, "wall-001", "bob@test.com")
        assert ok is False
        assert len(m.borrows) == 1

    def test_reborrow_by_same_user_refreshes_expiry(self):
        from kerf_bim.worksharing import _parse_iso
        m = _empty_manifest()
        now = _now()
        borrow_element(m, "wall-001", "alice@test.com", duration_hours=1.0, now_iso=now)
        old_expiry = _parse_iso(m.borrows[0].expires_at_iso)
        # Re-borrow with longer duration
        future_now = _iso(datetime.now(timezone.utc) + timedelta(minutes=30))
        ok, reason = borrow_element(m, "wall-001", "alice@test.com", duration_hours=8.0, now_iso=future_now)
        assert ok is True
        new_expiry = _parse_iso(m.borrows[0].expires_at_iso)
        assert new_expiry > old_expiry
        assert len(m.borrows) == 1  # no duplicate

    def test_expired_borrow_allows_new_borrower(self):
        m = _empty_manifest()
        # Insert an expired borrow
        m.borrows.append(ElementBorrowEntry(
            element_id="wall-001",
            borrowed_by_email="alice@test.com",
            borrowed_at_iso=_past(10),
            expires_at_iso=_past(2),
        ))
        ok, reason = borrow_element(m, "wall-001", "bob@test.com")
        assert ok is True
        assert m.borrows[0].borrowed_by_email == "bob@test.com"

    def test_workset_owner_borrow_blocks_others(self):
        """If workset owner has a workset-level borrow, others are blocked."""
        m = _empty_manifest()
        workset_create(m, "ws-arch", "Architecture", "alice@test.com")
        workset_assign_element(m, "wall-001", "ws-arch")
        # Alice borrows the workset at the workset level
        ws_borrow_id = "workset:ws-arch"
        m.borrows.append(ElementBorrowEntry(
            element_id=ws_borrow_id,
            borrowed_by_email="alice@test.com",
            borrowed_at_iso=_now(),
            expires_at_iso=_future(8),
            workset_id="ws-arch",
        ))
        # Bob tries to borrow wall-001 which is in alice's workset
        ok, reason = borrow_element(m, "wall-001", "bob@test.com")
        assert ok is False
        assert "alice@test.com" in reason


# ---------------------------------------------------------------------------
# 13 & 14. update_local_data
# ---------------------------------------------------------------------------

class TestUpdateLocalData:
    def test_update_stores_payload(self):
        m = _empty_manifest()
        borrow_element(m, "wall-001", "alice@test.com")
        ok = update_local_data(m, "wall-001", "alice@test.com", {"height_mm": 3000})
        assert ok is True
        b = m._find_borrow("wall-001")
        assert b.local_data == {"height_mm": 3000}

    def test_update_fails_for_non_borrower(self):
        m = _empty_manifest()
        borrow_element(m, "wall-001", "alice@test.com")
        ok = update_local_data(m, "wall-001", "bob@test.com", {"height_mm": 3000})
        assert ok is False


# ---------------------------------------------------------------------------
# 15-18. sync_to_central
# ---------------------------------------------------------------------------

class TestSyncToCentral:
    def test_sync_pushes_non_conflicting_edits(self):
        m = _empty_manifest()
        borrow_element(m, "wall-001", "alice@test.com")
        update_local_data(m, "wall-001", "alice@test.com", {"height_mm": 3000})
        result = sync_to_central(m, "alice@test.com")
        assert result.ok is True
        assert "wall-001" in result.synced_elements
        assert len(result.conflicts) == 0
        # Central should now have alice's data
        assert m.central_element_data["wall-001"]["height_mm"] == 3000
        assert m.central_element_data["wall-001"]["_last_editor"] == "alice@test.com"

    def test_sync_releases_borrow_after_push(self):
        m = _empty_manifest()
        borrow_element(m, "wall-001", "alice@test.com")
        update_local_data(m, "wall-001", "alice@test.com", {"height_mm": 3000})
        result = sync_to_central(m, "alice@test.com")
        assert "wall-001" in result.released_borrows
        assert m._find_borrow("wall-001") is None

    def test_sync_detects_conflict(self):
        """Two users borrow the same element; one syncs first; second sync detects conflict."""
        m = _empty_manifest()
        borrow_time = _past(2)  # both borrowed 2h ago

        # Alice borrowed and then synced first
        alice_borrow = ElementBorrowEntry(
            element_id="wall-001",
            borrowed_by_email="alice@test.com",
            borrowed_at_iso=borrow_time,
            expires_at_iso=_future(6),
            local_data={"height_mm": 3000},
        )
        m.borrows.append(alice_borrow)
        # Alice syncs first — pushes to central
        sync_to_central(m, "alice@test.com")
        # Central now has alice's data with _last_editor=alice

        # Bob borrowed the same element at the same time (in parallel)
        bob_borrow = ElementBorrowEntry(
            element_id="wall-001",
            borrowed_by_email="bob@test.com",
            borrowed_at_iso=borrow_time,    # same borrow time as alice
            expires_at_iso=_future(6),
            local_data={"height_mm": 4000},
        )
        m.borrows.append(bob_borrow)
        # Bob syncs — should detect conflict (alice wrote to central after bob borrowed)
        result = sync_to_central(m, "bob@test.com")
        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        assert conflict.element_id == "wall-001"
        assert conflict.user_a_email == "bob@test.com"
        assert conflict.user_b_email == "alice@test.com"

    def test_sync_merges_non_overlapping_elements(self):
        """Two users edit different elements — no conflict."""
        m = _empty_manifest()
        borrow_element(m, "wall-001", "alice@test.com")
        borrow_element(m, "wall-002", "bob@test.com")
        update_local_data(m, "wall-001", "alice@test.com", {"h": 3000})
        update_local_data(m, "wall-002", "bob@test.com", {"h": 4000})
        # Alice syncs
        r1 = sync_to_central(m, "alice@test.com")
        assert r1.ok is True
        assert len(r1.conflicts) == 0
        # Bob syncs
        r2 = sync_to_central(m, "bob@test.com")
        assert r2.ok is True
        assert len(r2.conflicts) == 0
        # Both elements now in central
        assert "wall-001" in m.central_element_data
        assert "wall-002" in m.central_element_data

    def test_sync_pulls_others_central_data(self):
        """After sync, pulled_elements includes elements already in central."""
        m = _empty_manifest()
        # Pre-populate central with someone else's element
        m.central_element_data["slab-001"] = {"thickness_mm": 200, "_last_editor": "bob@test.com", "_edited_at_iso": _past(1)}
        borrow_element(m, "wall-001", "alice@test.com")
        update_local_data(m, "wall-001", "alice@test.com", {"height_mm": 3000})
        result = sync_to_central(m, "alice@test.com")
        assert "slab-001" in result.pulled_elements


# ---------------------------------------------------------------------------
# 19. worksharing_status
# ---------------------------------------------------------------------------

class TestWorksharingStatus:
    def test_status_returns_correct_counts(self):
        m = _empty_manifest("my-project")
        workset_create(m, "ws-arch", "Architecture")
        workset_create(m, "ws-str", "Structure")
        borrow_element(m, "wall-001", "alice@test.com")
        borrow_element(m, "wall-002", "bob@test.com")
        m.central_element_data["elem-x"] = {"_last_editor": "alice@test.com", "_edited_at_iso": _now()}

        status = worksharing_status(m)
        assert status["project_id"] == "my-project"
        assert status["workset_count"] == 2
        assert status["active_borrow_count"] == 2
        assert status["central_element_count"] == 1
        assert "alice@test.com" in status["borrows_by_user"]
        assert "wall-001" in status["borrows_by_user"]["alice@test.com"]


# ---------------------------------------------------------------------------
# 20. JSON round-trip
# ---------------------------------------------------------------------------

class TestJsonRoundTrip:
    def test_manifest_round_trips(self):
        m = _empty_manifest("proj-rt")
        workset_create(m, "ws-arch", "Architecture", "alice@test.com")
        workset_assign_element(m, "wall-001", "ws-arch")
        borrow_element(m, "wall-001", "alice@test.com")
        update_local_data(m, "wall-001", "alice@test.com", {"color": "red"})
        m.central_element_data["slab-1"] = {"thickness": 200}

        json_str = m.to_json()
        restored = WorksharingManifest.from_json(json_str)

        assert restored.project_id == "proj-rt"
        assert len(restored.worksets) == 1
        assert restored.worksets[0].name == "Architecture"
        assert len(restored.borrows) == 1
        assert restored.borrows[0].local_data == {"color": "red"}
        assert "slab-1" in restored.central_element_data

    def test_empty_manifest_round_trips(self):
        m = WorksharingManifest()
        restored = WorksharingManifest.from_json(m.to_json())
        assert restored.worksets == []
        assert restored.borrows == []
