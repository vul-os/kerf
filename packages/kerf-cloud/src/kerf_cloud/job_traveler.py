"""
kerf_cloud.job_traveler
=======================

Purchase Order / Job Traveler / Inventory — thin production-ops layer.

Sits over:
  - BOM data from kerf_cad_core.jewelry.casting_export (casting_export_summary)
  - kerf-parts KerfPart.mpn / distributor refs for supplier_ref
  - File-keyed JSON store under data/cloud/jobs/ for persistence

All public functions follow the "never raise" contract: errors are returned
as dicts with ``{"ok": False, "error": "...", "code": "..."}``.
Success results carry ``{"ok": True, ...}``.

Persistence is a simple file-keyed JSON store — each document type gets its
own JSON file under ``<store_root>/``.  The store root defaults to
``data/cloud/jobs/`` relative to the caller's cwd; pass an explicit
``store_root`` Path to override (e.g. pytest tmp_path).

## Data model

PurchaseOrder
    id            — string (po-<timestamp>-<random>)
    customer      — str
    line_items    — list[LineItem]
    total         — float  (sum of qty * unit_price)
    status        — "draft" | "issued" | "received" | "closed"
    created_at    — ISO datetime str
    updated_at    — ISO datetime str

LineItem
    part_ref      — str  (mpn or sku)
    qty           — int
    unit_price    — float
    lead_time     — str  (free text, e.g. "5 days")

JobTraveler
    id                 — string (jt-<timestamp>-<random>)
    linked_po          — PO id or None
    linked_project_id  — str or None
    linked_revision_id — str or None
    stages             — dict[stage_name, StageRecord]
    current_stage      — str or None
    stage_history      — list[StageEvent]
    due_date           — ISO date str or None
    notes              — str
    status             — "open" | "closed"
    created_at         — ISO datetime str
    updated_at         — ISO datetime str

STAGE_ORDER = ["design", "cast", "clean", "set", "polish", "qc"]

StageRecord
    stage    — str
    status   — "pending" | "in_progress" | "done" | "skipped"
    assignee — str or None
    started_at  — ISO datetime str or None
    finished_at — ISO datetime str or None

StageEvent
    stage      — str
    event      — "started" | "completed" | "skipped"
    assignee   — str or None
    timestamp  — ISO datetime str

InventoryItem
    sku          — str  (part_ref / mpn)
    on_hand      — int
    allocated    — int
    reorder_point — int
    supplier_ref — str  (distributor part number or supplier name)
"""
from __future__ import annotations

import json
import random
import string
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Stage ordering
# ---------------------------------------------------------------------------

