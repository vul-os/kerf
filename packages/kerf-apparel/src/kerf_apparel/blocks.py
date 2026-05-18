"""
Parametric pattern-block generators for kerf-apparel.

Each generator takes body measurements (in cm unless noted) and returns a
``PatternPiece`` — a closed 2-D polyline (list of (x, y) tuples, last point
equals first) plus metadata.

Supported blocks
----------------
- bodice_front / bodice_back  — basic bodice blocks
- sleeve                      — one-piece set-in sleeve block
- pants_front / pants_back    — basic trousers block

All geometry is flat / 2-D.  No ease is added by default; call with
``ease_bust``, ``ease_waist``, ``ease_hip`` kwargs to customise.

Units: centimetres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

Point = tuple[float, float]
Polyline = list[Point]


@dataclass
class PatternPiece:
    """A single closed 2-D pattern piece."""

    name: str
    outline: Polyline          # closed: last pt == first pt
    grain_line: tuple[Point, Point] | None = None
    notches: list[Point] = field(default_factory=list)
    labels: dict[str, float] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Convenience                                                          #
    # ------------------------------------------------------------------ #

    def area(self) -> float:
        """Shoelace area (always positive)."""
        pts = self.outline
        n = len(pts)
        acc = 0.0
        for i in range(n - 1):
            acc += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
        return abs(acc) / 2.0

    def perimeter(self) -> float:
        """Total perimeter length."""
        pts = self.outline
        total = 0.0
        for i in range(len(pts) - 1):
            dx = pts[i + 1][0] - pts[i][0]
            dy = pts[i + 1][1] - pts[i][1]
            total += math.hypot(dx, dy)
        return total

    def bounding_box(self) -> tuple[float, float, float, float]:
        """(min_x, min_y, max_x, max_y)."""
        xs = [p[0] for p in self.outline]
        ys = [p[1] for p in self.outline]
        return min(xs), min(ys), max(xs), max(ys)


# ------------------------------------------------------------------ #
# Size table (standard womenswear, all measurements in cm)            #
# ------------------------------------------------------------------ #

# fmt: off
_SIZE_TABLE: dict[str, dict[str, float]] = {
    "XS": {"bust": 80,  "waist": 62,  "hip": 87,  "back_length": 40, "sleeve_length": 57, "inseam": 76, "rise": 26},
    "S":  {"bust": 84,  "waist": 66,  "hip": 91,  "back_length": 41, "sleeve_length": 58, "inseam": 77, "rise": 27},
    "M":  {"bust": 88,  "waist": 70,  "hip": 95,  "back_length": 42, "sleeve_length": 59, "inseam": 78, "rise": 28},
    "L":  {"bust": 93,  "waist": 75,  "hip": 100, "back_length": 43, "sleeve_length": 60, "inseam": 79, "rise": 29},
    "XL": {"bust": 98,  "waist": 80,  "hip": 105, "back_length": 44, "sleeve_length": 61, "inseam": 80, "rise": 30},
    "XXL":{"bust": 103, "waist": 85,  "hip": 110, "back_length": 45, "sleeve_length": 62, "inseam": 81, "rise": 31},
    # Numeric US sizes (even)
    "0":  {"bust": 80,  "waist": 61,  "hip": 86,  "back_length": 40, "sleeve_length": 57, "inseam": 76, "rise": 26},
    "2":  {"bust": 83,  "waist": 64,  "hip": 89,  "back_length": 40, "sleeve_length": 57, "inseam": 76, "rise": 26},
    "4":  {"bust": 85,  "waist": 66,  "hip": 91,  "back_length": 41, "sleeve_length": 58, "inseam": 77, "rise": 27},
    "6":  {"bust": 87,  "waist": 68,  "hip": 93,  "back_length": 41, "sleeve_length": 58, "inseam": 77, "rise": 27},
    "8":  {"bust": 89,  "waist": 70,  "hip": 95,  "back_length": 42, "sleeve_length": 59, "inseam": 78, "rise": 28},
    "10": {"bust": 91,  "waist": 72,  "hip": 97,  "back_length": 42, "sleeve_length": 59, "inseam": 78, "rise": 28},
    "12": {"bust": 94,  "waist": 75,  "hip": 100, "back_length": 43, "sleeve_length": 60, "inseam": 79, "rise": 29},
    "14": {"bust": 97,  "waist": 78,  "hip": 103, "back_length": 43, "sleeve_length": 60, "inseam": 79, "rise": 29},
    "16": {"bust": 100, "waist": 82,  "hip": 107, "back_length": 44, "sleeve_length": 61, "inseam": 80, "rise": 30},
    "18": {"bust": 104, "waist": 86,  "hip": 111, "back_length": 44, "sleeve_length": 61, "inseam": 80, "rise": 30},
    "20": {"bust": 108, "waist": 90,  "hip": 115, "back_length": 45, "sleeve_length": 62, "inseam": 81, "rise": 31},
    "22": {"bust": 112, "waist": 94,  "hip": 119, "back_length": 45, "sleeve_length": 62, "inseam": 81, "rise": 31},
}
# fmt: on


def get_measurements(size: str) -> dict[str, float]:
    """Return the standard measurement table for a named size."""
    key = str(size).strip().upper()
    if key not in _SIZE_TABLE:
        raise ValueError(f"Unknown size {size!r}. Valid: {sorted(_SIZE_TABLE)}")
    return dict(_SIZE_TABLE[key])


# ------------------------------------------------------------------ #
# Internal helpers                                                     #
# ------------------------------------------------------------------ #

def _close(pts: list[Point]) -> Polyline:
    """Ensure a polyline is closed (last pt == first pt)."""
    if pts and pts[-1] != pts[0]:
        pts = list(pts) + [pts[0]]
    return pts


def _arc_points(cx: float, cy: float, r: float,
                start_deg: float, end_deg: float,
                n: int = 8) -> list[Point]:
    """Approximate arc with ``n`` line segments."""
    pts = []
    for i in range(n + 1):
        t = start_deg + (end_deg - start_deg) * i / n
        rad = math.radians(t)
        pts.append((cx + r * math.cos(rad), cy + r * math.sin(rad)))
    return pts


# ------------------------------------------------------------------ #
# Bodice front                                                         #
# ------------------------------------------------------------------ #

def bodice_front(
    bust: float,
    waist: float,
    hip: float,
    back_length: float,
    *,
    ease_bust: float = 4.0,
    ease_waist: float = 2.0,
    ease_hip: float = 4.0,
) -> PatternPiece:
    """
    Generate a basic bodice front block.

    The block is a simplified rectangle-with-darts approximation suitable
    for pattern-making education and algorithmic downstream use (seam
    allowance, grading, marker making).

    Origin is at the top-left (shoulder-neck point).

    Parameters
    ----------
    bust, waist, hip : float
        Body measurements in cm.
    back_length : float
        Back waist length (nape to waist), cm.
    ease_bust, ease_waist, ease_hip : float
        Fitting ease to add, cm.
    """
    half_bust = (bust + ease_bust) / 4.0
    half_waist = (waist + ease_waist) / 4.0
    half_hip = (hip + ease_hip) / 4.0

    length = back_length  # approximate front body length

    # Shoulder slope: ~2 cm drop over half-bust width
    shoulder_slope = 2.0
    shoulder_width = half_bust * 0.45
    armhole_depth = bust / 10.0 + 2.0

    # Basic bodice front outline (simplified, no collar shaping):
    # A=top-left (CB neck), B=shoulder tip, C=armhole, D=side-waist,
    # E=side-hip (not included — bodice ends at waist), F=CF waist,
    # G=CF neck
    #
    # We build a polygon approximation:
    #   neck width at CF = bust/16
    #   neck depth at CF = bust/16 + 0.5

    neck_w = bust / 16.0
    neck_d = bust / 16.0 + 0.5

    # Key x coords (working left = CF, right = side seam)
    x_cf = 0.0
    x_shoulder = shoulder_width
    x_side = half_bust

    # Key y coords (working top = shoulder, down = hem)
    y_shoulder = 0.0
    y_armhole = armhole_depth
    y_waist = length

    # Neck curve approximated by 3 points
    neck_pts = [
        (x_cf + neck_w, y_shoulder),         # shoulder-neck
        (x_cf + neck_w / 2, y_shoulder + neck_d / 2),  # neck curve mid
        (x_cf, y_shoulder + neck_d),         # CF neck
    ]

    # Shoulder line
    shoulder_tip = (x_shoulder, y_shoulder + shoulder_slope)

    # Armhole curve approximated by 3 points
    armhole_pts = _arc_points(
        x_shoulder, y_armhole,
        r=x_side - x_shoulder,
        start_deg=90, end_deg=0,
        n=4,
    )

    # Side seam: waist is narrower — dart taken in equally at side seam
    waist_diff = half_bust - half_waist
    x_side_waist = x_side - waist_diff

    side_pts = [
        (x_side, y_armhole),         # bottom of armhole
        (x_side_waist, y_waist),     # waist side
    ]

    # Waist and CF lines
    waist_pts = [
        (x_side_waist, y_waist),
        (x_cf, y_waist),
    ]

    cf_pts = [
        (x_cf, y_waist),
        (x_cf, y_shoulder + neck_d),
    ]

    all_pts: list[Point] = (
        neck_pts
        + [shoulder_tip]
        + armhole_pts
        + side_pts[1:]
        + [(x_cf, y_waist)]
        + cf_pts[1:]
    )

    outline = _close(all_pts)

    grain = ((x_cf + half_bust / 2, y_shoulder + 2), (x_cf + half_bust / 2, y_waist - 2))

    return PatternPiece(
        name="bodice_front",
        outline=outline,
        grain_line=grain,
        labels={
            "bust": bust,
            "waist": waist,
            "hip": hip,
            "back_length": back_length,
            "half_bust_with_ease": half_bust,
        },
    )


# ------------------------------------------------------------------ #
# Bodice back                                                          #
# ------------------------------------------------------------------ #

def bodice_back(
    bust: float,
    waist: float,
    hip: float,
    back_length: float,
    *,
    ease_bust: float = 4.0,
    ease_waist: float = 2.0,
    ease_hip: float = 4.0,
) -> PatternPiece:
    """
    Generate a basic bodice back block.

    Mirror image of front with reduced neck depth and higher back neckline.
    """
    half_bust = (bust + ease_bust) / 4.0
    half_waist = (waist + ease_waist) / 4.0

    length = back_length
    shoulder_width = half_bust * 0.45
    shoulder_slope = 1.5
    armhole_depth = bust / 10.0 + 2.0

    neck_w = bust / 16.0
    neck_d = 2.0  # back neck is much shallower

    x_cf = 0.0
    x_shoulder = shoulder_width
    x_side = half_bust
    y_shoulder = 0.0
    y_armhole = armhole_depth
    y_waist = length

    neck_pts = [
        (x_cf + neck_w, y_shoulder),
        (x_cf + neck_w / 2, y_shoulder + neck_d / 2),
        (x_cf, y_shoulder + neck_d),
    ]

    shoulder_tip = (x_shoulder, y_shoulder + shoulder_slope)

    armhole_pts = _arc_points(
        x_shoulder, y_armhole,
        r=x_side - x_shoulder,
        start_deg=90, end_deg=0,
        n=4,
    )

    waist_diff = half_bust - half_waist
    x_side_waist = x_side - waist_diff

    all_pts: list[Point] = (
        neck_pts
        + [shoulder_tip]
        + armhole_pts
        + [(x_side_waist, y_waist)]
        + [(x_cf, y_waist)]
        + [(x_cf, y_shoulder + neck_d)]
    )

    outline = _close(all_pts)

    grain = ((x_cf + half_bust / 2, y_shoulder + 2), (x_cf + half_bust / 2, y_waist - 2))

    return PatternPiece(
        name="bodice_back",
        outline=outline,
        grain_line=grain,
        labels={
            "bust": bust,
            "waist": waist,
            "back_length": back_length,
            "half_bust_with_ease": half_bust,
        },
    )


# ------------------------------------------------------------------ #
# Sleeve                                                               #
# ------------------------------------------------------------------ #

def sleeve(
    bust: float,
    sleeve_length: float,
    *,
    ease_sleeve: float = 3.0,
) -> PatternPiece:
    """
    Generate a basic one-piece set-in sleeve block.

    The sleeve head is approximated by a half-ellipse.
    """
    bicep = bust / 2.0 * 0.35 + ease_sleeve  # approximate bicep from bust
    wrist = bicep * 0.55

    cap_height = bust / 10.0 + 3.0  # sleeve cap height
    length = sleeve_length

    # Sleeve outline (centred on grain):
    # Top centre = (0, 0), cap curves down to side seams,
    # side seams taper to wrist.

    half_bicep = bicep / 2.0
    half_wrist = wrist / 2.0

    # Cap as half-ellipse (approximated)
    cap_pts: list[Point] = []
    for i in range(13):
        t = math.pi * i / 12  # 0 → π
        x = half_bicep * math.cos(math.pi - t)  # left → right
        y = cap_height * math.sin(t)
        cap_pts.append((x, y))

    # Side seams
    right_side = (half_bicep, cap_height)
    right_wrist = (half_wrist, cap_height + length)
    left_wrist = (-half_wrist, cap_height + length)
    left_side = (-half_bicep, cap_height)

    all_pts = (
        cap_pts
        + [right_side, right_wrist, left_wrist, left_side]
        + [cap_pts[0]]
    )

    outline = _close(all_pts)

    grain = ((0.0, cap_height + 2), (0.0, cap_height + length - 2))

    return PatternPiece(
        name="sleeve",
        outline=outline,
        grain_line=grain,
        labels={
            "sleeve_length": sleeve_length,
            "cap_height": cap_height,
            "bicep": bicep,
            "wrist": wrist,
        },
    )


# ------------------------------------------------------------------ #
# Pants front                                                          #
# ------------------------------------------------------------------ #

def pants_front(
    waist: float,
    hip: float,
    inseam: float,
    rise: float,
    *,
    ease_hip: float = 4.0,
    ease_thigh: float = 3.0,
) -> PatternPiece:
    """
    Generate a basic trouser / pants front block.
    """
    half_hip = (hip + ease_hip) / 4.0
    half_waist = waist / 4.0 + 1.0  # 1 cm ease

    crotch_ext = rise / 6.0  # front crotch extension
    thigh = half_hip * 0.55 + ease_thigh / 4.0
    knee = thigh * 0.85
    ankle = thigh * 0.7

    total_length = rise + inseam

    # Origin: top-left (CF waist)
    # Build outline clockwise: CF waist → hip → crotch → inseam → hem → side seam
    x_cf = 0.0
    x_side = half_hip

    y_waist = 0.0
    y_hip = rise * 0.6
    y_crotch = rise
    y_knee = rise + inseam * 0.45
    y_hem = total_length

    # CF side crotch shaping
    crotch_pt = (-crotch_ext, y_crotch)

    # Dart approximation: take in 1.5 cm at waist on CF side
    waist_side = (x_side - (half_hip - half_waist), y_waist)

    outline = _close([
        (x_cf, y_waist),
        (x_cf, y_crotch),
        crotch_pt,
        (-thigh / 2 + crotch_ext * 0.3, y_knee),
        (-ankle / 2, y_hem),
        (ankle / 2, y_hem),
        (thigh / 2, y_knee),
        (x_side, y_crotch),
        (x_side, y_hip),
        waist_side,
        (x_cf, y_waist),
    ])

    grain = ((half_hip / 2, y_waist + 5), (half_hip / 2, y_hem - 5))

    return PatternPiece(
        name="pants_front",
        outline=outline,
        grain_line=grain,
        labels={
            "waist": waist,
            "hip": hip,
            "inseam": inseam,
            "rise": rise,
            "half_hip_with_ease": half_hip,
        },
    )


def pants_back(
    waist: float,
    hip: float,
    inseam: float,
    rise: float,
    *,
    ease_hip: float = 6.0,
    ease_thigh: float = 4.0,
) -> PatternPiece:
    """
    Generate a basic trouser / pants back block.

    Back has more ease and a larger crotch extension than front.
    """
    half_hip = (hip + ease_hip) / 4.0
    half_waist = waist / 4.0 + 1.5

    crotch_ext = rise / 4.0  # back crotch extension (larger than front)
    thigh = half_hip * 0.6 + ease_thigh / 4.0
    ankle = thigh * 0.72

    total_length = rise + inseam

    x_cf = 0.0
    x_side = half_hip
    y_waist = 0.0
    y_hip = rise * 0.6
    y_crotch = rise
    y_knee = rise + inseam * 0.45
    y_hem = total_length

    crotch_pt = (-crotch_ext, y_crotch + rise * 0.05)
    waist_side = (x_side - (half_hip - half_waist), y_waist)

    outline = _close([
        (x_cf, y_waist),
        (x_cf, y_crotch),
        crotch_pt,
        (-thigh / 2 + crotch_ext * 0.3, y_knee),
        (-ankle / 2, y_hem),
        (ankle / 2, y_hem),
        (thigh / 2, y_knee),
        (x_side, y_crotch),
        (x_side, y_hip),
        waist_side,
        (x_cf, y_waist),
    ])

    grain = ((half_hip / 2, y_waist + 5), (half_hip / 2, y_hem - 5))

    return PatternPiece(
        name="pants_back",
        outline=outline,
        grain_line=grain,
        labels={
            "waist": waist,
            "hip": hip,
            "inseam": inseam,
            "rise": rise,
            "half_hip_with_ease": half_hip,
        },
    )
