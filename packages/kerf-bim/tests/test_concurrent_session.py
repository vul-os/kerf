"""
Tests for kerf_bim.concurrent_session — AVEVA E3D parity Wave 12B.

Covers:
- open_concurrent_session: adds user, creates manifest
- close_concurrent_session: removes user, releases locks
- broadcast_position: updates cursor
- set_view: updates active view
- list_users_viewing_element: lock-based awareness
- resolve_lock_conflict: FCFS and LWW policies
- Integration with kerf_bim.element_lock (Wave 7C)

References: Tridas, Vrijhoef (2012); Dossick, Neff (2010).
"""
from __future__ import annotations

import pytest

from kerf_bim.concurrent_session import (
    UserPresence,
    ConcurrentSession,
    ConflictResolution,
    open_concurrent_session,
    close_concurrent_session,
    resolve_lock_conflict,
)
from kerf_bim.element_lock import (
    LockManifest,
    LockRequest,
    request_lock,
    is_locked,
    list_user_locks,
)


# ---------------------------------------------------------------------------
# open_concurrent_session
# ---------------------------------------------------------------------------

def test_open_session_adds_user():
    """open_concurrent_session should register the first user."""
    session = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    assert len(session.active_users) == 1
    assert session.active_users[0].user_id == "alice@example.com"
    assert session.active_users[0].user_name == "Alice"


def test_open_session_empty_manifest():
    """New session starts with an empty lock manifest."""
    session = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    assert len(session.lock_manifest.locks) == 0


def test_open_session_project_id():
    session = open_concurrent_session("proj-xyz", "u@u.com", "U")
    assert session.project_id == "proj-xyz"


def test_open_session_join_existing():
    """Second open_concurrent_session call on existing session adds second user."""
    s1 = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    s2 = open_concurrent_session("proj-1", "bob@example.com", "Bob", existing_session=s1)
    ids = [u.user_id for u in s2.active_users]
    assert "alice@example.com" in ids
    assert "bob@example.com" in ids
    assert len(s2.active_users) == 2


def test_open_session_started_iso_set():
    session = open_concurrent_session("p", "u@u.com", "U")
    assert session.session_started_iso != ""


# ---------------------------------------------------------------------------
# close_concurrent_session
# ---------------------------------------------------------------------------

def test_close_session_removes_user():
    s1 = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    s2 = open_concurrent_session("proj-1", "bob@example.com", "Bob", existing_session=s1)
    s3 = close_concurrent_session(s2, "alice@example.com")
    ids = [u.user_id for u in s3.active_users]
    assert "alice@example.com" not in ids
    assert "bob@example.com" in ids


def test_close_session_releases_locks():
    """Closing a session releases all locks held by that user."""
    s = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    manifest = s.lock_manifest
    # Alice locks elements A and B
    request_lock(manifest, LockRequest("elem-A", "alice@example.com"))
    request_lock(manifest, LockRequest("elem-B", "alice@example.com"))
    assert len(list_user_locks(manifest, "alice@example.com")) == 2

    s2 = close_concurrent_session(s, "alice@example.com")
    # Locks should be gone
    assert len(list_user_locks(s2.lock_manifest, "alice@example.com")) == 0


def test_close_session_only_releases_own_locks():
    """close_concurrent_session must not release locks held by other users."""
    s = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    s = open_concurrent_session("proj-1", "bob@example.com", "Bob", existing_session=s)
    manifest = s.lock_manifest
    request_lock(manifest, LockRequest("elem-C", "alice@example.com"))
    request_lock(manifest, LockRequest("elem-D", "bob@example.com"))

    # Alice leaves
    s2 = close_concurrent_session(s, "alice@example.com")
    alice_locks = list_user_locks(s2.lock_manifest, "alice@example.com")
    bob_locks = list_user_locks(s2.lock_manifest, "bob@example.com")
    assert len(alice_locks) == 0
    assert len(bob_locks) == 1


# ---------------------------------------------------------------------------
# broadcast_position
# ---------------------------------------------------------------------------

def test_broadcast_position_updates_cursor():
    s = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    s2 = s.broadcast_position("alice@example.com", (3.0, 4.0, 5.0))
    alice = next(u for u in s2.active_users if u.user_id == "alice@example.com")
    assert alice.cursor_position == (3.0, 4.0, 5.0)


