"""
Tests for BIMcloud-lite element-level locking (kerf_bim.element_lock).

Oracles
-------
- User A locks element → succeeds
- User B requests same element → fails with conflict_user=A
- After expiry, User B can lock same element
- Only locker can release (User B release of User A's lock → False)
- Only locker can extend (User B extend of User A's lock → False)
- cleanup_expired_locks removes only expired entries, returns correct count
- Multi-user concurrent serialises: two users lock different elements → both succeed
- JSON round-trip preserves all lock fields
- Re-lock by same user refreshes expiry (idempotent)
- list_user_locks returns only that user's active locks
- list_all_active_locks excludes expired locks
- is_locked returns (False, None) for an expired lock
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest

from kerf_bim.element_lock import (
    LockRequest,
    ElementLock,
    LockManifest,
    LockResult,
    request_lock,
    release_lock,
    extend_lock,
    cleanup_expired_locks,
    is_locked,
    list_user_locks,
    list_all_active_locks,
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


def _manifest(*locks: ElementLock) -> LockManifest:
    return LockManifest(locks=list(locks))


def _make_lock(
    element_id: str = "wall-001",
    user: str = "alice@test.com",
    hours: float = 8.0,
    comment: str = "",
) -> ElementLock:
    now = _now()
    return ElementLock(
        element_id=element_id,
        locked_by_email=user,
        locked_at_iso=now,
        expires_at_iso=_future(hours),
        lock_comment=comment,
    )


# ---------------------------------------------------------------------------
# 1. Basic lock acquisition
# ---------------------------------------------------------------------------

class TestRequestLock:
    def test_user_a_locks_succeeds(self):
        manifest = LockManifest()
        req = LockRequest(element_id="wall-001", user_email="alice@test.com")
        result = request_lock(manifest, req)
        assert result.success is True
        assert result.lock is not None
        assert result.lock.element_id == "wall-001"
        assert result.lock.locked_by_email == "alice@test.com"
        assert result.conflict_user is None

    def test_lock_added_to_manifest(self):
        manifest = LockManifest()
        request_lock(manifest, LockRequest("wall-001", "alice@test.com"))
        assert len(manifest.locks) == 1
        assert manifest.locks[0].element_id == "wall-001"

    def test_lock_comment_preserved(self):
        manifest = LockManifest()
        result = request_lock(manifest, LockRequest("wall-001", "alice@test.com", comment="editing facade"))
        assert result.lock.lock_comment == "editing facade"

    def test_custom_duration_reflected_in_expires(self):
        manifest = LockManifest()
        now = _now()
        result = request_lock(
            manifest,
            LockRequest("wall-002", "alice@test.com", lock_duration_hours=2.0),
            now_iso=now,
        )
        assert result.success is True
        # expires_at should be ~2 hours after now
        from kerf_bim.element_lock import _parse
        delta = _parse(result.lock.expires_at_iso) - _parse(now)
        assert abs(delta.total_seconds() - 7200) < 1


# ---------------------------------------------------------------------------
# 2. Lock conflict — User B blocked while User A holds live lock
# ---------------------------------------------------------------------------

class TestLockConflict:
    def test_user_b_request_fails_while_a_locked(self):
        manifest = LockManifest()
        request_lock(manifest, LockRequest("wall-001", "alice@test.com"))
        result = request_lock(manifest, LockRequest("wall-001", "bob@test.com"))
        assert result.success is False
        assert result.conflict_user == "alice@test.com"
        assert "alice@test.com" in result.reason

    def test_manifest_unchanged_on_conflict(self):
        manifest = LockManifest()
        request_lock(manifest, LockRequest("wall-001", "alice@test.com"))
        request_lock(manifest, LockRequest("wall-001", "bob@test.com"))
        # Still exactly one lock
        assert len(manifest.locks) == 1
        assert manifest.locks[0].locked_by_email == "alice@test.com"


# ---------------------------------------------------------------------------
# 3. After expiry, User B can lock
# ---------------------------------------------------------------------------

class TestExpiredLock:
    def test_user_b_can_lock_after_expiry(self):
        manifest = LockManifest()
        # Insert an already-expired lock for Alice
        manifest.locks.append(ElementLock(
            element_id="wall-001",
            locked_by_email="alice@test.com",
            locked_at_iso=_past(10),
            expires_at_iso=_past(2),   # expired 2 hours ago
            lock_comment="",
        ))
        result = request_lock(manifest, LockRequest("wall-001", "bob@test.com"))
        assert result.success is True
        assert result.lock.locked_by_email == "bob@test.com"

    def test_expired_lock_evicted_on_new_request(self):
        manifest = LockManifest()
        manifest.locks.append(ElementLock(
            element_id="wall-001",
            locked_by_email="alice@test.com",
            locked_at_iso=_past(10),
            expires_at_iso=_past(1),
            lock_comment="",
        ))
        request_lock(manifest, LockRequest("wall-001", "bob@test.com"))
        # Should now contain only Bob's lock
        assert len(manifest.locks) == 1
        assert manifest.locks[0].locked_by_email == "bob@test.com"


# ---------------------------------------------------------------------------
# 4. Only locker can release
# ---------------------------------------------------------------------------

class TestReleaseLock:
    def test_locker_can_release(self):
        manifest = LockManifest()
        request_lock(manifest, LockRequest("wall-001", "alice@test.com"))
        ok = release_lock(manifest, "wall-001", "alice@test.com")
        assert ok is True
        assert len(manifest.locks) == 0

    def test_other_user_cannot_release(self):
        manifest = LockManifest()
        request_lock(manifest, LockRequest("wall-001", "alice@test.com"))
        ok = release_lock(manifest, "wall-001", "bob@test.com")
        assert ok is False
        assert len(manifest.locks) == 1  # lock still there

    def test_release_nonexistent_lock_returns_false(self):
        manifest = LockManifest()
        ok = release_lock(manifest, "nonexistent-element", "alice@test.com")
        assert ok is False


# ---------------------------------------------------------------------------
# 5. Cleanup removes expired, leaves active
# ---------------------------------------------------------------------------

class TestCleanupExpiredLocks:
    def test_cleanup_removes_expired_returns_count(self):
        manifest = LockManifest()
        manifest.locks.append(ElementLock("wall-exp1", "alice@test.com", _past(5), _past(1), ""))
        manifest.locks.append(ElementLock("wall-exp2", "bob@test.com", _past(3), _past(0.5), ""))
        manifest.locks.append(ElementLock("wall-active", "carol@test.com", _past(1), _future(7), ""))

        removed = cleanup_expired_locks(manifest)
        assert removed == 2
        assert len(manifest.locks) == 1
        assert manifest.locks[0].element_id == "wall-active"

    def test_cleanup_empty_manifest_returns_zero(self):
        assert cleanup_expired_locks(LockManifest()) == 0

    def test_cleanup_all_active_returns_zero(self):
        manifest = _manifest(
            ElementLock("w1", "a@t.com", _past(1), _future(7), ""),
            ElementLock("w2", "b@t.com", _past(1), _future(5), ""),
        )
        assert cleanup_expired_locks(manifest) == 0


# ---------------------------------------------------------------------------
# 6. Multi-user concurrent — different elements
# ---------------------------------------------------------------------------

class TestMultiUserConcurrent:
    def test_two_users_lock_different_elements(self):
        manifest = LockManifest()
        r1 = request_lock(manifest, LockRequest("wall-001", "alice@test.com"))
        r2 = request_lock(manifest, LockRequest("wall-002", "bob@test.com"))
        assert r1.success is True
        assert r2.success is True
        assert len(manifest.locks) == 2

    def test_three_users_serialise_correctly(self):
        manifest = LockManifest()
        request_lock(manifest, LockRequest("elem-A", "u1@t.com"))
        request_lock(manifest, LockRequest("elem-B", "u2@t.com"))
        # u3 tries both → only elem-C succeeds; elem-A and elem-B conflict
        r_a = request_lock(manifest, LockRequest("elem-A", "u3@t.com"))
        r_c = request_lock(manifest, LockRequest("elem-C", "u3@t.com"))
        assert r_a.success is False
        assert r_c.success is True


# ---------------------------------------------------------------------------
# 7. JSON round-trip
# ---------------------------------------------------------------------------

class TestJsonRoundTrip:
    def test_round_trip_preserves_all_fields(self):
        manifest = LockManifest()
        request_lock(manifest, LockRequest("wall-001", "alice@test.com", 8.0, "facade work"))
        request_lock(manifest, LockRequest("wall-002", "bob@test.com", 4.0))

        json_str = manifest.to_json()
        restored = LockManifest.from_json(json_str)

        assert len(restored.locks) == 2
        lock = next(l for l in restored.locks if l.element_id == "wall-001")
        assert lock.locked_by_email == "alice@test.com"
        assert lock.lock_comment == "facade work"

    def test_empty_manifest_round_trips(self):
        restored = LockManifest.from_json(LockManifest().to_json())
        assert restored.locks == []

    def test_json_is_valid(self):
        manifest = LockManifest()
        request_lock(manifest, LockRequest("el-1", "x@y.com"))
        data = json.loads(manifest.to_json())
        assert "locks" in data
        assert isinstance(data["locks"], list)


# ---------------------------------------------------------------------------
# 8. Idempotent re-lock by same user
# ---------------------------------------------------------------------------

class TestRelock:
    def test_same_user_relock_refreshes_expiry(self):
        manifest = LockManifest()
        from kerf_bim.element_lock import _parse
        t0 = _now()
        request_lock(manifest, LockRequest("wall-001", "alice@test.com", 1.0), now_iso=t0)
        old_expiry = _parse(manifest.locks[0].expires_at_iso)

        # Re-lock with a longer duration 30 min later
        t1 = _iso(datetime.now(timezone.utc) + timedelta(minutes=30))
        result = request_lock(manifest, LockRequest("wall-001", "alice@test.com", 8.0), now_iso=t1)

        assert result.success is True
        assert len(manifest.locks) == 1  # No duplicate
        new_expiry = _parse(manifest.locks[0].expires_at_iso)
        assert new_expiry > old_expiry


# ---------------------------------------------------------------------------
# 9. is_locked
# ---------------------------------------------------------------------------

class TestIsLocked:
    def test_active_lock_returns_true_and_lock(self):
        manifest = LockManifest()
        request_lock(manifest, LockRequest("wall-001", "alice@test.com"))
        locked, lock = is_locked(manifest, "wall-001")
        assert locked is True
        assert lock is not None
        assert lock.locked_by_email == "alice@test.com"

    def test_no_lock_returns_false_none(self):
        locked, lock = is_locked(LockManifest(), "wall-001")
        assert locked is False
        assert lock is None

    def test_expired_lock_returns_false(self):
        manifest = _manifest(
            ElementLock("wall-001", "alice@test.com", _past(5), _past(1), ""),
        )
        locked, lock = is_locked(manifest, "wall-001")
        assert locked is False
        assert lock is None


# ---------------------------------------------------------------------------
# 10. list_user_locks
# ---------------------------------------------------------------------------

class TestListUserLocks:
    def test_returns_only_that_users_locks(self):
        manifest = LockManifest()
        request_lock(manifest, LockRequest("wall-001", "alice@test.com"))
        request_lock(manifest, LockRequest("wall-002", "bob@test.com"))
        request_lock(manifest, LockRequest("wall-003", "alice@test.com"))

        alice_locks = list_user_locks(manifest, "alice@test.com")
        assert len(alice_locks) == 2
        assert all(l.locked_by_email == "alice@test.com" for l in alice_locks)

    def test_excludes_expired_locks(self):
        manifest = _manifest(
            ElementLock("w1", "alice@test.com", _past(10), _past(1), ""),  # expired
            ElementLock("w2", "alice@test.com", _past(1), _future(7), ""),  # active
        )
        locks = list_user_locks(manifest, "alice@test.com")
        assert len(locks) == 1
        assert locks[0].element_id == "w2"


# ---------------------------------------------------------------------------
# 11. list_all_active_locks
# ---------------------------------------------------------------------------

class TestListAllActiveLocks:
    def test_excludes_expired(self):
        manifest = _manifest(
            ElementLock("exp", "a@t.com", _past(5), _past(1), ""),
            ElementLock("active", "b@t.com", _past(1), _future(7), ""),
        )
        active = list_all_active_locks(manifest)
        assert len(active) == 1
        assert active[0].element_id == "active"

    def test_empty_manifest_returns_empty(self):
        assert list_all_active_locks(LockManifest()) == []


# ---------------------------------------------------------------------------
# 12. extend_lock
# ---------------------------------------------------------------------------

class TestExtendLock:
    def test_owner_can_extend(self):
        from kerf_bim.element_lock import _parse
        manifest = LockManifest()
        request_lock(manifest, LockRequest("wall-001", "alice@test.com", 2.0))
        before = _parse(manifest.locks[0].expires_at_iso)
        ok = extend_lock(manifest, "wall-001", "alice@test.com", 4.0)
        after = _parse(manifest.locks[0].expires_at_iso)
        assert ok is True
        delta = (after - before).total_seconds()
        assert abs(delta - 4 * 3600) < 2

    def test_non_owner_cannot_extend(self):
        manifest = LockManifest()
        request_lock(manifest, LockRequest("wall-001", "alice@test.com"))
        ok = extend_lock(manifest, "wall-001", "bob@test.com", 4.0)
        assert ok is False

    def test_extend_missing_element_returns_false(self):
        assert extend_lock(LockManifest(), "no-such-element", "alice@test.com", 4.0) is False
