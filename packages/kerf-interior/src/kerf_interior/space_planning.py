"""
Space planning: RoomLayout with placed FF&E, circulation paths, and ADA auditing.

Coordinate system
-----------------
- Origin (0, 0) is the front-left interior corner of the room.
- X is the room width direction (left → right).
- Y is the room depth direction (front → back).
- All dimensions are in millimetres.

Circulation paths
-----------------
A ``CirculationPath`` connects two points and has a required clear width.
``RoomLayout.audit_circulation()`` checks that each path's declared width
meets the ADA minimum (914 mm / 36 in) and reports violations.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from kerf_interior.clearance import (
    ADAViolation,
    MIN_CORRIDOR_WIDTH_MM,
    audit_clearances,
    check_corridor_clearance,
    check_knee_clearance,
    check_reach_range,
    check_turning_radius,
    turning_circle_diameter_mm,
)
from kerf_interior.furniture import FurnitureItem


# ---------------------------------------------------------------------------
# Circulation path
# ---------------------------------------------------------------------------

@dataclass
class CirculationPath:
    """A named corridor or passage through the room.

    Attributes
    ----------
    name:
        Human-readable label (e.g. ``"Main aisle"``, ``"Exit path"``).
    start:
        ``(x, y)`` start point in mm.
    end:
        ``(x, y)`` end point in mm.
    clear_width_mm:
        Available clear width of the passage in mm.
    required_width_mm:
        Required clear width (default: ADA minimum 914 mm).
    """
    name: str
    start: tuple[float, float]
    end: tuple[float, float]
    clear_width_mm: float
    required_width_mm: float = MIN_CORRIDOR_WIDTH_MM

    @property
    def length_mm(self) -> float:
        """Euclidean length of the path centreline in mm."""
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        return math.sqrt(dx * dx + dy * dy)

    def check(self) -> list[ADAViolation]:
        """Return ADA violations for this path's clear width."""
        return check_corridor_clearance(
            self.clear_width_mm,
        )


# ---------------------------------------------------------------------------
# Placed item wrapper
# ---------------------------------------------------------------------------

@dataclass
class PlacedItem:
    """A ``FurnitureItem`` placed at a specific location in a room.

    Attributes
    ----------
    item:
        The FF&E piece.
    x_mm:
        X coordinate of the front-left corner in mm.
    y_mm:
        Y coordinate of the front-left corner in mm.
    rotation_deg:
        Counter-clockwise rotation about the vertical axis in degrees.
    label:
        Optional override label for the placed instance.
    """
    item: FurnitureItem
    x_mm: float
    y_mm: float
    rotation_deg: float = 0.0
    label: str | None = None

    @property
    def display_name(self) -> str:
        return self.label or self.item.name

    @property
    def bounding_box(self) -> tuple[float, float, float, float]:
        """``(x_min, y_min, x_max, y_max)`` of the item footprint in mm.

        Note: only axis-aligned (rotation_deg == 0) bounding boxes are
        returned; rotation is recorded but AABB expansion is not yet
        implemented.
        """
        return (
            self.x_mm,
            self.y_mm,
            self.x_mm + self.item.width_mm,
            self.y_mm + self.item.depth_mm,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item.to_dict(),
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "rotation_deg": self.rotation_deg,
            "label": self.label,
        }


# ---------------------------------------------------------------------------
# Room layout
# ---------------------------------------------------------------------------

