"""
kerf_bim.openings — Full parametric door / window model (T-111).

Promotes the basic opening primitive to fully parametric door and window
types with frame hardware, glazing configurations, and IFC export.

Reference
---------
Autodesk Revit 2024 — Door / Window Family parameters.
ISO 16739-1:2018 — ``IfcDoor``, ``IfcWindow``, ``IfcDoorType``,
``IfcWindowType``, ``IfcMaterialLayerSet``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

__all__ = [
    # Door
    "DoorOperation",
    "DoorType",
    "DoorInstance",
    "make_door_type",
    "make_door_instance",
    "door_to_ifc_dict",
    # Window
    "WindowOperation",
    "WindowType",
    "WindowInstance",
    "make_window_type",
    "make_window_instance",
    "window_to_ifc_dict",
    # Presets
    "PRESET_DOOR_TYPES",
    "PRESET_WINDOW_TYPES",
    "OpeningValidationError",
]


class OpeningValidationError(ValueError):
    """Raised on invalid opening configuration."""


# ---------------------------------------------------------------------------
# Door
# ---------------------------------------------------------------------------

DoorOperation = Literal[
    "single_swing",
    "double_swing",
    "sliding",
    "bifold",
    "pocket",
    "overhead_sectional",
    "revolving",
]

VALID_DOOR_OPERATIONS = frozenset({
    "single_swing", "double_swing", "sliding", "bifold",
    "pocket", "overhead_sectional", "revolving",
})


@dataclass
class DoorType:
    """Parametric door type definition.

    Parameters
    ----------
    name:
        Type name (e.g. ``"Single Swing - 3-0 × 6-8"``).
    operation:
        Opening operation type (see :data:`DoorOperation`).
    width:
        Clear opening width in mm.
    height:
        Clear opening height in mm.
    panel_thickness:
        Door leaf thickness in mm.
    frame_width:
        Frame / casing width in mm (returned face of frame).
    frame_depth:
        Frame depth into wall (mm) — must be ≤ wall thickness at placement.
    lite_pattern:
        Glazing lite pattern: ``none``, ``half``, ``full``, ``sidelite``.
    fire_rating:
        Fire-door rating string (e.g. ``"60 min"``), or empty string.
    panel_material:
        Material id for the door leaf.
    frame_material:
        Material id for the door frame.
    hardware_set:
        Hardware set description (e.g. ``"lever_handle_lockset"``).
    """
    name: str
    operation: DoorOperation = "single_swing"
    width: float = 914.4          # mm (3-0)
    height: float = 2032.0        # mm (6-8)
    panel_thickness: float = 44.5  # mm
    frame_width: float = 70.0     # mm
    frame_depth: float = 140.0    # mm
    lite_pattern: str = "none"
    fire_rating: str = ""
    panel_material: str = "solid_wood"
    frame_material: str = "timber_doug_fir"
    hardware_set: str = "lever_handle_lockset"

    def __post_init__(self) -> None:
        if not self.name:
            raise OpeningValidationError("DoorType name must be non-empty")
        if self.operation not in VALID_DOOR_OPERATIONS:
            raise OpeningValidationError(
                f"Unknown door operation '{self.operation}'; "
                f"allowed: {sorted(VALID_DOOR_OPERATIONS)}"
            )
        if self.width <= 0 or self.height <= 0:
            raise OpeningValidationError("Door width and height must be > 0")

    @property
    def rough_opening_width(self) -> float:
        """Rough opening width including frame (mm)."""
        return self.width + 2 * self.frame_width

    @property
    def rough_opening_height(self) -> float:
        """Rough opening height including frame (mm)."""
        return self.height + self.frame_width  # frame at head, sill at floor


@dataclass
class DoorInstance:
    """A placed door instance.

    Parameters
    ----------
    door_type:
        The :class:`DoorType` applied to this instance.
    wall_level:
        Level name of the host wall.
    position:
        ``[x, y, z]`` position in mm — typically the rough-opening centre.
    hand:
        Handedness: ``"left"`` or ``"right"`` (hinge side from outside).
    fire_rated:
        Override the type's fire_rating for this instance.
    name:
        Optional instance name.
    """
    door_type: DoorType
    wall_level: str = "L1"
    position: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    hand: Literal["left", "right"] = "right"
    fire_rated: bool = False
    name: str = ""

    def __post_init__(self) -> None:
        if len(self.position) < 3:
            self.position = list(self.position) + [0.0] * (3 - len(self.position))
        if self.hand not in ("left", "right"):
            raise OpeningValidationError(f"hand must be 'left' or 'right', got '{self.hand}'")
        if not self.name:
            self.name = f"Door ({self.door_type.name})"


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------

WindowOperation = Literal[
    "fixed",
    "casement",
    "awning",
    "double_hung",
    "single_hung",
    "sliding",
    "hopper",
    "jalousie",
]

VALID_WINDOW_OPERATIONS = frozenset({
    "fixed", "casement", "awning", "double_hung", "single_hung",
    "sliding", "hopper", "jalousie",
})


@dataclass
class WindowType:
    """Parametric window type definition.

    Parameters
    ----------
    name:
        Type name (e.g. ``"Fixed - 1200 × 1500"``).
    operation:
        Opening operation (see :data:`WindowOperation`).
    width:
        Rough opening width in mm.
    height:
        Rough opening height in mm.
    frame_width:
        Visible frame width in mm.
    frame_depth:
        Frame depth into wall (mm).
    glazing_type:
        Glazing specification: ``"single"``, ``"double_IGU"``, ``"triple_IGU"``.
    u_value:
        Whole-window U-value in W/(m²·K).  ``None`` if not known.
    shgc:
        Solar heat gain coefficient (0–1).  ``None`` if not known.
    frame_material:
        Material id for the window frame.
    """
    name: str
    operation: WindowOperation = "fixed"
    width: float = 1200.0        # mm
    height: float = 1500.0       # mm
    frame_width: float = 65.0    # mm
    frame_depth: float = 120.0   # mm
    glazing_type: str = "double_IGU"
    u_value: Optional[float] = None   # W/(m²·K)
    shgc: Optional[float] = None
    frame_material: str = "aluminum_6061_t6"

    def __post_init__(self) -> None:
        if not self.name:
            raise OpeningValidationError("WindowType name must be non-empty")
        if self.operation not in VALID_WINDOW_OPERATIONS:
            raise OpeningValidationError(
                f"Unknown window operation '{self.operation}'; "
                f"allowed: {sorted(VALID_WINDOW_OPERATIONS)}"
            )
        if self.width <= 0 or self.height <= 0:
            raise OpeningValidationError("Window width and height must be > 0")
        if self.u_value is not None and self.u_value < 0:
            raise OpeningValidationError("u_value must be ≥ 0")
        if self.shgc is not None and not (0.0 <= self.shgc <= 1.0):
            raise OpeningValidationError("shgc must be in [0, 1]")

    @property
    def clear_opening_width(self) -> float:
        """Clear day-light opening width (mm) = width - 2*frame_width."""
        return max(0.0, self.width - 2 * self.frame_width)

    @property
    def clear_opening_height(self) -> float:
        """Clear day-light opening height (mm) = height - 2*frame_width."""
        return max(0.0, self.height - 2 * self.frame_width)


@dataclass
class WindowInstance:
    """A placed window instance.

    Parameters
    ----------
    window_type:
        The :class:`WindowType` applied.
    wall_level:
        Level name of the host wall.
    position:
        ``[x, y, z]`` position (mm).  z is sill height above floor.
    name:
        Optional instance name.
    """
    window_type: WindowType
    wall_level: str = "L1"
    position: List[float] = field(default_factory=lambda: [0.0, 0.0, 900.0])
    name: str = ""

    def __post_init__(self) -> None:
        if len(self.position) < 3:
            self.position = list(self.position) + [0.0] * (3 - len(self.position))
        if not self.name:
            self.name = f"Window ({self.window_type.name})"


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_door_type(
    name: str,
    operation: DoorOperation = "single_swing",
    width: float = 914.4,
    height: float = 2032.0,
    **kwargs,
) -> DoorType:
    """Create a :class:`DoorType` ergonomically."""
    return DoorType(name=name, operation=operation, width=width, height=height, **kwargs)


def make_door_instance(
    door_type: DoorType,
    position: List[float],
    wall_level: str = "L1",
    hand: Literal["left", "right"] = "right",
    name: str = "",
) -> DoorInstance:
    """Create a :class:`DoorInstance` ergonomically."""
    return DoorInstance(
        door_type=door_type,
        wall_level=wall_level,
        position=list(position),
        hand=hand,
        name=name,
    )


def make_window_type(
    name: str,
    operation: WindowOperation = "fixed",
    width: float = 1200.0,
    height: float = 1500.0,
    **kwargs,
) -> WindowType:
    """Create a :class:`WindowType` ergonomically."""
    return WindowType(name=name, operation=operation, width=width, height=height, **kwargs)


def make_window_instance(
    window_type: WindowType,
    position: List[float],
    wall_level: str = "L1",
    name: str = "",
) -> WindowInstance:
    """Create a :class:`WindowInstance` ergonomically."""
    return WindowInstance(
        window_type=window_type,
        wall_level=wall_level,
        position=list(position),
        name=name,
    )


# ---------------------------------------------------------------------------
# IFC dict serialisation
# ---------------------------------------------------------------------------

def door_to_ifc_dict(instance: DoorInstance) -> dict:
    """Convert a :class:`DoorInstance` to the IFC dict format for the exporter.

    Compatible with the ``openings`` list in the model dict accepted by
    :func:`kerf_bim.export_ifc.writer.export_ifc`.
    """
    return {
        "kind":       "door",
        "level":      instance.wall_level,
        "position":   list(instance.position),
        "width":      instance.door_type.width,
        "height":     instance.door_type.height,
        "name":       instance.name,
        # Extra parametric metadata (informational for renderer / schedules)
        "operation":  instance.door_type.operation,
        "hand":       instance.hand,
        "panel_material": instance.door_type.panel_material,
        "frame_material": instance.door_type.frame_material,
        "lite_pattern":   instance.door_type.lite_pattern,
        "fire_rating":    instance.door_type.fire_rating,
        "hardware_set":   instance.door_type.hardware_set,
    }


def window_to_ifc_dict(instance: WindowInstance) -> dict:
    """Convert a :class:`WindowInstance` to the IFC dict format for the exporter."""
    return {
        "kind":       "window",
        "level":      instance.wall_level,
        "position":   list(instance.position),
        "width":      instance.window_type.width,
        "height":     instance.window_type.height,
        "name":       instance.name,
        # Extra parametric metadata
        "operation":    instance.window_type.operation,
        "glazing_type": instance.window_type.glazing_type,
        "frame_material": instance.window_type.frame_material,
        "u_value":      instance.window_type.u_value,
        "shgc":         instance.window_type.shgc,
    }


# ---------------------------------------------------------------------------
# Preset door and window types
# ---------------------------------------------------------------------------

def _preset_doors() -> dict[str, DoorType]:
    d: dict[str, DoorType] = {}

    def add(dt: DoorType) -> None:
        d[dt.name] = dt

    add(make_door_type("Single Swing - 2-6 × 6-8",  width=762.0,  height=2032.0))
    add(make_door_type("Single Swing - 2-8 × 6-8",  width=812.8,  height=2032.0))
    add(make_door_type("Single Swing - 3-0 × 6-8",  width=914.4,  height=2032.0))
    add(make_door_type("Single Swing - 3-0 × 7-0",  width=914.4,  height=2133.6))
    add(make_door_type("Double Swing - 6-0 × 6-8",  operation="double_swing", width=1828.8, height=2032.0))
    add(make_door_type("Sliding - 6-0 × 7-0",       operation="sliding",       width=1828.8, height=2133.6))
    add(make_door_type("Garage - 8-0 × 7-0",        operation="overhead_sectional", width=2438.4, height=2133.6))
    # Metric
    add(make_door_type("Single Swing - 800 × 2100",  width=800.0,  height=2100.0))
    add(make_door_type("Single Swing - 900 × 2100",  width=900.0,  height=2100.0))
    add(make_door_type("Single Swing - 1000 × 2100", width=1000.0, height=2100.0))
    # Fire-rated
    add(make_door_type("Fire Door - 900 × 2100 - 60min",
                       width=900.0, height=2100.0,
                       fire_rating="60 min",
                       panel_material="steel_a36",
                       frame_material="steel_a36"))

    return d


def _preset_windows() -> dict[str, WindowType]:
    w: dict[str, WindowType] = {}

    def add(wt: WindowType) -> None:
        w[wt.name] = wt

    add(make_window_type("Fixed - 600 × 1200",    operation="fixed",       width=600.0,  height=1200.0))
    add(make_window_type("Fixed - 1200 × 1500",   operation="fixed",       width=1200.0, height=1500.0))
    add(make_window_type("Casement - 600 × 1200", operation="casement",    width=600.0,  height=1200.0))
    add(make_window_type("Casement - 900 × 1500", operation="casement",    width=900.0,  height=1500.0))
    add(make_window_type("Double Hung - 3-0 × 5-0",
                         operation="double_hung",
                         width=914.4, height=1524.0, frame_material="timber_doug_fir"))
    add(make_window_type("Awning - 1200 × 600",   operation="awning",      width=1200.0, height=600.0))
    add(make_window_type("Sliding - 1800 × 1200", operation="sliding",     width=1800.0, height=1200.0))
    add(make_window_type("Fixed - 2400 × 1800 Triple IGU",
                         operation="fixed", width=2400.0, height=1800.0,
                         glazing_type="triple_IGU", u_value=0.7, shgc=0.32))

    return w


PRESET_DOOR_TYPES: dict[str, DoorType] = _preset_doors()
PRESET_WINDOW_TYPES: dict[str, WindowType] = _preset_windows()
