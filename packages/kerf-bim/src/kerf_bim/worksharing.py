"""
worksharing.py — BIM worksharing: central model, worksets, element borrow/release,
sync-to-central, and conflict detection.

Modelled after Revit's actual worksharing workflow (not live CRDT co-editing):
  - A CENTRAL model is the authoritative store.
  - Users work on LOCAL copies.
  - Elements belong to WORKSETS (named groups with an owner/editable-by policy).
  - A user BORROWs (checks out) specific elements to gain exclusive edit rights.
  - SYNC-TO-CENTRAL pushes the user's borrowed-element edits back to central and
    pulls other users' committed changes (non-conflicting elements are merged; a
    conflict is raised when two users edited the same element).

This is the honest model: Revit Worksharing is also a checkout/borrow/sync
workflow, not live real-time co-editing.

Public API
----------
Workset                 — named group of elements with an owner
WorksharingManifest     — central-model state: worksets + element borrows + central data
ElementBorrowEntry      — one user's borrow record for one element
SyncResult              — outcome of a sync-to-central operation
ConflictRecord          — details of a single edit conflict detected during sync

workset_create          — add a new workset
workset_assign_element  — move element into a workset
workset_set_owner       — set the workset owner (who has blanket edit rights)

borrow_element          — check out an element for exclusive editing
release_element         — release a borrowed element (no edits committed)
sync_to_central         — push local edits + pull others' changes; detect conflicts

worksharing_status      — summary of current borrow state for a manifest
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime(_FMT)


def _parse_iso(iso: str) -> datetime:
    iso = iso.rstrip("Z")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%f")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _add_hours(iso: str, hours: float) -> str:
    dt = _parse_iso(iso) + timedelta(hours=hours)
    return dt.strftime(_FMT)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Workset:
    """A named group of BIM elements that can be collectively owned.

    Mirrors Revit's Workset concept: project elements belong to worksets;
    a workset has an owner who has blanket borrow rights over all its elements.
    Other users can still borrow individual elements from a workset they don't own.

    kind: 'user' | 'standard' | 'view' | 'family'
    """
    workset_id: str
    name: str
    owner_email: str = ""
    kind: str = "user"
    element_ids: list[str] = field(default_factory=list)
    is_editable_by_owner: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "workset_id": self.workset_id,
            "name": self.name,
            "owner_email": self.owner_email,
            "kind": self.kind,
            "element_ids": list(self.element_ids),
            "is_editable_by_owner": self.is_editable_by_owner,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Workset":
        return cls(
            workset_id=d["workset_id"],
            name=d["name"],
            owner_email=d.get("owner_email", ""),
            kind=d.get("kind", "user"),
            element_ids=list(d.get("element_ids", [])),
            is_editable_by_owner=d.get("is_editable_by_owner", True),
        )


@dataclass
class ElementBorrowEntry:
    """Record that one user has borrowed (checked out) one element.

    local_data: the user's in-progress edit payload (arbitrary dict).
                Empty dict = element borrowed but not yet edited.
    """
    element_id: str
    borrowed_by_email: str
    borrowed_at_iso: str
    expires_at_iso: str
    workset_id: str = ""
    local_data: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now_iso: Optional[str] = None) -> bool:
        now = _parse_iso(now_iso or _now_iso())
        return now >= _parse_iso(self.expires_at_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "borrowed_by_email": self.borrowed_by_email,
            "borrowed_at_iso": self.borrowed_at_iso,
            "expires_at_iso": self.expires_at_iso,
            "workset_id": self.workset_id,
            "local_data": self.local_data,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ElementBorrowEntry":
        return cls(
            element_id=d["element_id"],
            borrowed_by_email=d["borrowed_by_email"],
            borrowed_at_iso=d["borrowed_at_iso"],
            expires_at_iso=d["expires_at_iso"],
            workset_id=d.get("workset_id", ""),
            local_data=d.get("local_data", {}),
        )


@dataclass
class ConflictRecord:
    """Details of a single element-level edit conflict detected during sync."""
    element_id: str
    user_a_email: str
    user_b_email: str
    central_data: dict[str, Any]
    user_a_data: dict[str, Any]
    user_b_data: dict[str, Any]
    detected_at_iso: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "user_a_email": self.user_a_email,
            "user_b_email": self.user_b_email,
            "central_data": self.central_data,
            "user_a_data": self.user_a_data,
            "user_b_data": self.user_b_data,
            "detected_at_iso": self.detected_at_iso,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConflictRecord":
        return cls(
            element_id=d["element_id"],
            user_a_email=d["user_a_email"],
            user_b_email=d["user_b_email"],
            central_data=d.get("central_data", {}),
            user_a_data=d.get("user_a_data", {}),
            user_b_data=d.get("user_b_data", {}),
            detected_at_iso=d.get("detected_at_iso", _now_iso()),
        )


@dataclass
class SyncResult:
    """Result of a sync-to-central operation."""
    ok: bool
    synced_elements: list[str]       # element_ids whose edits were pushed to central
    pulled_elements: list[str]       # element_ids whose central data was pulled
    conflicts: list[ConflictRecord]  # conflicts detected (element edited by 2 users)
    released_borrows: list[str]      # element_ids released after successful sync
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "synced_elements": self.synced_elements,
            "pulled_elements": self.pulled_elements,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "released_borrows": self.released_borrows,
            "message": self.message,
        }


@dataclass
class WorksharingManifest:
    """Central-model worksharing state.

    Holds:
    - worksets: named element groups
    - borrows: active element borrow records across all users
    - central_element_data: the committed (central) state for each element
      (keyed by element_id; value is arbitrary dict representing element props)
    """
    project_id: str = ""
    worksets: list[Workset] = field(default_factory=list)
    borrows: list[ElementBorrowEntry] = field(default_factory=list)
    central_element_data: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_sync_iso: str = ""

    # ── JSON round-trip ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "worksets": [ws.to_dict() for ws in self.worksets],
            "borrows": [b.to_dict() for b in self.borrows],
            "central_element_data": self.central_element_data,
            "last_sync_iso": self.last_sync_iso,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorksharingManifest":
        return cls(
            project_id=d.get("project_id", ""),
            worksets=[Workset.from_dict(ws) for ws in d.get("worksets", [])],
            borrows=[ElementBorrowEntry.from_dict(b) for b in d.get("borrows", [])],
            central_element_data=d.get("central_element_data", {}),
            last_sync_iso=d.get("last_sync_iso", ""),
        )

    @classmethod
    def from_json(cls, text: str) -> "WorksharingManifest":
        return cls.from_dict(json.loads(text))

    # ── Internal helpers ────────────────────────────────────────────────────

    def _find_borrow(self, element_id: str) -> Optional[ElementBorrowEntry]:
        for b in self.borrows:
            if b.element_id == element_id:
                return b
        return None

    def _find_workset(self, workset_id: str) -> Optional[Workset]:
        for ws in self.worksets:
            if ws.workset_id == workset_id:
                return ws
        return None

    def _active_borrows(self, now_iso: Optional[str] = None) -> list[ElementBorrowEntry]:
        now = now_iso or _now_iso()
        return [b for b in self.borrows if not b.is_expired(now)]

    def _workset_for_element(self, element_id: str) -> Optional[Workset]:
        for ws in self.worksets:
            if element_id in ws.element_ids:
                return ws
        return None


# ---------------------------------------------------------------------------
# Workset management
# ---------------------------------------------------------------------------

def workset_create(
    manifest: WorksharingManifest,
    workset_id: str,
    name: str,
    owner_email: str = "",
    kind: str = "user",
) -> Workset:
    """Add a new workset to the manifest.

    Returns the new Workset; raises ValueError if workset_id already exists.
    """
    if not workset_id or not name:
        raise ValueError("workset_id and name are required")
    existing = manifest._find_workset(workset_id)
    if existing is not None:
        raise ValueError(f"Workset '{workset_id}' already exists")
    ws = Workset(
        workset_id=workset_id,
        name=name,
        owner_email=owner_email,
        kind=kind,
    )
    manifest.worksets.append(ws)
    return ws


def workset_assign_element(
    manifest: WorksharingManifest,
    element_id: str,
    workset_id: str,
) -> bool:
    """Assign element_id to a workset (removes from any previous workset).

    Returns True on success, False if workset_id not found.
    """
    ws = manifest._find_workset(workset_id)
    if ws is None:
        return False
    # Remove from any existing workset
    for existing_ws in manifest.worksets:
        if element_id in existing_ws.element_ids:
            existing_ws.element_ids = [
                e for e in existing_ws.element_ids if e != element_id
            ]
    ws.element_ids.append(element_id)
    return True


def workset_set_owner(
    manifest: WorksharingManifest,
    workset_id: str,
    owner_email: str,
    requesting_email: str = "",
) -> bool:
    """Set or transfer workset ownership.

    Anyone can claim an unowned workset.  A currently-owned workset can only
    be transferred by the current owner (or pass requesting_email='' to bypass
    the ownership check in admin scenarios).

    Returns True on success.
    """
    ws = manifest._find_workset(workset_id)
    if ws is None:
        return False
    # If already owned and requesting_email provided, must match owner
    if ws.owner_email and requesting_email and ws.owner_email != requesting_email:
        return False
    ws.owner_email = owner_email
    return True


# ---------------------------------------------------------------------------
# Element borrow / release
# ---------------------------------------------------------------------------

def borrow_element(
    manifest: WorksharingManifest,
    element_id: str,
    user_email: str,
    duration_hours: float = 8.0,
    now_iso: Optional[str] = None,
) -> tuple[bool, str]:
    """Check out an element for exclusive editing.

    Returns (True, '') on success.
    Returns (False, reason) if blocked by:
      - Another user's active borrow on the same element.
      - Workset-level ownership: the workset owner's borrow automatically
        succeeds; other users must wait if the owner has borrowed the workset.

    A user re-borrowing their own element refreshes the expiry (idempotent).
    """
    now = now_iso or _now_iso()
    existing = manifest._find_borrow(element_id)

    if existing is not None:
        if not existing.is_expired(now):
            if existing.borrowed_by_email == user_email:
                # Idempotent re-borrow: refresh expiry
                existing.expires_at_iso = _add_hours(now, duration_hours)
                return True, ""
            # Someone else has it
            return (
                False,
                f"Element '{element_id}' is borrowed by {existing.borrowed_by_email} "
                f"until {existing.expires_at_iso}.",
            )
        else:
            # Expired borrow — evict it
            manifest.borrows = [b for b in manifest.borrows if b.element_id != element_id]

    # Check workset-level ownership: if a *different* user owns the workset AND
    # has an active borrow on the whole workset (borrow entry with element_id ==
    # 'workset:<id>'), block.  Simple heuristic for full workset checkout.
    ws = manifest._workset_for_element(element_id)
    if ws and ws.owner_email and ws.owner_email != user_email:
        # Check if the owner has a live workset-level borrow
        ws_borrow_id = f"workset:{ws.workset_id}"
        ws_borrow = manifest._find_borrow(ws_borrow_id)
        if ws_borrow and not ws_borrow.is_expired(now):
            return (
                False,
                f"Element '{element_id}' is in workset '{ws.name}' which is exclusively "
                f"borrowed by its owner {ws.owner_email}.",
            )

    entry = ElementBorrowEntry(
        element_id=element_id,
        borrowed_by_email=user_email,
        borrowed_at_iso=now,
        expires_at_iso=_add_hours(now, duration_hours),
        workset_id=ws.workset_id if ws else "",
        local_data={},
    )
    manifest.borrows.append(entry)
    return True, ""


def release_element(
    manifest: WorksharingManifest,
    element_id: str,
    user_email: str,
) -> bool:
    """Release a borrow WITHOUT committing any edits.

    Returns True on success, False if not found or not owned by user_email.
    """
    existing = manifest._find_borrow(element_id)
    if existing is None:
        return False
    if existing.borrowed_by_email != user_email:
        return False
    manifest.borrows = [b for b in manifest.borrows if b.element_id != element_id]
    return True


def update_local_data(
    manifest: WorksharingManifest,
    element_id: str,
    user_email: str,
    data: dict[str, Any],
) -> bool:
    """Store the user's local edit payload for a borrowed element.

    Returns False if the element is not currently borrowed by user_email.
    """
    existing = manifest._find_borrow(element_id)
    if existing is None or existing.borrowed_by_email != user_email:
        return False
    if existing.is_expired():
        return False
    existing.local_data = data
    return True


# ---------------------------------------------------------------------------
# Sync-to-central
# ---------------------------------------------------------------------------

def sync_to_central(
    manifest: WorksharingManifest,
    user_email: str,
    now_iso: Optional[str] = None,
) -> SyncResult:
    """Sync a user's borrowed-element edits to the central model.

    Algorithm (matches Revit Worksharing sync-to-central semantics):
    1. Collect all non-expired borrows held by user_email.
    2. For each such borrow:
       a. If central_element_data has a version that was updated by ANOTHER user
          since this user borrowed — CONFLICT (both users edited).
       b. Otherwise: push local_data → central_element_data; release the borrow.
    3. Pull: collect element IDs whose central data has changed since this user
       last synced, but are NOT borrowed by this user → pulled_elements list.
    4. Update last_sync_iso.

    Conflict detection: a conflict occurs when local_data is non-empty AND the
    central_element_data for that element was last written by a DIFFERENT user
    after the borrow was created.  The central_element_data stores an optional
    '_last_editor' key to track this.

    Returns SyncResult with synced/pulled/conflict lists.
    """
    now = now_iso or _now_iso()
    manifest.last_sync_iso = now

    user_borrows = [b for b in manifest.borrows
                    if b.borrowed_by_email == user_email and not b.is_expired(now)]

    synced: list[str] = []
    released: list[str] = []
    conflicts: list[ConflictRecord] = []

    for borrow in user_borrows:
        eid = borrow.element_id
        central = manifest.central_element_data.get(eid, {})
        central_last_editor = central.get("_last_editor", "")
        central_edited_at = central.get("_edited_at_iso", "")

        # Conflict: another user wrote to central AFTER this borrow was created
        # AND this user also has local edits (local_data is non-empty).
        has_local_edits = bool(borrow.local_data)
        central_updated_by_other = (
            central_last_editor
            and central_last_editor != user_email
            and central_edited_at
            and central_edited_at > borrow.borrowed_at_iso
        )

        if has_local_edits and central_updated_by_other:
            # Conflict — leave borrow in place; user must resolve manually
            conflicts.append(ConflictRecord(
                element_id=eid,
                user_a_email=user_email,
                user_b_email=central_last_editor,
                central_data=dict(central),
                user_a_data=dict(borrow.local_data),
                user_b_data={},           # other user's data already in central
                detected_at_iso=now,
            ))
        else:
            # No conflict: push local_data to central
            new_central = dict(borrow.local_data) if has_local_edits else dict(central)
            new_central["_last_editor"] = user_email
            new_central["_edited_at_iso"] = now
            manifest.central_element_data[eid] = new_central
            synced.append(eid)
            # Release borrow after successful sync
            manifest.borrows = [b for b in manifest.borrows if b.element_id != eid]
            released.append(eid)

    # Pull: elements in central that are NOT borrowed by this user and have
    # central data changed since the user's last known pull.
    borrowed_by_user = {b.element_id for b in manifest.borrows
                        if b.borrowed_by_email == user_email}
    pulled: list[str] = []
    for eid, cdata in manifest.central_element_data.items():
        if eid in borrowed_by_user:
            continue
        # Include all non-borrowed central elements as "pulled" (simplified)
        pulled.append(eid)

    return SyncResult(
        ok=True,
        synced_elements=synced,
        pulled_elements=pulled,
        conflicts=conflicts,
        released_borrows=released,
        message=(
            f"Sync complete: {len(synced)} pushed, {len(pulled)} pulled, "
            f"{len(conflicts)} conflict(s)."
        ),
    )


# ---------------------------------------------------------------------------
# Status summary
# ---------------------------------------------------------------------------

def worksharing_status(
    manifest: WorksharingManifest,
    now_iso: Optional[str] = None,
) -> dict[str, Any]:
    """Return a summary of current worksharing state."""
    now = now_iso or _now_iso()
    active = [b for b in manifest.borrows if not b.is_expired(now)]

    by_user: dict[str, list[str]] = {}
    for b in active:
        by_user.setdefault(b.borrowed_by_email, []).append(b.element_id)

    return {
        "project_id": manifest.project_id,
        "workset_count": len(manifest.worksets),
        "active_borrow_count": len(active),
        "central_element_count": len(manifest.central_element_data),
        "borrows_by_user": by_user,
        "worksets": [ws.to_dict() for ws in manifest.worksets],
        "last_sync_iso": manifest.last_sync_iso,
    }
