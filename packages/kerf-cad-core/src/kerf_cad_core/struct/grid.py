"""
kerf_cad_core.struct.grid — structural grid axes and floor levels.

Grid convention
---------------
* X-direction (columns left→right): axes named with letters A, B, C, …
  spacing_x is a list of bay widths [d_AB, d_BC, …] in mm.
* Y-direction (rows front→back): axes numbered 1, 2, 3, …
  spacing_y is a list of bay depths [d_12, d_23, …] in mm.
* Origin (A/1 intersection) is at (0, 0, 0).

A grid intersection is addressed with a label like "B/3" meaning X-axis B,
Y-axis 3.  Letters are case-insensitive.

Level convention
----------------
* Each Level has a name ("Ground", "L1", "Roof", …) and an elevation (mm,
  measured from project datum at Z=0).
* Elevations may be negative (basement levels).

All data is immutable after construction (dataclass-like frozen objects).
No external dependencies.

Units: mm (all lengths and elevations).
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# GridPoint — resolved 3-D coordinate for a grid intersection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GridPoint:
    """A resolved (x, y) coordinate at a grid intersection label."""
    label: str          # e.g. "B/3"
    x_mm: float         # X-coordinate in mm (along X-grid axis)
    y_mm: float         # Y-coordinate in mm (along Y-grid axis)

    def at_level(self, elevation_mm: float) -> tuple[float, float, float]:
        """Return (x, y, z) with z = elevation_mm."""
        return (self.x_mm, self.y_mm, elevation_mm)


# ---------------------------------------------------------------------------
# StructGrid
# ---------------------------------------------------------------------------

_LETTERS = string.ascii_uppercase  # A … Z (26 axes maximum before multi-char)


def _label_to_x_index(label: str) -> Optional[int]:
    """Convert an X-axis label (A, B, … Z) to 0-based index. Case-insensitive."""
    label = label.strip().upper()
    if len(label) == 1 and label in _LETTERS:
        return _LETTERS.index(label)
    return None


def _y_label_to_index(label: str) -> Optional[int]:
    """Convert a Y-axis label ('1', '2', …) to 0-based index."""
    try:
        n = int(label.strip())
        if n >= 1:
            return n - 1
    except ValueError:
        pass
    return None


_GRID_LABEL_RE = re.compile(r"^([A-Za-z]+)\s*/\s*(\d+)$")


@dataclass
class StructGrid:
    """
    Parametric structural grid.

    Parameters
    ----------
    spacing_x:
        List of bay widths in X (mm). The number of X-axes = len(spacing_x) + 1.
        Example: [6000, 8000, 6000] → axes A, B, C, D at x = 0, 6000, 14000, 20000.
    spacing_y:
        List of bay depths in Y (mm). The number of Y-axes = len(spacing_y) + 1.
        Example: [5000, 5000] → axes 1, 2, 3 at y = 0, 5000, 10000.
    name:
        Optional project / grid set name.
    """

    spacing_x: list[float]
    spacing_y: list[float]
    name: str = ""

    # Derived cumulative coordinates (built in __post_init__)
    _x_coords: list[float] = field(default_factory=list, init=False, repr=False)
    _y_coords: list[float] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.spacing_x:
            raise ValueError("spacing_x must contain at least one bay width")
        if not self.spacing_y:
            raise ValueError("spacing_y must contain at least one bay depth")
        for i, s in enumerate(self.spacing_x):
            if s <= 0:
                raise ValueError(f"spacing_x[{i}] must be > 0; got {s}")
        for i, s in enumerate(self.spacing_y):
            if s <= 0:
                raise ValueError(f"spacing_y[{i}] must be > 0; got {s}")

        # Build cumulative coordinates
        xs = [0.0]
        for s in self.spacing_x:
            xs.append(xs[-1] + float(s))
        object.__setattr__(self, "_x_coords", xs) if hasattr(type(self), "__dataclass_fields__") else None
        self._x_coords = xs

        ys = [0.0]
        for s in self.spacing_y:
            ys.append(ys[-1] + float(s))
        self._y_coords = ys

    @property
    def x_axis_labels(self) -> list[str]:
        """Return X-axis labels (A, B, C, …)."""
        count = len(self.spacing_x) + 1
        if count > 26:
            raise ValueError(f"Too many X-axes ({count}); maximum 26 (A–Z)")
        return list(_LETTERS[:count])

    @property
    def y_axis_labels(self) -> list[str]:
        """Return Y-axis labels ('1', '2', '3', …)."""
        return [str(i + 1) for i in range(len(self.spacing_y) + 1)]

    def resolve(self, label: str) -> tuple[bool, Optional[GridPoint], Optional[str]]:
        """
        Resolve a grid label like "B/3" to a GridPoint.

        Returns
        -------
        (ok, grid_point, error_message)
        ok == False with error_message set on failure.
        """
        m = _GRID_LABEL_RE.match(label.strip())
        if not m:
            return False, None, (
                f"Invalid grid label '{label}'. "
                "Expected format 'X/Y' where X is a letter (A, B, …) "
                "and Y is a number (1, 2, …).  Example: 'B/3'."
            )

        x_part, y_part = m.group(1), m.group(2)

        xi = _label_to_x_index(x_part)
        if xi is None:
            return False, None, f"X-axis label '{x_part}' is not a valid letter"
        max_xi = len(self.spacing_x)
        if xi > max_xi:
            valid = self.x_axis_labels
            return False, None, (
                f"X-axis '{x_part}' is out of range for this grid "
                f"(valid: {valid})"
            )

        yi = _y_label_to_index(y_part)
        if yi is None:
            return False, None, f"Y-axis label '{y_part}' is not a valid number"
        max_yi = len(self.spacing_y)
        if yi > max_yi:
            valid = self.y_axis_labels
            return False, None, (
                f"Y-axis '{y_part}' is out of range for this grid "
                f"(valid: {valid})"
            )

        canonical = f"{x_part.upper()}/{y_part}"
        pt = GridPoint(
            label=canonical,
            x_mm=self._x_coords[xi],
            y_mm=self._y_coords[yi],
        )
        return True, pt, None

    def all_intersections(self) -> list[GridPoint]:
        """Return GridPoint for every intersection in the grid."""
        pts = []
        for xi, xlab in enumerate(self.x_axis_labels):
            for yi, ylab in enumerate(self.y_axis_labels):
                label = f"{xlab}/{ylab}"
                pts.append(GridPoint(
                    label=label,
                    x_mm=self._x_coords[xi],
                    y_mm=self._y_coords[yi],
                ))
        return pts

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "spacing_x": list(self.spacing_x),
            "spacing_y": list(self.spacing_y),
            "x_axes": self.x_axis_labels,
            "y_axes": self.y_axis_labels,
            "x_coords_mm": list(self._x_coords),
            "y_coords_mm": list(self._y_coords),
        }


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Level:
    """
    A floor / storey level at a fixed elevation above the project datum.

    Parameters
    ----------
    name:
        Human-readable name, e.g. "Ground", "L1", "L2", "Mezzanine", "Roof".
    elevation_mm:
        Elevation in mm measured from the project datum (Z = 0).
        Negative values for basements are permitted.
    """

    name: str
    elevation_mm: float

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Level name must be a non-empty string")

    def to_dict(self) -> dict:
        return {"name": self.name, "elevation_mm": self.elevation_mm}
