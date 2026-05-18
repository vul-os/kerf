"""
Parametric FF&E (Furniture, Fixtures & Equipment) generators.

Each generator returns a ``FurnitureItem`` dataclass that describes the
object's bounding box, clearance zones, and metadata.  All dimensions are
in millimetres.

Typical industry sizes used as defaults
---------------------------------------
Chair (task/side)    : 500 W × 500 D × 850 H, seat 450 mm AFF
Desk (sit-stand)     : 1500 W × 750 D × 730 H  (fixed-height default)
Sofa (3-seat)        : 2100 W × 950 D × 900 H, seat 450 mm AFF
Dining table (4-top) : 900 W × 900 D × 750 H
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Core data type
# ---------------------------------------------------------------------------

@dataclass
class FurnitureItem:
    """A placed or unplaced piece of furniture / equipment.

    Coordinates are in mm; ``origin`` is the front-left corner at floor level
    (same convention as Kerf BIM spaces).

    Attributes
    ----------
    name:
        Human-readable label (e.g. ``"Task Chair"``, ``"Sit-Stand Desk"``).
    kind:
        Category key: ``"chair"``, ``"desk"``, ``"sofa"``, ``"table"``.
    width_mm:
        Bounding-box width (X-axis) in mm.
    depth_mm:
        Bounding-box depth (Y-axis) in mm.
    height_mm:
        Bounding-box height (Z-axis) in mm.
    seat_height_mm:
        Height of seat or working surface above finished floor in mm.
        ``None`` for items without a defined seating height.
    clearance_front_mm:
        Required clear space in front of the item (pull-out, egress).
    clearance_back_mm:
        Required clear space behind the item.
    clearance_left_mm:
        Required clear space to the left.
    clearance_right_mm:
        Required clear space to the right.
    origin:
        ``(x, y)`` position of the front-left corner in mm, or ``None`` if
        the item has not been placed in a layout.
    rotation_deg:
        Rotation about the vertical axis (Z) in degrees, measured
        counter-clockwise from the +X axis.
    metadata:
        Arbitrary extra data (finish, manufacturer, etc.).
    """
    name: str
    kind: str
    width_mm: float
    depth_mm: float
    height_mm: float
    seat_height_mm: float | None = None
    clearance_front_mm: float = 0.0
    clearance_back_mm: float = 0.0
    clearance_left_mm: float = 0.0
    clearance_right_mm: float = 0.0
    origin: tuple[float, float] | None = None
    rotation_deg: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Derived geometry helpers
    # ------------------------------------------------------------------

    @property
    def footprint_area_m2(self) -> float:
        """Bounding-box footprint in square metres."""
        return (self.width_mm / 1000.0) * (self.depth_mm / 1000.0)

    @property
    def clearance_envelope_mm(self) -> tuple[float, float]:
        """``(total_width, total_depth)`` including all clearance zones."""
        w = self.width_mm + self.clearance_left_mm + self.clearance_right_mm
        d = self.depth_mm + self.clearance_front_mm + self.clearance_back_mm
        return w, d

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for JSON export."""
        return {
            "name": self.name,
            "kind": self.kind,
            "width_mm": self.width_mm,
            "depth_mm": self.depth_mm,
            "height_mm": self.height_mm,
            "seat_height_mm": self.seat_height_mm,
            "clearance_front_mm": self.clearance_front_mm,
            "clearance_back_mm": self.clearance_back_mm,
            "clearance_left_mm": self.clearance_left_mm,
            "clearance_right_mm": self.clearance_right_mm,
            "origin": list(self.origin) if self.origin else None,
            "rotation_deg": self.rotation_deg,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FurnitureItem":
        """Deserialise from a plain dict."""
        origin = data.get("origin")
        return cls(
            name=data["name"],
            kind=data["kind"],
            width_mm=float(data["width_mm"]),
            depth_mm=float(data["depth_mm"]),
            height_mm=float(data["height_mm"]),
            seat_height_mm=data.get("seat_height_mm"),
            clearance_front_mm=float(data.get("clearance_front_mm", 0.0)),
            clearance_back_mm=float(data.get("clearance_back_mm", 0.0)),
            clearance_left_mm=float(data.get("clearance_left_mm", 0.0)),
            clearance_right_mm=float(data.get("clearance_right_mm", 0.0)),
            origin=tuple(origin) if origin else None,
            rotation_deg=float(data.get("rotation_deg", 0.0)),
            metadata=dict(data.get("metadata", {})),
        )


# ---------------------------------------------------------------------------
# Parametric generators
# ---------------------------------------------------------------------------

def make_chair(
    *,
    name: str = "Task Chair",
    width_mm: float = 500.0,
    depth_mm: float = 500.0,
    height_mm: float = 1200.0,
    seat_height_mm: float = 450.0,
    with_ada_clearance: bool = True,
    **metadata: Any,
) -> FurnitureItem:
    """Generate a parametric chair (task, side, dining, lounge).

    Parameters
    ----------
    name:
        Label for this chair instance.
    width_mm:
        Overall width of the chair bounding box.
    depth_mm:
        Overall depth (front-to-back) of the chair bounding box.
    height_mm:
        Overall height including back rest.
    seat_height_mm:
        Height of the seat surface above finished floor.
    with_ada_clearance:
        If True, apply a 914 mm (36 in) clear-floor space in front for
        wheelchair-accessible seating positions.
    **metadata:
        Arbitrary keyword arguments stored in ``item.metadata``.

    Returns
    -------
    FurnitureItem
    """
    clearance_front = 914.0 if with_ada_clearance else 300.0
    return FurnitureItem(
        name=name,
        kind="chair",
        width_mm=width_mm,
        depth_mm=depth_mm,
        height_mm=height_mm,
        seat_height_mm=seat_height_mm,
        clearance_front_mm=clearance_front,
        clearance_back_mm=100.0,
        clearance_left_mm=50.0,
        clearance_right_mm=50.0,
        metadata=dict(metadata),
    )


def make_desk(
    *,
    name: str = "Work Desk",
    width_mm: float = 1500.0,
    depth_mm: float = 750.0,
    height_mm: float = 730.0,
    seat_height_mm: float | None = None,
    knee_clearance_height_mm: float = 686.0,
    knee_clearance_depth_mm: float = 483.0,
    with_ada_clearance: bool = True,
    **metadata: Any,
) -> FurnitureItem:
    """Generate a parametric desk (fixed, sit-stand, return).

    ADA §306 requires 686 mm (27 in) knee clearance height and 483 mm (19 in)
    depth under accessible work surfaces.  These are stored in metadata for
    downstream clearance checks.

    Parameters
    ----------
    name:
        Label for this desk instance.
    width_mm:
        Desktop width.
    depth_mm:
        Desktop depth front-to-back.
    height_mm:
        Working surface height above finished floor.
    seat_height_mm:
        If provided, overrides the surface height as the seating reference
        (useful for height-adjustable desks).
    knee_clearance_height_mm:
        Clear height under the desk surface (for ADA knee-clearance audit).
    knee_clearance_depth_mm:
        Clear depth under the desk surface (for ADA knee-clearance audit).
    with_ada_clearance:
        If True, apply a 914 mm clear-floor approach zone at the front.
    **metadata:
        Arbitrary keyword arguments stored in ``item.metadata``.

    Returns
    -------
    FurnitureItem
    """
    clearance_front = 914.0 if with_ada_clearance else 400.0
    meta = dict(metadata)
    meta.setdefault("knee_clearance_height_mm", knee_clearance_height_mm)
    meta.setdefault("knee_clearance_depth_mm", knee_clearance_depth_mm)
    return FurnitureItem(
        name=name,
        kind="desk",
        width_mm=width_mm,
        depth_mm=depth_mm,
        height_mm=height_mm,
        seat_height_mm=seat_height_mm,
        clearance_front_mm=clearance_front,
        clearance_back_mm=100.0,
        clearance_left_mm=50.0,
        clearance_right_mm=50.0,
        metadata=meta,
    )


def make_sofa(
    *,
    name: str = "Sofa",
    seats: int = 3,
    seat_width_mm: float = 600.0,
    depth_mm: float = 950.0,
    height_mm: float = 900.0,
    seat_height_mm: float = 450.0,
    arm_width_mm: float = 150.0,
    **metadata: Any,
) -> FurnitureItem:
    """Generate a parametric sofa.

    Total width is computed as ``seats * seat_width_mm + 2 * arm_width_mm``.

    Parameters
    ----------
    name:
        Label for this sofa instance.
    seats:
        Number of seat positions (1–5).
    seat_width_mm:
        Width of each seat cushion.
    depth_mm:
        Sofa depth front-to-back.
    height_mm:
        Total height including back cushions.
    seat_height_mm:
        Seat surface height above finished floor.
    arm_width_mm:
        Width of each arm rest.
    **metadata:
        Arbitrary keyword arguments stored in ``item.metadata``.

    Returns
    -------
    FurnitureItem
    """
    if seats < 1 or seats > 5:
        raise ValueError(f"seats must be between 1 and 5, got {seats!r}")
    total_width = seats * seat_width_mm + 2 * arm_width_mm
    meta = dict(metadata)
    meta.setdefault("seats", seats)
    return FurnitureItem(
        name=name,
        kind="sofa",
        width_mm=total_width,
        depth_mm=depth_mm,
        height_mm=height_mm,
        seat_height_mm=seat_height_mm,
        clearance_front_mm=1000.0,   # coffee-table zone + circulation
        clearance_back_mm=50.0,
        clearance_left_mm=50.0,
        clearance_right_mm=50.0,
        metadata=meta,
    )


def make_table(
    *,
    name: str = "Dining Table",
    width_mm: float = 900.0,
    depth_mm: float = 900.0,
    height_mm: float = 750.0,
    seats: int = 4,
    with_ada_clearance: bool = True,
    **metadata: Any,
) -> FurnitureItem:
    """Generate a parametric table (dining, conference, coffee).

    ADA §902 requires accessible tables to have knee clearance of at least
    686 mm (27 in) height and 483 mm (19 in) depth on at least one side;
    the ADA clear-floor space at an accessible seat is 914 × 1219 mm.

    Parameters
    ----------
    name:
        Label for this table instance.
    width_mm:
        Table-top width.
    depth_mm:
        Table-top depth.
    height_mm:
        Table-top surface height above finished floor.
    seats:
        Nominal seating capacity.
    with_ada_clearance:
        If True, apply 914 mm clear-floor zones on all four sides.
    **metadata:
        Arbitrary keyword arguments stored in ``item.metadata``.

    Returns
    -------
    FurnitureItem
    """
    clearance = 914.0 if with_ada_clearance else 400.0
    meta = dict(metadata)
    meta.setdefault("seats", seats)
    return FurnitureItem(
        name=name,
        kind="table",
        width_mm=width_mm,
        depth_mm=depth_mm,
        height_mm=height_mm,
        seat_height_mm=None,
        clearance_front_mm=clearance,
        clearance_back_mm=clearance,
        clearance_left_mm=clearance,
        clearance_right_mm=clearance,
        metadata=meta,
    )
