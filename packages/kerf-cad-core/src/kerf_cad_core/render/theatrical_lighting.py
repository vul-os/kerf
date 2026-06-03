"""
kerf_cad_core.render.theatrical_lighting — Luminaire library, IES LM-63 photometric
file reader, and theatrical lighting plot generator.

This module provides:
  * IES LM-63-2002 photometric data file parser (ASCII format)
  * Luminaire / fixture library covering PAR64, ETC Source Four, moving-head washes, etc.
  * TheatricalLightingPlot — positions, aims, truss lines, and SVG output
    (Vectorworks-style plan view)

References
----------
IESNA LM-63-2002 — "Standard File Format for Electronic Transfer of Photometric Data
    and Related Information."  Illuminating Engineering Society of North America.
Ashdown, I. (1994).  "Radiosity: A Programmer's Perspective."  Wiley.  Ch. 2 (IES file
    format internals).
Gillette, J.M. (2008).  "Designing with Light: The Art, Science, and Practice of
    Theatrical Lighting Design."  4th ed.  McGraw-Hill.

Author: imranparuk
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Luminaire type catalogue — a representative selection.
FIXTURE_TYPES = [
    "PAR64",
    "PAR38",
    "ETC Source Four",
    "ETC Source Four Jr",
    "Mac Quantum Wash",
    "Mac Aura",
    "Robe BMFL",
    "Clay Paky A.leda",
    "Strand SL",
    "Fresnelite",
    "Cyclorama Strip",
    "Ground Row",
    "Followspot",
]

# Default peak candela per fixture type (cd) — approximate catalogue values
_DEFAULT_PEAK_CD: dict[str, float] = {
    "PAR64": 45000.0,
    "PAR38": 3500.0,
    "ETC Source Four": 60000.0,
    "ETC Source Four Jr": 28000.0,
    "Mac Quantum Wash": 9000.0,
    "Mac Aura": 6500.0,
    "Robe BMFL": 140000.0,
    "Clay Paky A.leda": 25000.0,
    "Strand SL": 38000.0,
    "Fresnelite": 12000.0,
    "Cyclorama Strip": 1200.0,
    "Ground Row": 800.0,
    "Followspot": 80000.0,
}


# ---------------------------------------------------------------------------
# IES LM-63 photometric data file
# ---------------------------------------------------------------------------

@dataclass
class IesPhotometricFile:
    """IES LM-63 photometric data file.

    Attributes
    ----------
    luminaire_name : str
        Manufacturer / luminaire name from ``[LUMINAIRE]`` header keyword.
    candela_grid : np.ndarray, shape (n_vertical, n_horizontal)
        Candela intensity values.  Rows = vertical angles, columns = horizontal angles.
    vertical_angles : np.ndarray, shape (n_vertical,)
        Vertical angles in degrees (0 = nadir, 90 = horizontal, 180 = zenith).
    horizontal_angles : np.ndarray, shape (n_horizontal,)
        Horizontal angles in degrees.
    lumens : float
        Total rated lumen output (from the TILT=NONE header line).

    References
    ----------
    IESNA LM-63-2002, §7 (data block structure).
    """
    luminaire_name: str
    candela_grid: np.ndarray          # (n_vertical, n_horizontal) cd
    vertical_angles: np.ndarray
    horizontal_angles: np.ndarray
    lumens: float                     # total rated lumen output


def read_ies_file(content: str) -> IesPhotometricFile:
    """Parse an IES LM-63-2002 ASCII photometric file from its text content.

    The parser handles:
    * ``[LUMINAIRE]``, ``[ISSUEDATE]``, ``[LAMP]``, etc. keyword lines.
    * The ``TILT=NONE`` or ``TILT=INCLUDE`` header (only NONE + INCLUDE are
      recognised; TILT=FILE is not supported).
    * The lamp descriptor line (count, lumens, multiplier, V angles, H angles,
      photometric type, units, dimensions, ballast factor, …).
    * The vertical-angle block, horizontal-angle block, and candela matrix.

    Parameters
    ----------
    content : str
        Full text of the ``.ies`` file (newlines preserved).

    Returns
    -------
    IesPhotometricFile

    Raises
    ------
    ValueError
        If mandatory sections are missing or the candela matrix dimensions
        do not match the declared angle counts.

    References
    ----------
    IESNA LM-63-2002, §6 (header keywords) and §7 (data block).
    Ashdown (1994) Ch. 2.
    """
    lines: list[str] = content.splitlines()

    luminaire_name = "Unknown"
    keyword_done = False
    data_lines: list[str] = []

    # ── 1. Collect header keywords and locate start of data block ─────────
    in_data = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if not in_data:
            # Keyword line?
            m = re.match(r"^\[([A-Z_0-9]+)\]\s*(.*)", stripped)
            if m:
                key, val = m.group(1), m.group(2).strip()
                if key == "LUMINAIRE":
                    luminaire_name = val
                continue
            # TILT line marks start of data block
            if stripped.startswith("TILT="):
                tilt_val = stripped.split("=", 1)[1].strip().upper()
                in_data = True
                if tilt_val == "INCLUDE":
                    # Skip the 4 TILT=INCLUDE lines (orientation, count, angles, candelas)
                    # — not modelled in this simplified parser
                    pass
                continue
        else:
            data_lines.append(stripped)

    if not data_lines:
        raise ValueError("IES file: no data block found (missing TILT= line).")

    # ── 2. Tokenise all data tokens (integers and floats) ─────────────────
    tokens: list[str] = []
    for dl in data_lines:
        tokens.extend(dl.split())

    if len(tokens) < 13:
        raise ValueError(f"IES file: data block too short ({len(tokens)} tokens).")

    idx = 0

    def _next_float() -> float:
        nonlocal idx
        val = float(tokens[idx])
        idx += 1
        return val

    def _next_int() -> int:
        return int(_next_float())

    # Lamp count, lumens, candela-multiplier, n_vertical, n_horizontal
    _lamp_count = _next_int()          # number of lamps
    lumens = _next_float()             # rated lumens per lamp
    _candela_mult = _next_float()      # candela multiplier (usually 1.0)
    n_vert = _next_int()               # number of vertical angles
    n_horiz = _next_int()              # number of horizontal angles
    _photometric_type = _next_int()    # 1=Type C, 2=Type B, 3=Type A
    _units_type = _next_int()          # 1=feet, 2=metres
    _width = _next_float()
    _length = _next_float()
    _height = _next_float()
    _ballast_factor = _next_float()
    _future = _next_float()            # reserved / future use
    _input_watts = _next_float()

    # Vertical angles
    if idx + n_vert > len(tokens):
        raise ValueError(
            f"IES file: expected {n_vert} vertical angles but only "
            f"{len(tokens) - idx} tokens remain."
        )
    vertical_angles = np.array([float(tokens[idx + i]) for i in range(n_vert)])
    idx += n_vert

    # Horizontal angles
    if idx + n_horiz > len(tokens):
        raise ValueError(
            f"IES file: expected {n_horiz} horizontal angles but only "
            f"{len(tokens) - idx} tokens remain."
        )
    horizontal_angles = np.array([float(tokens[idx + i]) for i in range(n_horiz)])
    idx += n_horiz

    # Candela values — n_horiz blocks of n_vert values each, then transposed
    n_cd = n_vert * n_horiz
    if idx + n_cd > len(tokens):
        raise ValueError(
            f"IES file: expected {n_cd} candela values but only "
            f"{len(tokens) - idx} remain."
        )
    raw_cd = np.array([float(tokens[idx + i]) for i in range(n_cd)])
    idx += n_cd

    # IES stores: for each H angle, all V values → shape (n_horiz, n_vert)
    # Transpose to (n_vert, n_horiz) for the grid
    cd_horiz_major = raw_cd.reshape(n_horiz, n_vert)
    candela_grid = (cd_horiz_major.T * _candela_mult)

    return IesPhotometricFile(
        luminaire_name=luminaire_name,
        candela_grid=candela_grid,
        vertical_angles=vertical_angles,
        horizontal_angles=horizontal_angles,
        lumens=lumens,
    )


def ies_candela_at(
    ies: IesPhotometricFile,
    vertical_deg: float,
    horizontal_deg: float,
) -> float:
    """Bilinear interpolation of candela value at (vertical, horizontal) angles.

    Parameters
    ----------
    ies : IesPhotometricFile
    vertical_deg : float
        Vertical angle in degrees.
    horizontal_deg : float
        Horizontal angle in degrees.

    Returns
    -------
    float
        Candela value [cd].

    References
    ----------
    IESNA LM-63-2002, §7.3 (interpolation of photometric values).
    """
    va = ies.vertical_angles
    ha = ies.horizontal_angles
    grid = ies.candela_grid  # (n_vert, n_horiz)

    # Clamp to valid range
    v = float(np.clip(vertical_deg, va[0], va[-1]))
    h = float(np.clip(horizontal_deg % 360.0, ha[0], ha[-1]))

    # Nearest indices (for bilinear)
    iv = int(np.searchsorted(va, v, side="right")) - 1
    iv = int(np.clip(iv, 0, len(va) - 2))
    ih = int(np.searchsorted(ha, h, side="right")) - 1
    ih = int(np.clip(ih, 0, len(ha) - 2))

    dv = (v - va[iv]) / (va[iv + 1] - va[iv]) if va[iv + 1] != va[iv] else 0.0
    dh = (h - ha[ih]) / (ha[ih + 1] - ha[ih]) if ha[ih + 1] != ha[ih] else 0.0

    c00 = grid[iv, ih]
    c10 = grid[iv + 1, ih]
    c01 = grid[iv, ih + 1]
    c11 = grid[iv + 1, ih + 1]

    return float(
        c00 * (1 - dv) * (1 - dh)
        + c10 * dv * (1 - dh)
        + c01 * (1 - dv) * dh
        + c11 * dv * dh
    )


# ---------------------------------------------------------------------------
# Theatrical fixture
# ---------------------------------------------------------------------------

@dataclass
class TheatricalFixture:
    """A single theatrical lighting fixture in a plot.

    Attributes
    ----------
    fixture_id : str
        Unique identifier (e.g. ``'LX1-01'``).
    type : str
        Fixture type string from ``FIXTURE_TYPES``.
    position : tuple[float, float, float]
        World-space position (X, Y, Z) in metres.
    aim_target : tuple[float, float, float]
        The point in world space the fixture is aimed at.
    color : tuple[float, float, float]
        RGB colour gel (values 0..1).
    intensity_pct : float
        Dimmer level, 0..100.
    ies_file : IesPhotometricFile | None
        Optional IES photometric data; if None a simple cosine lobe is used.
    channel : int
        DMX channel (1-based, 1..512).
    circuit : str
        Electrical circuit identifier (e.g. ``'C-14'``).
    purpose : str
        Descriptive note (e.g. ``'Key light DR'``).
    """
    fixture_id: str
    type: str
    position: Tuple[float, float, float]
    aim_target: Tuple[float, float, float]
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    intensity_pct: float = 100.0
    ies_file: Optional[IesPhotometricFile] = None
    channel: int = 1
    circuit: str = ""
    purpose: str = ""


# ---------------------------------------------------------------------------
# Theatrical lighting plot
# ---------------------------------------------------------------------------

@dataclass
class TheatricalLightingPlot:
    """Complete theatrical lighting plot — fixtures + truss lines.

    Attributes
    ----------
    fixtures : list[TheatricalFixture]
    truss_lines : list[tuple[tuple[float,float,float], tuple[float,float,float]]]
        Each entry is (start_xyz, end_xyz) in world space (metres).
    stage_width : float
        Total stage width (X extent, metres).
    stage_depth : float
        Total stage depth (Y extent, metres).

    References
    ----------
    Gillette (2008) Ch. 5 — lighting plot conventions and symbols.
    """
    fixtures: List[TheatricalFixture] = field(default_factory=list)
    truss_lines: List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = field(
        default_factory=list
    )
    stage_width: float = 10.0   # metres
    stage_depth: float = 8.0    # metres

    # ------------------------------------------------------------------
    # Beam illuminance
    # ------------------------------------------------------------------

    def illuminance_at(self, point: Tuple[float, float, float]) -> float:
        """Compute total illuminance at *point* from all fixtures (lux).

        For each fixture the inverse-square cosine law is applied.  If an IES
        file is attached the candela at the relevant vertical angle is used;
        otherwise the peak candela from the catalogue is used with a cos²(θ)
        beam fall-off (approximating a PAR/ellipsoidal).

        E = (I · cos θ) / d²   [IES HB-10 §5.3]

        Parameters
        ----------
        point : (float, float, float)
            Measurement point in world space (metres).

        Returns
        -------
        float
            Illuminance in lux [lx].
        """
        pt = np.array(point, dtype=float)
        total_lux = 0.0

        for fix in self.fixtures:
            pos = np.array(fix.position, dtype=float)
            aim = np.array(fix.aim_target, dtype=float)

            diff = pt - pos
            dist = float(np.linalg.norm(diff))
            if dist < 1e-9:
                continue

            # Fixture aim direction (unit)
            aim_dir = aim - pos
            aim_dist = float(np.linalg.norm(aim_dir))
            if aim_dist < 1e-9:
                continue
            aim_unit = aim_dir / aim_dist

            # Angle between aim direction and direction-to-point
            cos_theta = float(np.dot(aim_unit, diff / dist))
            cos_theta = max(0.0, cos_theta)

            # Candela
            if fix.ies_file is not None:
                theta_deg = math.degrees(math.acos(min(1.0, cos_theta)))
                cd = ies_candela_at(fix.ies_file, theta_deg, 0.0)
            else:
                # Use catalogue peak candela with cos² falloff
                peak_cd = _DEFAULT_PEAK_CD.get(fix.type, 10000.0)
                cd = peak_cd * (cos_theta ** 2)

            # Dimmer scaling
            cd *= fix.intensity_pct / 100.0

            # Inverse-square law (E = I·cosθ / d²)
            total_lux += cd * cos_theta / (dist * dist + 1e-12)

        return total_lux

    # ------------------------------------------------------------------
    # SVG drawing (Vectorworks-style plan view)
    # ------------------------------------------------------------------

    def to_svg(
        self,
        plan_view_only: bool = True,
        svg_width_px: int = 800,
        margin_m: float = 1.0,
    ) -> str:
        """Generate a Vectorworks-style lighting plot as an SVG string.

        In plan view (looking down the Z axis):
        * Stage outline drawn as a grey rectangle.
        * Truss lines drawn as heavy black horizontal rules.
        * Each fixture rendered as a circle (colour-coded) + aim-direction arrow
          + label showing fixture_id and type.

        Parameters
        ----------
        plan_view_only : bool
            Currently only plan-view (top-down) is implemented.
        svg_width_px : int
            Width of the generated SVG in pixels.
        margin_m : float
            Scene margin beyond stage bounds.

        Returns
        -------
        str
            SVG XML string.

        References
        ----------
        Gillette (2008) Ch. 5 — lighting plot symbol conventions.
        IESNA LM-63-2002 §9 (photometric data file association with fixture plot).
        """
        total_w = self.stage_width + 2 * margin_m
        total_d = self.stage_depth + 2 * margin_m

        aspect = total_d / total_w
        svg_h = int(svg_width_px * aspect)
        scale = svg_width_px / total_w  # px per metre

        def wx(x: float) -> float:
            return (x + margin_m) * scale

        def wy(y: float) -> float:
            # Y increases downward in SVG (stage "up" = negative Y)
            return (total_d - (y + margin_m)) * scale

        lines: list[str] = []
        lines.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{svg_width_px}" height="{svg_h}" '
            f'viewBox="0 0 {svg_width_px} {svg_h}">'
        )
        lines.append("  <!-- Theatrical Lighting Plot — kerf_cad_core.render.theatrical_lighting -->")
        lines.append(
            "  <!-- Reference: Gillette (2008) Ch.5; IESNA LM-63-2002 §9 -->"
        )

        # Background
        lines.append(f'  <rect width="{svg_width_px}" height="{svg_h}" fill="#1a1a1a"/>')

        # Stage outline
        sx0 = wx(0.0)
        sy0 = wy(self.stage_depth)
        sw = self.stage_width * scale
        sdepth = self.stage_depth * scale
        lines.append(
            f'  <rect x="{sx0:.1f}" y="{sy0:.1f}" width="{sw:.1f}" height="{sdepth:.1f}" '
            f'fill="#2a2a2a" stroke="#888" stroke-width="1.5"/>'
        )
        lines.append(
            f'  <text x="{sx0 + sw/2:.1f}" y="{wy(0) - 4:.1f}" '
            f'fill="#666" font-size="10" text-anchor="middle">STAGE</text>'
        )

        # Truss lines
        for (x0, y0, z0), (x1, y1, z1) in self.truss_lines:
            lines.append(
                f'  <line x1="{wx(x0):.1f}" y1="{wy(y0):.1f}" '
                f'x2="{wx(x1):.1f}" y2="{wy(y1):.1f}" '
                f'stroke="#c8a060" stroke-width="4" stroke-linecap="round"/>'
            )

        # Fixtures
        r = max(5.0, scale * 0.15)  # fixture symbol radius in px
        for fix in self.fixtures:
            px = wx(fix.position[0])
            py = wy(fix.position[1])

            # Colour
            cr, cg, cb = fix.color
            hex_color = "#{:02x}{:02x}{:02x}".format(
                int(cr * 255), int(cg * 255), int(cb * 255)
            )
            dim_alpha = fix.intensity_pct / 100.0

            # Aim direction arrow
            aim = np.array(fix.aim_target[:2])
            pos2 = np.array(fix.position[:2])
            aim_vec = aim - pos2
            aim_len = float(np.linalg.norm(aim_vec))
            if aim_len > 1e-6:
                aim_unit = aim_vec / aim_len
                arrow_len = r * 2.0
                ax = px + aim_unit[0] * arrow_len
                ay = py - aim_unit[1] * arrow_len  # SVG y flip
                lines.append(
                    f'  <line x1="{px:.1f}" y1="{py:.1f}" '
                    f'x2="{ax:.1f}" y2="{ay:.1f}" '
                    f'stroke="{hex_color}" stroke-width="1.5" opacity="{dim_alpha:.2f}"/>'
                )

            # Fixture circle
            lines.append(
                f'  <circle cx="{px:.1f}" cy="{py:.1f}" r="{r:.1f}" '
                f'fill="{hex_color}" opacity="{dim_alpha:.2f}" '
                f'stroke="#fff" stroke-width="0.8"/>'
            )

            # Label
            label = f"{fix.fixture_id} / {fix.type}"
            lines.append(
                f'  <text x="{px:.1f}" y="{py - r - 3:.1f}" '
                f'fill="#ddd" font-size="8" text-anchor="middle">{label}</text>'
            )

        lines.append("</svg>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def fixture_count(self) -> int:
        """Return number of fixtures in the plot."""
        return len(self.fixtures)

    def total_load_watts(self, wattage_per_type: Optional[dict] = None) -> float:
        """Estimate total electrical load in watts.

        Parameters
        ----------
        wattage_per_type : dict[str, float] | None
            Override wattage per fixture type.  If None, defaults are used.

        Returns
        -------
        float
            Total watts.
        """
        defaults = {
            "PAR64": 1000.0,
            "PAR38": 150.0,
            "ETC Source Four": 575.0,
            "ETC Source Four Jr": 375.0,
            "Mac Quantum Wash": 630.0,
            "Mac Aura": 380.0,
            "Robe BMFL": 1700.0,
            "Clay Paky A.leda": 350.0,
            "Strand SL": 575.0,
            "Fresnelite": 500.0,
            "Cyclorama Strip": 300.0,
            "Ground Row": 200.0,
            "Followspot": 1000.0,
        }
        overrides = wattage_per_type or {}
        total = 0.0
        for fix in self.fixtures:
            w = overrides.get(fix.type, defaults.get(fix.type, 500.0))
            total += w * fix.intensity_pct / 100.0
        return total