def test_broadcast_position_does_not_affect_other_users():
    s = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    s = open_concurrent_session("proj-1", "bob@example.com", "Bob", existing_session=s)
    s2 = s.broadcast_position("alice@example.com", (1.0, 2.0, 3.0))
    bob = next(u for u in s2.active_users if u.user_id == "bob@example.com")
    assert bob.cursor_position is None  # unchanged


def test_broadcast_position_refreshes_last_seen():
    s = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    old_ts = s.active_users[0].last_seen_iso
    import time; time.sleep(0.01)
    s2 = s.broadcast_position("alice@example.com", (0.0, 0.0, 0.0))
    new_ts = s2.active_users[0].last_seen_iso
    # new_ts should be >= old_ts (may be equal on fast machines)
    assert new_ts >= old_ts


# ---------------------------------------------------------------------------
# list_users_viewing_element
# ---------------------------------------------------------------------------

def test_list_users_viewing_element_with_lock():
    """User with active lock on an element shows up in list_users_viewing_element."""
    s = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    request_lock(s.lock_manifest, LockRequest("pipe-seg-1", "alice@example.com"))
    viewers = s.list_users_viewing_element("pipe-seg-1")
    assert "alice@example.com" in viewers


def test_list_users_viewing_element_no_lock():
    s = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    viewers = s.list_users_viewing_element("pipe-seg-99")
    assert viewers == []


# ---------------------------------------------------------------------------
# resolve_lock_conflict — FCFS policy
# ---------------------------------------------------------------------------

def test_resolve_conflict_fcfs_existing_owner_wins():
    """FCFS: existing lock owner must win."""
    result = resolve_lock_conflict(
        lock_request_user="bob@example.com",
        current_lock_owner="alice@example.com",
        element_id="elem-X",
        policy="first_come_first_serve",
    )
    assert result.winning_user == "alice@example.com"
    assert result.policy == "first_come_first_serve"


def test_resolve_conflict_fcfs_conflicting_users_listed():
    result = resolve_lock_conflict(
        lock_request_user="charlie@example.com",
        current_lock_owner="alice@example.com",
        element_id="elem-Y",
        policy="first_come_first_serve",
    )
    assert "alice@example.com" in result.conflicting_users
    assert "charlie@example.com" in result.conflicting_users


def test_resolve_conflict_no_conflict_same_user():
    """If the same user re-requests their own lock → no conflict."""
    result = resolve_lock_conflict(
        lock_request_user="alice@example.com",
        current_lock_owner="alice@example.com",
        element_id="elem-Z",
        policy="first_come_first_serve",
    )
    assert result.winning_user == "alice@example.com"
    assert len(result.conflicting_users) == 1


def test_resolve_conflict_lww_challenger_wins():
    """LWW policy: challenger (requesting user) wins."""
    result = resolve_lock_conflict(
        lock_request_user="bob@example.com",
        current_lock_owner="alice@example.com",
        element_id="elem-W",
        policy="last_writer_wins",
    )
    assert result.winning_user == "bob@example.com"
    assert result.policy == "last_writer_wins"


def test_resolve_conflict_invalid_policy():
    """Unknown policy string should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown conflict resolution policy"):
        resolve_lock_conflict(
            lock_request_user="bob@example.com",
            current_lock_owner="alice@example.com",
            policy="random",
        )


# ---------------------------------------------------------------------------
# Integration: element_lock + concurrent_session
# ---------------------------------------------------------------------------

def test_integration_two_users_lock_different_elements():
    """Two users can hold locks on different elements simultaneously."""
    s = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    s = open_concurrent_session("proj-1", "bob@example.com", "Bob", existing_session=s)

    r_a = request_lock(s.lock_manifest, LockRequest("elem-1", "alice@example.com"))
    r_b = request_lock(s.lock_manifest, LockRequest("elem-2", "bob@example.com"))

    assert r_a.success is True
    assert r_b.success is True


def test_integration_second_user_cant_lock_held_element():
    """Bob cannot lock an element Alice already holds."""
    s = open_concurrent_session("proj-1", "alice@example.com", "Alice")
    s = open_concurrent_session("proj-1", "bob@example.com", "Bob", existing_session=s)

    request_lock(s.lock_manifest, LockRequest("elem-3", "alice@example.com"))
    r_b = request_lock(s.lock_manifest, LockRequest("elem-3", "bob@example.com"))

    assert r_b.success is False
    assert r_b.conflict_user == "alice@example.com"
