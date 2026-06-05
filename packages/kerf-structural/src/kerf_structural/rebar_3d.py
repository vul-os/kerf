"""
3D rebar placement and bending schedule engine.

Covers:
- 3D bar placement inside concrete member solids (beams, columns, slabs)
  longitudinal bars + stirrups/ties at spacing, cover offset from member faces
- BS 8666:2020 standard bar bend shapes (shape codes 00–99 subset)
  with cut length formula per shape code
- Bar-bending schedule generation (mark, shape code, bar size, length, count,
  total mass)

Units: metric SI throughout (mm, kg/m).
Bar sizes reference UK standard diameters per BS 4449:2005.

References
----------
BS 8666:2020  "Specification for scheduling, dimensioning, bending and cutting of steel
              reinforcement for concrete"
ACI 315-99    "Details and Detailing of Concrete Reinforcement" (US reference)
SABS 82:2019  "Bending dimensions and scheduling of steel bars for concrete
              reinforcement" (South Africa)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Bar size tables
# ---------------------------------------------------------------------------

# BS 4449 / BS 8666 nominal diameters (mm) → (area mm², mass kg/m)
_BS_BAR_TABLE: dict[int, tuple[float, float]] = {
    6:  (28.3,  0.222),
    8:  (50.3,  0.395),
    10: (78.5,  0.616),
    12: (113.1, 0.888),
    16: (201.1, 1.579),
    20: (314.2, 2.466),
    25: (490.9, 3.854),
    32: (804.2, 6.313),
    40: (1256.6, 9.864),
    50: (1963.5, 15.413),
}

# ACI bar-mark → diameter mm (for US bar marks used with ACI shapes)
_ACI_BAR_DIAMETER_MM: dict[int, float] = {
    3:  9.525,
    4:  12.700,
    5:  15.875,
    6:  19.050,
    7:  22.225,
    8:  25.400,
    9:  28.651,
    10: 32.258,
    11: 35.814,
    14: 43.002,
    18: 57.328,
}


@dataclass
class BarProperties:
    """Resolved properties for a reinforcing bar."""
    diameter_mm: float    # nominal diameter (mm)
    area_mm2: float       # nominal area (mm²)
    mass_kg_per_m: float  # mass (kg/m)


def bs_bar_properties(diameter_mm: int) -> BarProperties:
    """Return BS 4449 bar properties for a given nominal diameter (mm)."""
    if diameter_mm not in _BS_BAR_TABLE:
        raise ValueError(
            f"Bar diameter {diameter_mm} mm not in BS table. "
            f"Valid: {sorted(_BS_BAR_TABLE)}"
        )
    area, mass = _BS_BAR_TABLE[diameter_mm]
    return BarProperties(diameter_mm=float(diameter_mm), area_mm2=area, mass_kg_per_m=mass)


# ---------------------------------------------------------------------------
# BS 8666:2020 bend shape codes + cut length
# ---------------------------------------------------------------------------

# Standard bend radii (BS 8666 Table 2) — minimum r = 2*d for d <= 16 mm,
# 3.5*d for d = 20/25 mm, 4*d for d >= 32 mm
def _min_bend_radius(d: float) -> float:
    """Minimum mandrel radius r (mm) per BS 8666:2020 Table 2."""
    if d <= 16.0:
        return 2.0 * d
    elif d <= 25.0:
        return 3.5 * d
    else:
        return 4.0 * d


def _hook_allowance(d: float, angle_deg: float = 180.0) -> float:
    """
    Hook/bend allowance Δ (mm) per BS 8666:2020.

    For a standard hook: Δ = (π/2)(r + d/2) where r is the mandrel radius.
    For 135° hooks:      Δ = (3π/8)(r + d/2)
    For 90° bends:       Δ = (π/4)(r + d/2)
    """
    r = _min_bend_radius(d)
    angle_rad = math.radians(angle_deg)
    # Straight extension beyond tangent point is included in measured dimensions
    return angle_rad * (r + d / 2.0)


# Shape code registry: code → (description, cut_length_fn)
# cut_length_fn(dims: dict, d: float) -> float (all mm)
# dims keys depend on shape code — documented per shape.

def _shape_00_cut_length(dims: dict, d: float) -> float:
    """Shape 00: straight bar. Cut length = A."""
    return dims["A"]


def _shape_11_cut_length(dims: dict, d: float) -> float:
    """Shape 11: straight + 180° hook one end. L = A + 0.5B - d (BS 8666 Table 3)."""
    A = dims["A"]
    B = dims.get("B", _min_bend_radius(d) * 2 + d * 5)  # default tail
    return A + 0.5 * B - d


def _shape_12_cut_length(dims: dict, d: float) -> float:
    """Shape 12: 180° hooks both ends. L = A + B - 2d."""
    A = dims["A"]
    B = dims.get("B", _min_bend_radius(d) * 2 + d * 5)
    return A + B - 2.0 * d


def _shape_13_cut_length(dims: dict, d: float) -> float:
    """
    Shape 13: straight + 90° bend one end.
    L = A + B - 0.5r - d
    where r = min bend radius.
    """
    A = dims["A"]
    B = dims["B"]
    r = _min_bend_radius(d)
    return A + B - 0.5 * r - d


def _shape_21_cut_length(dims: dict, d: float) -> float:
    """Shape 21: L-shape (two legs, 90° bend). L = A + B - 0.5r - d."""
    return _shape_13_cut_length(dims, d)


def _shape_22_cut_length(dims: dict, d: float) -> float:
    """Shape 22: Z-shape (two 90° bends, same direction). L = A + B + C - r - 2d."""
    A = dims["A"]
    B = dims["B"]
    C = dims["C"]
    r = _min_bend_radius(d)
    return A + B + C - r - 2.0 * d


def _shape_25_cut_length(dims: dict, d: float) -> float:
    """
    Shape 25: Closed rectangular stirrup (4 bends, one hook).
    L = 2(A + B) + hook_allowance (BS 8666 Table 3 — rectangular link formula).
    Perimeter + 1 standard hook tail (10d or min 75mm).
    """
    A = dims["A"]
    B = dims["B"]
    r = _min_bend_radius(d)
    # 4 × 90° bend allowances
    bend_allow = 4 * (r + d / 2.0) * (math.pi / 2.0)
    # One standard hook (135° per BS 8666 for links): (3π/8)(r + d/2) + straight tail
    hook = (3.0 * math.pi / 8.0) * (r + d / 2.0) + max(10.0 * d, 75.0)
    return 2.0 * (A + B) + bend_allow + hook


def _shape_26_cut_length(dims: dict, d: float) -> float:
    """
    Shape 26: Closed rectangular stirrup with two 135° hooks.
    L = 2(A + B) + 4×bend_allow + 2×hook_allow
    """
    A = dims["A"]
    B = dims["B"]
    r = _min_bend_radius(d)
    bend_allow = 4 * (r + d / 2.0) * (math.pi / 2.0)
    hook_allow = 2 * ((3.0 * math.pi / 8.0) * (r + d / 2.0) + max(10.0 * d, 75.0))
    return 2.0 * (A + B) + bend_allow + hook_allow


def _shape_31_cut_length(dims: dict, d: float) -> float:
    """Shape 31: U-bar (two 90° bends). L = A + 2B - r - 2d."""
    A = dims["A"]
    B = dims["B"]
    r = _min_bend_radius(d)
    return A + 2.0 * B - r - 2.0 * d


def _shape_38_cut_length(dims: dict, d: float) -> float:
    """Shape 38: Cranked bar (two bends, offset). L = A + B + C + D - 2(0.5r + d)."""
    A = dims["A"]
    B = dims["B"]
    C = dims["C"]
    D = dims.get("D", 0.0)
    r = _min_bend_radius(d)
    return A + B + C + D - r - 2.0 * d


def _shape_41_cut_length(dims: dict, d: float) -> float:
    """Shape 41: T-head / spiral stop. Approximated as straight."""
    return dims["A"]


def _shape_51_cut_length(dims: dict, d: float) -> float:
    """Shape 51: Circular/spiral link. L = π × (A - d) + tail where tail = 12d."""
    A = dims["A"]  # mean diameter of circle
    tail = max(12.0 * d, 75.0)
    return math.pi * (A - d) + tail


# Registry
_SHAPE_CODES: dict[str, tuple[str, object]] = {
    "00": ("Straight bar",                       _shape_00_cut_length),
    "11": ("Straight + 180° hook one end",        _shape_11_cut_length),
    "12": ("180° hooks both ends",                _shape_12_cut_length),
    "13": ("Straight + 90° bend one end",         _shape_13_cut_length),
    "21": ("L-shape 90° bend",                   _shape_21_cut_length),
    "22": ("Z-shape two 90° bends same dir",     _shape_22_cut_length),
    "25": ("Closed rectangular stirrup (1 hook)", _shape_25_cut_length),
    "26": ("Closed rectangular stirrup (2 hooks)", _shape_26_cut_length),
    "31": ("U-bar two 90° bends",                _shape_31_cut_length),
    "38": ("Cranked bar",                        _shape_38_cut_length),
    "41": ("T-head / spiral stop",               _shape_41_cut_length),
    "51": ("Circular / spiral link",             _shape_51_cut_length),
}


def bar_cut_length(shape_code: str, dims: dict, diameter_mm: int) -> float:
    """
    Compute the cut (bending) length for a bar of given shape and dims.

    Parameters
    ----------
    shape_code : str
        BS 8666:2020 shape code (e.g. '00', '25', '38').
    dims : dict
        Dimension keys A, B, C, D (mm) as required by the shape code.
    diameter_mm : int
        Nominal bar diameter (mm).

    Returns
    -------
    float
        Cut length in mm, rounded to nearest mm.

    Raises
    ------
    ValueError
        If shape_code is not recognised.
    """
    if shape_code not in _SHAPE_CODES:
        raise ValueError(
            f"Unknown shape code '{shape_code}'. "
            f"Valid codes: {sorted(_SHAPE_CODES)}"
        )
    props = bs_bar_properties(diameter_mm)
    d = props.diameter_mm
    _, fn = _SHAPE_CODES[shape_code]
    return round(fn(dims, d), 1)


def shape_code_description(shape_code: str) -> str:
    """Return human-readable description for a shape code."""
    if shape_code not in _SHAPE_CODES:
        raise ValueError(f"Unknown shape code '{shape_code}'")
    return _SHAPE_CODES[shape_code][0]


# ---------------------------------------------------------------------------
# 3D bar placement inside a concrete member solid
# ---------------------------------------------------------------------------

@dataclass
class Point3:
    """Simple 3D point (mm)."""
    x: float
    y: float
    z: float

    def __add__(self, other: "Point3") -> "Point3":
        return Point3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Point3") -> "Point3":
        return Point3(self.x - other.x, self.y - other.y, self.z - other.z)

    def as_list(self) -> list:
        return [self.x, self.y, self.z]


@dataclass
class RebarInstance:
    """A single physical bar placed inside a member."""
    mark: str                # bar mark (schedule reference)
    shape_code: str          # BS 8666 shape code
    diameter_mm: int         # nominal diameter (mm)
    cut_length_mm: float     # cut length (mm)
    count: int               # number of identical bars in this instance
    dims: dict               # A, B, C, D as applicable (mm)
    # Placement centroid path (list of Point3 along bar centreline)
    centreline: list[Point3] = field(default_factory=list)
    role: str = "longitudinal"  # "longitudinal" | "stirrup" | "tie" | "link"

    @property
    def mass_kg(self) -> float:
        props = bs_bar_properties(self.diameter_mm)
        total_length_m = self.cut_length_mm / 1000.0 * self.count
        return round(total_length_m * props.mass_kg_per_m, 3)


@dataclass
class ConcreteSection:
    """Parameters for a rectangular concrete member cross-section."""
    width_mm: float    # section width (mm)
    depth_mm: float    # section depth (mm)
    length_mm: float   # member length along axis (mm)
    cover_mm: float    # clear cover to stirrup face (mm)

    @property
    def inner_width(self) -> float:
        return self.width_mm - 2.0 * self.cover_mm

    @property
    def inner_depth(self) -> float:
        return self.depth_mm - 2.0 * self.cover_mm


def place_longitudinal_bars(
    section: ConcreteSection,
    bar_diameter_mm: int,
    n_bars_bottom: int,
    n_bars_top: int,
    stirrup_diameter_mm: int,
    mark_prefix: str = "L",
) -> list[RebarInstance]:
    """
    Place longitudinal bars inside a rectangular concrete beam/column.

    Bars are arranged in a single layer at the top and bottom (beam mode).
    For columns, pass n_bars_bottom = n_bars_top = total_bars // 2.

    Parameters
    ----------
    section : ConcreteSection
        Member cross-section geometry.
    bar_diameter_mm : int
        Nominal diameter of longitudinal bars (mm).
    n_bars_bottom : int
        Number of bars in the bottom layer.
    n_bars_top : int
        Number of bars in the top layer.
    stirrup_diameter_mm : int
        Stirrup bar diameter — needed to compute cover offset (mm).
    mark_prefix : str
        Prefix for bar marks in the bending schedule.

    Returns
    -------
    list[RebarInstance]
        One RebarInstance per layer (bottom / top).
    """
    cv = section.cover_mm
    d_l = float(bar_diameter_mm)
    d_s = float(stirrup_diameter_mm)

    # Offset from outer face to centreline of longitudinal bar
    offset_to_bar_cl = cv + d_s + d_l / 2.0

    # Y positions (bottom-left origin, Z along member axis)
    y_bottom = offset_to_bar_cl                              # from bottom face
    y_top    = section.depth_mm - offset_to_bar_cl          # from bottom face

    results: list[RebarInstance] = []
    dims = {"A": section.length_mm}

    for layer_idx, (n_bars, y_pos, role_label) in enumerate([
        (n_bars_bottom, y_bottom, "bot"),
        (n_bars_top,    y_top,    "top"),
    ]):
        if n_bars <= 0:
            continue

        # Even spacing across inner width
        if n_bars == 1:
            x_positions = [section.width_mm / 2.0]
        else:
            spacing = section.inner_width / (n_bars - 1)
            x_positions = [
                section.cover_mm + d_s + d_l / 2.0 + i * spacing
                for i in range(n_bars)
            ]

        # Build centreline path (straight bar: two endpoints)
        centreline = [
            Point3(x_positions[0], y_pos, 0.0),
            Point3(x_positions[-1], y_pos, section.length_mm),
        ]

        cut_len = bar_cut_length("00", dims, bar_diameter_mm)
        mark = f"{mark_prefix}{layer_idx + 1}"

        results.append(RebarInstance(
            mark=mark,
            shape_code="00",
            diameter_mm=bar_diameter_mm,
            cut_length_mm=cut_len,
            count=n_bars,
            dims=dims.copy(),
            centreline=centreline,
            role="longitudinal",
        ))

    return results


def place_stirrups(
    section: ConcreteSection,
    stirrup_diameter_mm: int,
    spacing_mm: float,
    mark_prefix: str = "S",
    shape_code: str = "25",
) -> list[RebarInstance]:
    """
    Place rectangular closed stirrups at regular spacing along a beam/column.

    Spacing zones: full-member-length at uniform spacing (simplified).
    Production-grade would have 2/3 spacing near ends — use this as the
    standard zone spacing input.

    Parameters
    ----------
    section : ConcreteSection
        Member geometry.
    stirrup_diameter_mm : int
        Stirrup bar diameter (mm).
    spacing_mm : float
        Centre-to-centre stirrup spacing (mm).
    mark_prefix : str
        Mark prefix in bending schedule.
    shape_code : str
        Shape code for the stirrup; default '25' (closed rectangular, 1 hook).

    Returns
    -------
    list[RebarInstance]
        One RebarInstance representing all stirrups (count = number placed).
    """
    cv = section.cover_mm
    d_s = float(stirrup_diameter_mm)

    # Inner dimensions of the stirrup (inside face to inside face)
    inner_w = section.width_mm - 2.0 * cv - d_s
    inner_h = section.depth_mm - 2.0 * cv - d_s

    # Stirrup legs: A = inner width, B = inner height
    dims = {"A": round(inner_w, 1), "B": round(inner_h, 1)}

    cut_len = bar_cut_length(shape_code, dims, stirrup_diameter_mm)

    # Number of stirrups: place from end_offset to (length - end_offset)
    end_offset = cv  # start/end covers
    usable_length = section.length_mm - 2.0 * end_offset
    count = max(1, int(usable_length / spacing_mm) + 1)

    # Centreline paths: represent first and last stirrup positions
    centreline = [
        Point3(section.width_mm / 2.0, section.depth_mm / 2.0, end_offset),
        Point3(section.width_mm / 2.0, section.depth_mm / 2.0,
               end_offset + (count - 1) * spacing_mm),
    ]

    return [RebarInstance(
        mark=f"{mark_prefix}1",
        shape_code=shape_code,
        diameter_mm=stirrup_diameter_mm,
        cut_length_mm=cut_len,
        count=count,
        dims=dims.copy(),
        centreline=centreline,
        role="stirrup",
    )]


def place_column_ties(
    section: ConcreteSection,
    tie_diameter_mm: int,
    spacing_mm: float,
    mark_prefix: str = "T",
) -> list[RebarInstance]:
    """
    Place square/rectangular column ties (same shape as stirrups, shape 25).

    Parameters
    ----------
    section : ConcreteSection
        Column cross-section (width = depth for square columns).
    tie_diameter_mm : int
        Tie bar diameter (mm).
    spacing_mm : float
        Tie spacing (mm).
    mark_prefix : str
        Mark prefix.

    Returns
    -------
    list[RebarInstance]
    """
    return place_stirrups(
        section, tie_diameter_mm, spacing_mm,
        mark_prefix=mark_prefix, shape_code="25"
    )


def detail_member(
    member_type: Literal["beam", "column", "slab"],
    length_mm: float,
    width_mm: float,
    depth_mm: float,
    cover_mm: float,
    long_bar_diameter_mm: int,
    n_bars_bottom: int,
    n_bars_top: int,
    stirrup_diameter_mm: int,
    stirrup_spacing_mm: float,
) -> dict:
    """
    Full 3D rebar detailing for a single concrete member.

    Returns a placement dict with:
      - section geometry
      - longitudinal_bars: list of RebarInstance dicts
      - stirrups: list of RebarInstance dicts
      - all_bars: combined list
      - summary: total bar count and mass

    Parameters
    ----------
    member_type : {'beam', 'column', 'slab'}
        Member category (affects placement naming).
    length_mm : float
        Member length along its axis (mm).
    width_mm : float
        Cross-section width (mm).
    depth_mm : float
        Cross-section depth / height (mm).
    cover_mm : float
        Clear cover to face of stirrups (mm).
    long_bar_diameter_mm : int
        Longitudinal bar diameter (mm).
    n_bars_bottom : int
        Bars in bottom layer (beams) / face (columns).
    n_bars_top : int
        Bars in top layer (beams) / opposite face (columns).
    stirrup_diameter_mm : int
        Transverse reinforcement diameter (mm).
    stirrup_spacing_mm : float
        Transverse reinforcement spacing (mm).

    Returns
    -------
    dict
        Placement result including bar lists and schedule-ready data.
    """
    section = ConcreteSection(
        width_mm=width_mm,
        depth_mm=depth_mm,
        length_mm=length_mm,
        cover_mm=cover_mm,
    )

    longs = place_longitudinal_bars(
        section,
        bar_diameter_mm=long_bar_diameter_mm,
        n_bars_bottom=n_bars_bottom,
        n_bars_top=n_bars_top,
        stirrup_diameter_mm=stirrup_diameter_mm,
        mark_prefix="L",
    )

    if member_type == "slab":
        stirrups = []
    elif member_type == "column":
        stirrups = place_column_ties(
            section, tie_diameter_mm=stirrup_diameter_mm,
            spacing_mm=stirrup_spacing_mm, mark_prefix="T"
        )
    else:
        stirrups = place_stirrups(
            section, stirrup_diameter_mm=stirrup_diameter_mm,
            spacing_mm=stirrup_spacing_mm, mark_prefix="S"
        )

    all_bars = longs + stirrups
    total_count = sum(b.count for b in all_bars)
    total_mass = round(sum(b.mass_kg for b in all_bars), 3)

    def _bar_dict(b: RebarInstance) -> dict:
        return {
            "mark": b.mark,
            "shape_code": b.shape_code,
            "diameter_mm": b.diameter_mm,
            "cut_length_mm": b.cut_length_mm,
            "count": b.count,
            "mass_kg": b.mass_kg,
            "dims": b.dims,
            "role": b.role,
            "centreline": [p.as_list() for p in b.centreline],
        }

    return {
        "ok": True,
        "member_type": member_type,
        "section": {
            "length_mm": length_mm,
            "width_mm": width_mm,
            "depth_mm": depth_mm,
            "cover_mm": cover_mm,
        },
        "longitudinal_bars": [_bar_dict(b) for b in longs],
        "stirrups": [_bar_dict(b) for b in stirrups],
        "all_bars": [_bar_dict(b) for b in all_bars],
        "summary": {
            "total_bar_count": total_count,
            "total_mass_kg": total_mass,
        },
    }


# ---------------------------------------------------------------------------
# Bar-bending schedule
# ---------------------------------------------------------------------------

@dataclass
class ScheduleRow:
    """One row of a BS 8666 bar-bending schedule."""
    member_ref: str
    bar_mark: str
    shape_code: str
    bar_type: str          # "H" (high-yield) or "R" (mild steel)
    diameter_mm: int
    cut_length_mm: float
    number_of_bars: int
    dims: dict             # A, B, C, D (mm)
    total_length_m: float
    mass_kg: float


def generate_bending_schedule(
    members: list[dict],
) -> dict:
    """
    Generate a complete bar-bending schedule from a list of detailed member dicts.

    Parameters
    ----------
    members : list[dict]
        Each dict must contain at minimum:
          member_ref : str        — e.g. 'B1', 'C2'
          all_bars   : list[dict] — from detail_member output

    Returns
    -------
    dict
        {
          "rows": list of schedule row dicts,
          "summary": { "total_mass_kg", "total_bars" }
        }
    """
    rows: list[dict] = []

    for member in members:
        ref = member.get("member_ref", "?")
        for bar in member.get("all_bars", []):
            d = int(bar["diameter_mm"])
            count = int(bar["count"])
            cut_len = float(bar["cut_length_mm"])

            try:
                props = bs_bar_properties(d)
                mass = round(props.mass_kg_per_m * (cut_len / 1000.0) * count, 3)
            except ValueError:
                mass = 0.0

            rows.append({
                "member_ref": ref,
                "bar_mark": bar["mark"],
                "shape_code": bar["shape_code"],
                "bar_type": "H",   # high-yield (default; extend with material input)
                "diameter_mm": d,
                "cut_length_mm": cut_len,
                "number_of_bars": count,
                "dims": bar.get("dims", {}),
                "total_length_m": round(cut_len / 1000.0 * count, 3),
                "mass_kg": mass,
            })

    total_mass = round(sum(r["mass_kg"] for r in rows), 3)
    total_bars = sum(r["number_of_bars"] for r in rows)

    return {
        "ok": True,
        "rows": rows,
        "summary": {
            "total_mass_kg": total_mass,
            "total_bars": total_bars,
            "row_count": len(rows),
        },
    }
