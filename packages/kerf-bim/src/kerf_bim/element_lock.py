"""
element_lock.py — BIMcloud-lite element-level locking for multi-user BIM teamwork.

ArchiCAD's killer team feature: any user can reserve an element for exclusive editing.
A lock is time-bounded (default 8 h) and only the locker can release or extend it.
Expired locks are cleaned on the next request or an explicit cleanup call.

All state is captured in a ``LockManifest`` that is safe to serialise to JSON and
store alongside the project (e.g. in cloud/git or a DB JSONB column).

Public API
----------
request_lock     — acquire exclusive edit rights on an element
release_lock     — give up a lock (only the locker can)
extend_lock      — push the expiry forward (only the locker can)
cleanup_expired_locks — remove all past-expiry locks; returns count removed
is_locked        — query lock state of one element
list_user_locks  — all active locks held by a given user
list_all_active_locks — all currently-active locks across all users
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional


# ---------------------------------------------------------------------------
# ISO-8601 helpers (timezone-aware UTC, no external deps)
# ---------------------------------------------------------------------------

_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime(_FMT)


def _parse(iso: str) -> datetime:
    """Parse an ISO-8601 UTC string back to an aware datetime."""
    # Accept both trailing-Z and +00:00 forms
    iso = iso.rstrip("Z")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        # Fallback for "%Y-%m-%dT%H:%M:%S.%f" without offset
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%f")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _add_hours(iso: str, hours: float) -> str:
    dt = _parse(iso) + timedelta(hours=hours)
    return dt.strftime(_FMT)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LockRequest:
    element_id: str
    user_email: str
    lock_duration_hours: float = 8.0
    comment: str = ""


@dataclass
class ElementLock:
    element_id: str
    locked_by_email: str
    locked_at_iso: str
    expires_at_iso: str
    lock_comment: str

    def is_expired(self, now_iso: Optional[str] = None) -> bool:
        now = _parse(now_iso or _now_iso())
        return now >= _parse(self.expires_at_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ElementLock":
        return cls(
            element_id=d["element_id"],
            locked_by_email=d["locked_by_email"],
            locked_at_iso=d["locked_at_iso"],
            expires_at_iso=d["expires_at_iso"],
            lock_comment=d.get("lock_comment", ""),
        )


@dataclass
class LockManifest:
    locks: list[ElementLock] = field(default_factory=list)

    # ── JSON round-trip ───────────────────────────────────────────────────

    def to_json(self) -> str:
        return json.dumps({"locks": [lock.to_dict() for lock in self.locks]}, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "LockManifest":
        data = json.loads(text)
        return cls(locks=[ElementLock.from_dict(d) for d in data.get("locks", [])])

    # ── Internal helpers ──────────────────────────────────────────────────

    def _find(self, element_id: str) -> Optional[ElementLock]:
        for lock in self.locks:
            if lock.element_id == element_id:
                return lock
        return None

    def _remove(self, element_id: str) -> bool:
        before = len(self.locks)
        self.locks = [lock for lock in self.locks if lock.element_id != element_id]
        return len(self.locks) < before


@dataclass
class LockResult:
    success: bool
    lock: Optional[ElementLock]
    conflict_user: Optional[str]
    reason: str


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

def request_lock(
    manifest: LockManifest,
    request: LockRequest,
    now_iso: Optional[str] = None,
) -> LockResult:
    """Acquire an exclusive lock on *element_id* for *user_email*.

    Succeeds immediately if the element is unlocked **or** the existing lock
    has expired.  Fails if another user holds a live lock.

    A user re-requesting their own active lock refreshes the expiry (idempotent
    re-lock is safe in a reconnect scenario).
    """
    now = now_iso or _now_iso()

    existing = manifest._find(request.element_id)

    if existing is not None:
        if not existing.is_expired(now):
            # Active lock held by someone else → conflict
            if existing.locked_by_email != request.user_email:
                return LockResult(
                    success=False,
                    lock=None,
                    conflict_user=existing.locked_by_email,
                    reason=(
                        f"Element '{request.element_id}' is locked by "
                        f"{existing.locked_by_email} until {existing.expires_at_iso}."
                    ),
                )
            # Same user re-locking → refresh expiry
            manifest._remove(request.element_id)
        else:
            # Expired — silently evict
            manifest._remove(request.element_id)

    new_lock = ElementLock(
        element_id=request.element_id,
        locked_by_email=request.user_email,
        locked_at_iso=now,
        expires_at_iso=_add_hours(now, request.lock_duration_hours),
        lock_comment=request.comment,
    )
    manifest.locks.append(new_lock)
    return LockResult(success=True, lock=new_lock, conflict_user=None, reason="")


def release_lock(
    manifest: LockManifest,
    element_id: str,
    user_email: str,
) -> bool:
    """Release a lock.  Returns ``True`` on success, ``False`` if not found or
    the caller does not own the lock."""
    existing = manifest._find(element_id)
    if existing is None:
        return False
    if existing.locked_by_email != user_email:
        return False
    manifest._remove(element_id)
    return True


def extend_lock(
    manifest: LockManifest,
    element_id: str,
    user_email: str,
    additional_hours: float,
) -> bool:
    """Extend the expiry of an active lock by *additional_hours*.

    Returns ``False`` if the lock does not exist, is already expired, or the
    caller is not the locker.
    """
    existing = manifest._find(element_id)
    if existing is None:
        return False
    if existing.locked_by_email != user_email:
        return False
    if existing.is_expired():
        return False
    existing.expires_at_iso = _add_hours(existing.expires_at_iso, additional_hours)
    return True


def cleanup_expired_locks(
    manifest: LockManifest,
    now_iso: Optional[str] = None,
) -> int:
    """Remove all expired locks.  Returns the count of removed entries."""
    now = now_iso or _now_iso()
    before = len(manifest.locks)
    manifest.locks = [lock for lock in manifest.locks if not lock.is_expired(now)]
    return before - len(manifest.locks)


def is_locked(
    manifest: LockManifest,
    element_id: str,
    now_iso: Optional[str] = None,
) -> tuple[bool, Optional[ElementLock]]:
    """Return ``(True, lock)`` if the element has an active (non-expired) lock,
    otherwise ``(False, None)``."""
    existing = manifest._find(element_id)
    if existing is None:
        return False, None
    if existing.is_expired(now_iso or _now_iso()):
        return False, None
    return True, existing


def list_user_locks(
    manifest: LockManifest,
    user_email: str,
) -> list[ElementLock]:
    """Return all active (non-expired) locks held by *user_email*."""
    now = _now_iso()
    return [
        lock for lock in manifest.locks
        if lock.locked_by_email == user_email and not lock.is_expired(now)
    ]


def list_all_active_locks(
    manifest: LockManifest,
    now_iso: Optional[str] = None,
) -> list[ElementLock]:
    """Return every active (non-expired) lock across all users."""
    now = now_iso or _now_iso()
    return [lock for lock in manifest.locks if not lock.is_expired(now)]