STAGE_ORDER: list[str] = ["design", "cast", "clean", "set", "polish", "qc"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OK = True
_FAIL = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rand_suffix(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _new_po_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"po-{ts}-{_rand_suffix()}"


def _new_jt_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"jt-{ts}-{_rand_suffix()}"


def _err(msg: str, code: str = "ERROR") -> dict:
    return {"ok": _FAIL, "error": msg, "code": code}


def _ok(**kwargs) -> dict:
    return {"ok": _OK, **kwargs}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LineItem:
    part_ref: str
    qty: int
    unit_price: float
    lead_time: str = ""


@dataclass
class PurchaseOrder:
    id: str
    customer: str
    line_items: list[LineItem]
    total: float
    status: str  # draft | issued | received | closed
    created_at: str
    updated_at: str


@dataclass
class StageRecord:
    stage: str
    status: str = "pending"       # pending | in_progress | done | skipped
    assignee: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


@dataclass
class StageEvent:
    stage: str
    event: str                    # started | completed | skipped
    assignee: Optional[str]
    timestamp: str


@dataclass
class JobTraveler:
    id: str
    linked_po: Optional[str]
    linked_project_id: Optional[str]
    linked_revision_id: Optional[str]
    stages: dict[str, StageRecord]
    current_stage: Optional[str]
    stage_history: list[StageEvent]
    due_date: Optional[str]
    notes: str
    status: str                   # open | closed
    created_at: str
    updated_at: str


@dataclass
class InventoryItem:
    sku: str
    on_hand: int
    allocated: int
    reorder_point: int
    supplier_ref: str = ""


# ---------------------------------------------------------------------------
# JSON serialisation helpers
# ---------------------------------------------------------------------------

def _line_item_to_dict(li: LineItem) -> dict:
    return asdict(li)


def _line_item_from_dict(d: dict) -> LineItem:
    return LineItem(
        part_ref=d["part_ref"],
        qty=int(d["qty"]),
        unit_price=float(d["unit_price"]),
        lead_time=d.get("lead_time", ""),
    )


def _po_to_dict(po: PurchaseOrder) -> dict:
    return {
        "id": po.id,
        "customer": po.customer,
        "line_items": [_line_item_to_dict(li) for li in po.line_items],
        "total": po.total,
        "status": po.status,
        "created_at": po.created_at,
        "updated_at": po.updated_at,
    }


def _po_from_dict(d: dict) -> PurchaseOrder:
    return PurchaseOrder(
        id=d["id"],
        customer=d["customer"],
        line_items=[_line_item_from_dict(li) for li in d.get("line_items", [])],
        total=float(d["total"]),
        status=d["status"],
        created_at=d["created_at"],
        updated_at=d["updated_at"],
    )


def _stage_record_to_dict(sr: StageRecord) -> dict:
    return asdict(sr)


def _stage_record_from_dict(d: dict) -> StageRecord:
    return StageRecord(
        stage=d["stage"],
        status=d.get("status", "pending"),
        assignee=d.get("assignee"),
        started_at=d.get("started_at"),
        finished_at=d.get("finished_at"),
    )


def _stage_event_to_dict(se: StageEvent) -> dict:
    return asdict(se)


def _stage_event_from_dict(d: dict) -> StageEvent:
    return StageEvent(
        stage=d["stage"],
        event=d["event"],
        assignee=d.get("assignee"),
        timestamp=d["timestamp"],
    )


def _jt_to_dict(jt: JobTraveler) -> dict:
    return {
        "id": jt.id,
        "linked_po": jt.linked_po,
        "linked_project_id": jt.linked_project_id,
        "linked_revision_id": jt.linked_revision_id,
        "stages": {k: _stage_record_to_dict(v) for k, v in jt.stages.items()},
        "current_stage": jt.current_stage,
        "stage_history": [_stage_event_to_dict(e) for e in jt.stage_history],
        "due_date": jt.due_date,
        "notes": jt.notes,
        "status": jt.status,
        "created_at": jt.created_at,
        "updated_at": jt.updated_at,
    }


def _jt_from_dict(d: dict) -> JobTraveler:
    stages_raw = d.get("stages", {})
    stages = {k: _stage_record_from_dict(v) for k, v in stages_raw.items()}
    history_raw = d.get("stage_history", [])
    history = [_stage_event_from_dict(e) for e in history_raw]
    return JobTraveler(
        id=d["id"],
        linked_po=d.get("linked_po"),
        linked_project_id=d.get("linked_project_id"),
        linked_revision_id=d.get("linked_revision_id"),
        stages=stages,
        current_stage=d.get("current_stage"),
        stage_history=history,
        due_date=d.get("due_date"),
        notes=d.get("notes", ""),
        status=d.get("status", "open"),
        created_at=d["created_at"],
        updated_at=d["updated_at"],
    )


def _inv_to_dict(item: InventoryItem) -> dict:
    return asdict(item)


def _inv_from_dict(d: dict) -> InventoryItem:
    return InventoryItem(
        sku=d["sku"],
        on_hand=int(d["on_hand"]),
        allocated=int(d["allocated"]),
        reorder_point=int(d["reorder_point"]),
        supplier_ref=d.get("supplier_ref", ""),
    )


# ---------------------------------------------------------------------------
# File-keyed JSON store
# ---------------------------------------------------------------------------

_DEFAULT_STORE = Path("data/cloud/jobs")


def _store_path(store_root: Optional[Path] = None) -> Path:
    return Path(store_root) if store_root is not None else _DEFAULT_STORE


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _load_store(filename: str, store_root: Optional[Path] = None) -> dict:
    """Load a JSON file from the store; return {} on any failure."""
    try:
        path = _store_path(store_root) / filename
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_store(filename: str, data: dict, store_root: Optional[Path] = None) -> None:
    """Persist a dict to a JSON file; silently skip on failure."""
    try:
        root = _store_path(store_root)
        _ensure_dir(root)
        path = root / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# Store filenames
_PO_FILE = "purchase_orders.json"
_JT_FILE = "job_travelers.json"
_INV_FILE = "inventory.json"


# ---------------------------------------------------------------------------
# Internal CRUD helpers
# ---------------------------------------------------------------------------

def _load_pos(store_root: Optional[Path] = None) -> dict[str, PurchaseOrder]:
    raw = _load_store(_PO_FILE, store_root)
    return {k: _po_from_dict(v) for k, v in raw.items()}


def _save_pos(pos: dict[str, PurchaseOrder], store_root: Optional[Path] = None) -> None:
    _save_store(_PO_FILE, {k: _po_to_dict(v) for k, v in pos.items()}, store_root)


def _load_jts(store_root: Optional[Path] = None) -> dict[str, JobTraveler]:
    raw = _load_store(_JT_FILE, store_root)
    return {k: _jt_from_dict(v) for k, v in raw.items()}


def _save_jts(jts: dict[str, JobTraveler], store_root: Optional[Path] = None) -> None:
    _save_store(_JT_FILE, {k: _jt_to_dict(v) for k, v in jts.items()}, store_root)


def _load_inv(store_root: Optional[Path] = None) -> dict[str, InventoryItem]:
    raw = _load_store(_INV_FILE, store_root)
    return {k: _inv_from_dict(v) for k, v in raw.items()}


def _save_inv(inv: dict[str, InventoryItem], store_root: Optional[Path] = None) -> None:
    _save_store(_INV_FILE, {k: _inv_to_dict(v) for k, v in inv.items()}, store_root)


# ---------------------------------------------------------------------------
# Purchase Order operations
# ---------------------------------------------------------------------------

def create_po(
    customer: str,
    items: list[dict],
    store_root: Optional[Path] = None,
) -> dict:
    """
    Create a new PurchaseOrder in draft status.

    Parameters
    ----------
    customer : str
        Customer name or identifier.
    items : list[dict]
        Each item: {"part_ref": str, "qty": int, "unit_price": float,
                    "lead_time": str (optional)}.
    store_root : Path, optional
        Override the default JSON-store root.

    Returns
    -------
    dict — ok=True + "po" (PurchaseOrder as dict) on success.
    """
    if not customer or not str(customer).strip():
        return _err("customer must be a non-empty string", "BAD_ARGS")
    if not isinstance(items, list) or len(items) == 0:
        return _err("items must be a non-empty list", "BAD_ARGS")

    line_items: list[LineItem] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            return _err(f"items[{idx}] must be a dict", "BAD_ARGS")
        part_ref = item.get("part_ref", "")
        if not part_ref:
            return _err(f"items[{idx}].part_ref is required", "BAD_ARGS")
        try:
            qty = int(item.get("qty", 0))
        except (TypeError, ValueError):
            return _err(f"items[{idx}].qty must be an integer", "BAD_ARGS")
        if qty <= 0:
            return _err(f"items[{idx}].qty must be > 0", "BAD_ARGS")
        try:
            unit_price = float(item.get("unit_price", 0.0))
        except (TypeError, ValueError):
            return _err(f"items[{idx}].unit_price must be a number", "BAD_ARGS")
        if unit_price < 0:
            return _err(f"items[{idx}].unit_price must be >= 0", "BAD_ARGS")
        lead_time = str(item.get("lead_time", ""))
        line_items.append(LineItem(part_ref=str(part_ref), qty=qty, unit_price=unit_price, lead_time=lead_time))

    total = sum(li.qty * li.unit_price for li in line_items)
    now = _now_iso()
    po = PurchaseOrder(
        id=_new_po_id(),
        customer=str(customer).strip(),
        line_items=line_items,
        total=round(total, 6),
        status="draft",
        created_at=now,
        updated_at=now,
    )
    pos = _load_pos(store_root)
    pos[po.id] = po
    _save_pos(pos, store_root)
    return _ok(po=_po_to_dict(po))


def issue_po(po_id: str, store_root: Optional[Path] = None) -> dict:
    """
    Transition a PO from draft → issued.

    Returns
    -------
    dict — ok=True + "po" on success; ok=False on errors.
    """
    pos = _load_pos(store_root)
    po = pos.get(po_id)
    if po is None:
        return _err(f"PO not found: {po_id}", "NOT_FOUND")
    if po.status != "draft":
        return _err(f"PO {po_id} is already {po.status}; can only issue draft POs", "INVALID_STATE")
    po.status = "issued"
    po.updated_at = _now_iso()
    pos[po_id] = po
    _save_pos(pos, store_root)
    return _ok(po=_po_to_dict(po))


def receive_po(
    po_id: str,
    received_items: list[dict],
    store_root: Optional[Path] = None,
) -> dict:
    """
    Mark a PO as received and update inventory on-hand quantities.

    ``received_items`` is a list of ``{"part_ref": str, "qty": int}`` dicts
    representing what was actually delivered (may differ from ordered qty).

    Updates (or creates) InventoryItem records for each received part.

    Returns
    -------
    dict — ok=True + "po" + "inventory_updates" list on success.
    """
    pos = _load_pos(store_root)
    po = pos.get(po_id)
    if po is None:
        return _err(f"PO not found: {po_id}", "NOT_FOUND")
    if po.status not in ("issued",):
        return _err(f"PO {po_id} must be 'issued' to receive; current status: {po.status}", "INVALID_STATE")
    if not isinstance(received_items, list) or len(received_items) == 0:
        return _err("received_items must be a non-empty list", "BAD_ARGS")

    inv = _load_inv(store_root)
    updates: list[dict] = []
    for idx, item in enumerate(received_items):
        if not isinstance(item, dict):
            return _err(f"received_items[{idx}] must be a dict", "BAD_ARGS")
        part_ref = str(item.get("part_ref", "")).strip()
        if not part_ref:
            return _err(f"received_items[{idx}].part_ref is required", "BAD_ARGS")
        try:
            qty = int(item.get("qty", 0))
        except (TypeError, ValueError):
            return _err(f"received_items[{idx}].qty must be an integer", "BAD_ARGS")
        if qty <= 0:
            return _err(f"received_items[{idx}].qty must be > 0", "BAD_ARGS")

        if part_ref in inv:
            inv[part_ref].on_hand += qty
        else:
            inv[part_ref] = InventoryItem(
                sku=part_ref,
                on_hand=qty,
                allocated=0,
                reorder_point=0,
                supplier_ref="",
            )
        updates.append({"part_ref": part_ref, "qty_received": qty, "on_hand": inv[part_ref].on_hand})

    po.status = "received"
    po.updated_at = _now_iso()
    pos[po_id] = po
    _save_pos(pos, store_root)
    _save_inv(inv, store_root)
    return _ok(po=_po_to_dict(po), inventory_updates=updates)


def get_po(po_id: str, store_root: Optional[Path] = None) -> dict:
    """Retrieve a PO by id."""
    pos = _load_pos(store_root)
    po = pos.get(po_id)
    if po is None:
        return _err(f"PO not found: {po_id}", "NOT_FOUND")
    return _ok(po=_po_to_dict(po))


def list_pos(store_root: Optional[Path] = None) -> dict:
    """Return all POs."""
    pos = _load_pos(store_root)
    return _ok(purchase_orders=[_po_to_dict(v) for v in pos.values()])


# ---------------------------------------------------------------------------
# Job Traveler operations
# ---------------------------------------------------------------------------

def _build_stages() -> dict[str, StageRecord]:
    return {s: StageRecord(stage=s) for s in STAGE_ORDER}


def start_traveler(
    po: Optional[str] = None,
    project: Optional[str] = None,
    revision: Optional[str] = None,
    due_date: Optional[str] = None,
    notes: str = "",
    store_root: Optional[Path] = None,
) -> dict:
    """
    Create and persist a new JobTraveler.  First stage is 'design'.

    Parameters
    ----------
    po : str, optional
        Linked PO id.
    project : str, optional
        Linked project id.
    revision : str, optional
        Linked file-revision id.
    due_date : str, optional
        ISO date string (e.g. "2026-06-01").
    notes : str
        Free-form notes.
    store_root : Path, optional
        Override the default JSON-store root.

    Returns
    -------
    dict — ok=True + "traveler" on success.
    """
    now = _now_iso()
    first_stage = STAGE_ORDER[0]
    stages = _build_stages()
    stages[first_stage].status = "in_progress"
    stages[first_stage].started_at = now

    jt = JobTraveler(
        id=_new_jt_id(),
        linked_po=po,
        linked_project_id=project,
        linked_revision_id=revision,
        stages=stages,
        current_stage=first_stage,
        stage_history=[
            StageEvent(
                stage=first_stage,
                event="started",
                assignee=None,
                timestamp=now,
            )
        ],
        due_date=due_date,
        notes=notes,
        status="open",
        created_at=now,
        updated_at=now,
    )
    jts = _load_jts(store_root)
    jts[jt.id] = jt
    _save_jts(jts, store_root)
    return _ok(traveler=_jt_to_dict(jt))


def advance_stage(
    traveler_id: str,
    stage: str,
    assignee: Optional[str] = None,
    store_root: Optional[Path] = None,
) -> dict:
    """
    Mark the given stage as complete and advance to the next stage.

    Stage transitions are monotonic: you can only advance, never go back.
    ``stage`` must be the current stage of the traveler.

    Parameters
    ----------
    traveler_id : str
        ID of the JobTraveler to advance.
    stage : str
        The stage being completed (must match current_stage).
    assignee : str, optional
        Person completing this stage.
    store_root : Path, optional
        Override the default JSON-store root.

    Returns
    -------
    dict — ok=True + "traveler" + "next_stage" (None if last stage complete).
    """
    if stage not in STAGE_ORDER:
        return _err(f"Unknown stage '{stage}'. Valid: {STAGE_ORDER}", "BAD_ARGS")

    jts = _load_jts(store_root)
    jt = jts.get(traveler_id)
    if jt is None:
        return _err(f"JobTraveler not found: {traveler_id}", "NOT_FOUND")
    if jt.status == "closed":
        return _err(f"Traveler {traveler_id} is already closed", "INVALID_STATE")
    if jt.current_stage != stage:
        return _err(
            f"Stage '{stage}' is not the current stage (current: {jt.current_stage}); "
            "stages must be advanced in order",
            "INVALID_STATE",
        )

    now = _now_iso()
    # Complete current stage
    sr = jt.stages[stage]
    sr.status = "done"
    sr.assignee = assignee
    sr.finished_at = now
    jt.stage_history.append(
        StageEvent(stage=stage, event="completed", assignee=assignee, timestamp=now)
    )

    # Determine next stage
    idx = STAGE_ORDER.index(stage)
    next_stage: Optional[str] = None
    if idx + 1 < len(STAGE_ORDER):
        next_stage = STAGE_ORDER[idx + 1]
        jt.current_stage = next_stage
        jt.stages[next_stage].status = "in_progress"
        jt.stages[next_stage].started_at = now
        jt.stage_history.append(
            StageEvent(stage=next_stage, event="started", assignee=None, timestamp=now)
        )
    else:
        # All stages done
        jt.current_stage = None

    jt.updated_at = now
    jts[traveler_id] = jt
    _save_jts(jts, store_root)
    return _ok(traveler=_jt_to_dict(jt), next_stage=next_stage)


def close_traveler(
    traveler_id: str,
    qc_pass: bool,
    notes: str = "",
    store_root: Optional[Path] = None,
) -> dict:
    """
    Close a JobTraveler.  ``qc_pass=True`` is required to close successfully.

    Parameters
    ----------
    traveler_id : str
        ID of the JobTraveler to close.
    qc_pass : bool
        Must be True; if False the traveler is flagged as QC-failed and
        remains open.
    notes : str
        Optional closing notes appended to the traveler's notes field.
    store_root : Path, optional
        Override the default JSON-store root.

    Returns
    -------
    dict — ok=True + "traveler" on success; ok=False if qc_pass is False.
    """
    jts = _load_jts(store_root)
    jt = jts.get(traveler_id)
    if jt is None:
        return _err(f"JobTraveler not found: {traveler_id}", "NOT_FOUND")
    if jt.status == "closed":
        return _err(f"Traveler {traveler_id} is already closed", "INVALID_STATE")
    if not qc_pass:
        return _err(
            "qc_pass must be True to close a traveler; "
            "address QC failures before closing",
            "QC_FAILED",
        )

    now = _now_iso()
    if notes:
        sep = "\n" if jt.notes else ""
        jt.notes = jt.notes + sep + notes
    jt.status = "closed"
    jt.updated_at = now
    jts[traveler_id] = jt
    _save_jts(jts, store_root)
    return _ok(traveler=_jt_to_dict(jt))


def get_traveler(traveler_id: str, store_root: Optional[Path] = None) -> dict:
    """Retrieve a JobTraveler by id."""
    jts = _load_jts(store_root)
    jt = jts.get(traveler_id)
    if jt is None:
        return _err(f"JobTraveler not found: {traveler_id}", "NOT_FOUND")
    return _ok(traveler=_jt_to_dict(jt))


def list_travelers(store_root: Optional[Path] = None) -> dict:
    """Return all JobTravelers."""
    jts = _load_jts(store_root)
    return _ok(travelers=[_jt_to_dict(v) for v in jts.values()])


# ---------------------------------------------------------------------------
# Inventory operations
# ---------------------------------------------------------------------------

def upsert_inventory_item(
    sku: str,
    on_hand: int,
    allocated: int = 0,
    reorder_point: int = 0,
    supplier_ref: str = "",
    store_root: Optional[Path] = None,
) -> dict:
    """
    Create or update an InventoryItem.

    Returns
    -------
    dict — ok=True + "item" on success.
    """
    if not sku or not str(sku).strip():
        return _err("sku must be a non-empty string", "BAD_ARGS")
    try:
        on_hand = int(on_hand)
        allocated = int(allocated)
        reorder_point = int(reorder_point)
    except (TypeError, ValueError):
        return _err("on_hand, allocated, reorder_point must be integers", "BAD_ARGS")
    if on_hand < 0:
        return _err("on_hand must be >= 0", "BAD_ARGS")
    if allocated < 0:
        return _err("allocated must be >= 0", "BAD_ARGS")
    if allocated > on_hand:
        return _err(f"allocated ({allocated}) cannot exceed on_hand ({on_hand})", "BAD_ARGS")

    inv = _load_inv(store_root)
    item = InventoryItem(
        sku=str(sku).strip(),
        on_hand=on_hand,
        allocated=allocated,
        reorder_point=reorder_point,
        supplier_ref=supplier_ref,
    )
    inv[item.sku] = item
    _save_inv(inv, store_root)
    return _ok(item=_inv_to_dict(item))


def get_inventory_item(sku: str, store_root: Optional[Path] = None) -> dict:
    """Retrieve an InventoryItem by sku."""
    inv = _load_inv(store_root)
    item = inv.get(sku)
    if item is None:
        return _err(f"Inventory item not found: {sku}", "NOT_FOUND")
    return _ok(item=_inv_to_dict(item))


def list_inventory(store_root: Optional[Path] = None) -> dict:
    """Return all InventoryItems."""
    inv = _load_inv(store_root)
    return _ok(items=[_inv_to_dict(v) for v in inv.values()])


# ---------------------------------------------------------------------------
# allocation_check
# ---------------------------------------------------------------------------

def allocation_check(
    items: list[dict],
    store_root: Optional[Path] = None,
) -> dict:
    """
    Check whether on_hand − allocated >= requested qty for each item.

    Parameters
    ----------
    items : list[dict]
        Each: {"part_ref": str, "qty": int}.
    store_root : Path, optional
        Override the default JSON-store root.

    Returns
    -------
    dict:
        ok         — True if ALL items can be filled from available stock.
        checks     — list of per-item results:
                       {"part_ref", "qty_requested", "on_hand", "allocated",
                        "available", "shortfall", "ok"}
        shortfalls — list of part_refs where available < requested.
    """
    if not isinstance(items, list):
        return _err("items must be a list", "BAD_ARGS")

    inv = _load_inv(store_root)
    checks: list[dict] = []
    shortfalls: list[str] = []

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            return _err(f"items[{idx}] must be a dict", "BAD_ARGS")
        part_ref = str(item.get("part_ref", "")).strip()
        if not part_ref:
            return _err(f"items[{idx}].part_ref is required", "BAD_ARGS")
        try:
            qty_req = int(item.get("qty", 0))
        except (TypeError, ValueError):
            return _err(f"items[{idx}].qty must be an integer", "BAD_ARGS")
        if qty_req <= 0:
            return _err(f"items[{idx}].qty must be > 0", "BAD_ARGS")

        inv_item = inv.get(part_ref)
        if inv_item is None:
            available = 0
            on_hand = 0
            allocated = 0
        else:
            on_hand = inv_item.on_hand
            allocated = inv_item.allocated
            available = max(0, on_hand - allocated)

        shortfall = max(0, qty_req - available)
        item_ok = shortfall == 0
        if not item_ok:
            shortfalls.append(part_ref)

        checks.append({
            "part_ref": part_ref,
            "qty_requested": qty_req,
            "on_hand": on_hand,
            "allocated": allocated,
            "available": available,
            "shortfall": shortfall,
            "ok": item_ok,
        })

    return _ok(
        ok=len(shortfalls) == 0,   # override inner ok with allocation result
        checks=checks,
        shortfalls=shortfalls,
    )


# ---------------------------------------------------------------------------
# inventory_pick_list
# ---------------------------------------------------------------------------

def inventory_pick_list(
    bom: list[dict],
    store_root: Optional[Path] = None,
) -> dict:
    """
    For a jewelry BOM (from casting_export or similar), partition items into
    those that can be filled from on-hand stock vs those that need ordering.

    The BOM is a list of dicts each with at minimum:
        ``part_ref`` (str)  — the SKU / mpn to look up in inventory
        ``qty``      (int)  — quantity required

    Returns
    -------
    dict:
        ok                — True
        can_fill          — list of BOM items fully satisfiable from on-hand
                            (each dict includes inventory snapshot)
        needs_order       — list of BOM items with shortfalls
                            (each dict includes shortfall qty and reorder info)
        summary           — {"total_lines", "fill_lines", "order_lines"}
    """
    if not isinstance(bom, list):
        return _err("bom must be a list", "BAD_ARGS")

    inv = _load_inv(store_root)
    can_fill: list[dict] = []
    needs_order: list[dict] = []

    for idx, entry in enumerate(bom):
        if not isinstance(entry, dict):
            return _err(f"bom[{idx}] must be a dict", "BAD_ARGS")
        part_ref = str(entry.get("part_ref", "")).strip()
        if not part_ref:
            return _err(f"bom[{idx}].part_ref is required", "BAD_ARGS")
        try:
            qty_req = int(entry.get("qty", 0))
        except (TypeError, ValueError):
            return _err(f"bom[{idx}].qty must be an integer", "BAD_ARGS")
        if qty_req <= 0:
            return _err(f"bom[{idx}].qty must be > 0", "BAD_ARGS")

        inv_item = inv.get(part_ref)
        if inv_item is None:
            available = 0
            on_hand = 0
            allocated = 0
            supplier_ref = ""
            reorder_point = 0
        else:
            on_hand = inv_item.on_hand
            allocated = inv_item.allocated
            available = max(0, on_hand - allocated)
            supplier_ref = inv_item.supplier_ref
            reorder_point = inv_item.reorder_point

        shortfall = max(0, qty_req - available)
        row = {
            **{k: v for k, v in entry.items()},   # preserve original BOM fields
            "part_ref": part_ref,
            "qty_requested": qty_req,
            "on_hand": on_hand,
            "allocated": allocated,
            "available": available,
            "shortfall": shortfall,
            "supplier_ref": supplier_ref,
            "reorder_point": reorder_point,
        }
        if shortfall == 0:
            can_fill.append(row)
        else:
            needs_order.append(row)

    return _ok(
        can_fill=can_fill,
        needs_order=needs_order,
        summary={
            "total_lines": len(bom),
            "fill_lines": len(can_fill),
            "order_lines": len(needs_order),
        },
    )


# ---------------------------------------------------------------------------
# Optional LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register as _register
    from kerf_core.utils.context import ProjectCtx as _ProjectCtx

    _create_po_spec = ToolSpec(
        name="job_create_po",
        description=(
            "Create a new Purchase Order (draft) for parts/materials.\n\n"
            "Returns the new PO with a generated id and status='draft'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "customer": {"type": "string", "description": "Customer name or id."},
                "items": {
                    "type": "array",
                    "description": "Line items.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "part_ref": {"type": "string"},
                            "qty": {"type": "integer"},
                            "unit_price": {"type": "number"},
                            "lead_time": {"type": "string"},
                        },
                        "required": ["part_ref", "qty", "unit_price"],
                    },
                },
            },
            "required": ["customer", "items"],
        },
    )

    @_register(_create_po_spec, write=True)
    async def _run_job_create_po(ctx: _ProjectCtx, args: bytes) -> str:
        import json as _json
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        result = create_po(a.get("customer", ""), a.get("items", []))
        if not result.get("ok"):
            return err_payload(result.get("error", "error"), result.get("code", "ERROR"))
        return ok_payload(result)

    _pick_list_spec = ToolSpec(
        name="job_inventory_pick_list",
        description=(
            "For a jewelry/production BOM, return which items can be filled from "
            "on-hand inventory vs which need ordering."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bom": {
                    "type": "array",
                    "description": "BOM lines: [{part_ref, qty, ...}].",
                    "items": {"type": "object"},
                },
            },
            "required": ["bom"],
        },
    )

    @_register(_pick_list_spec, write=False)
    async def _run_job_inventory_pick_list(ctx: _ProjectCtx, args: bytes) -> str:
        import json as _json
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        result = inventory_pick_list(a.get("bom", []))
        if not result.get("ok"):
            return err_payload(result.get("error", "error"), result.get("code", "ERROR"))
        return ok_payload(result)

    _TOOLS_REGISTERED = True

except Exception:
    _TOOLS_REGISTERED = False