@dataclass
class RoomLayout:
    """A rectangular room with placed FF&E and circulation paths.

    Attributes
    ----------
    name:
        Room name (e.g. ``"Conference Room A"``).
    width_mm:
        Interior room width (X direction) in mm.
    depth_mm:
        Interior room depth (Y direction) in mm.
    ceiling_height_mm:
        Interior ceiling height in mm.
    items:
        List of placed FF&E items.
    circulation_paths:
        Named circulation corridors / aisles.
    metadata:
        Arbitrary extra data.
    """
    name: str
    width_mm: float
    depth_mm: float
    ceiling_height_mm: float = 2700.0
    items: list[PlacedItem] = field(default_factory=list)
    circulation_paths: list[CirculationPath] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    @property
    def area_m2(self) -> float:
        """Room floor area in square metres."""
        return (self.width_mm / 1000.0) * (self.depth_mm / 1000.0)

    @property
    def perimeter_mm(self) -> float:
        """Interior perimeter in mm."""
        return 2 * (self.width_mm + self.depth_mm)

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------

    def place(
        self,
        item: FurnitureItem,
        x_mm: float,
        y_mm: float,
        *,
        rotation_deg: float = 0.0,
        label: str | None = None,
    ) -> PlacedItem:
        """Place a furniture item in the room and return the PlacedItem.

        Parameters
        ----------
        item:
            FF&E piece to place.
        x_mm:
            X position of the front-left corner.
        y_mm:
            Y position of the front-left corner.
        rotation_deg:
            Counter-clockwise rotation in degrees.
        label:
            Optional display label override.

        Returns
        -------
        PlacedItem
        """
        placed = PlacedItem(
            item=item,
            x_mm=x_mm,
            y_mm=y_mm,
            rotation_deg=rotation_deg,
            label=label,
        )
        self.items.append(placed)
        return placed

    def add_circulation_path(
        self,
        name: str,
        start: tuple[float, float],
        end: tuple[float, float],
        clear_width_mm: float,
        *,
        required_width_mm: float = MIN_CORRIDOR_WIDTH_MM,
    ) -> CirculationPath:
        """Add a circulation path to the room.

        Parameters
        ----------
        name:
            Label for the path.
        start:
            ``(x, y)`` start coordinates in mm.
        end:
            ``(x, y)`` end coordinates in mm.
        clear_width_mm:
            Available clear width of the passage.
        required_width_mm:
            Minimum required clear width (default ADA 914 mm).

        Returns
        -------
        CirculationPath
        """
        path = CirculationPath(
            name=name,
            start=start,
            end=end,
            clear_width_mm=clear_width_mm,
            required_width_mm=required_width_mm,
        )
        self.circulation_paths.append(path)
        return path

    # ------------------------------------------------------------------
    # ADA auditing
    # ------------------------------------------------------------------

    def audit_circulation(self) -> list[ADAViolation]:
        """Check all circulation paths for ADA compliance.

        Returns
        -------
        list[ADAViolation]
            All violations found across all paths.
        """
        violations: list[ADAViolation] = []
        for path in self.circulation_paths:
            violations.extend(path.check())
        return violations

    def audit_furniture_clearances(self) -> list[ADAViolation]:
        """Check placed FF&E for ADA knee-clearance (desks/tables) compliance.

        Returns
        -------
        list[ADAViolation]
        """
        violations: list[ADAViolation] = []
        for placed in self.items:
            item = placed.item
            if item.kind in ("desk", "table"):
                kh = item.metadata.get("knee_clearance_height_mm")
                kd = item.metadata.get("knee_clearance_depth_mm")
                if kh is not None and kd is not None:
                    violations.extend(check_knee_clearance(kh, kd))
        return violations

    def audit_reach_ranges(
        self, reach_heights_mm: Sequence[float]
    ) -> list[ADAViolation]:
        """Check a list of control/switch heights against ADA reach ranges.

        Parameters
        ----------
        reach_heights_mm:
            Heights of controls/outlets/switches above finished floor.

        Returns
        -------
        list[ADAViolation]
        """
        violations: list[ADAViolation] = []
        for height in reach_heights_mm:
            violations.extend(check_reach_range(height))
        return violations

    def audit_all(
        self,
        *,
        turning_diameter_mm: float | None = None,
        reach_heights_mm: Sequence[float] = (),
    ) -> list[ADAViolation]:
        """Run a full ADA audit of the room.

        Parameters
        ----------
        turning_diameter_mm:
            If provided, also checks this clear-floor turning diameter.
        reach_heights_mm:
            Heights of controls to check for reach range.

        Returns
        -------
        list[ADAViolation]
        """
        violations = self.audit_circulation()
        violations.extend(self.audit_furniture_clearances())
        violations.extend(self.audit_reach_ranges(reach_heights_mm))

        if turning_diameter_mm is not None:
            violations.extend(check_turning_radius(turning_diameter_mm))

        return violations

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a plain-dict summary of the room layout."""
        violations = self.audit_all()
        return {
            "name": self.name,
            "width_mm": self.width_mm,
            "depth_mm": self.depth_mm,
            "ceiling_height_mm": self.ceiling_height_mm,
            "area_m2": round(self.area_m2, 3),
            "item_count": len(self.items),
            "circulation_path_count": len(self.circulation_paths),
            "ada_violations": len(violations),
            "violations": [
                {
                    "rule": v.rule,
                    "actual_mm": round(v.actual_mm, 1),
                    "limit_mm": round(v.limit_mm, 1),
                    "message": v.message,
                }
                for v in violations
            ],
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_room(
    name: str,
    width_mm: float,
    depth_mm: float,
    *,
    ceiling_height_mm: float = 2700.0,
    **metadata: Any,
) -> RoomLayout:
    """Create an empty ``RoomLayout``.

    Parameters
    ----------
    name:
        Room name.
    width_mm:
        Interior room width in mm.
    depth_mm:
        Interior room depth in mm.
    ceiling_height_mm:
        Interior ceiling height in mm (default 2700 mm / ~8'10").
    **metadata:
        Arbitrary keyword arguments stored in ``layout.metadata``.

    Returns
    -------
    RoomLayout
    """
    return RoomLayout(
        name=name,
        width_mm=width_mm,
        depth_mm=depth_mm,
        ceiling_height_mm=ceiling_height_mm,
        metadata=dict(metadata),
    )
