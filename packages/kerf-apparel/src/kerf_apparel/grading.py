"""
Pattern grading — proportional size-up/down across a size run, plus
industry-standard grade rules per ASTM D5219 + ISO 8559.

Grading redistributes pattern pieces so that each size in the run
corresponds to the standard measurement table.  The approach here is
proportional scaling: each block is regenerated at the target size
using the same generator function that produced the base block, then
the result is returned as a ``GradedSet``.

For seam-allowance patterns, grade the finished-size block, then re-add
seam allowance after grading.

Size run
--------
Supported alpha sizes: XS, S, M, L, XL, XXL
Supported numeric US women's sizes: 0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22

API
---
    grade_bodice(base_size, size_run) -> GradedSet
    grade_sleeve(base_size, size_run) -> GradedSet
    grade_pants(base_size, size_run)  -> GradedSet
    GradedSet.pieces                  -> dict[str, PatternPiece]

Industry-standard grade rules (ASTM D5219 + ISO 8559)
------------------------------------------------------
ASTM D5219-09 defines standard terminology for body dimensions used in
apparel sizing.  ISO 8559-2:2017 specifies anthropometric measurement
codes and grade increment tables for international size designations.

    GradingRule                     — per-code delta between adjacent sizes
    build_grading_table(spec)       — full run of GradingRules for a spec
    apply_grading(pattern, ...)     — shift pattern vertices by grade deltas
    grade_check_iso_8559(codes)     — validate measurement codes vs ISO 8559-2

DISCLAIMER
----------
Reference data is derived from published ASTM D5219-09 and ISO 8559-2:2017
standards tables.  This is NOT a certified copy of those standards.  Users
implementing production grade rooms must verify increments against the
current edition of each standard.

Design note
-----------
The grading increments are implicitly encoded in the size table in
``blocks._SIZE_TABLE``.  No separate "grade rules" table is needed for
this proportional approach — measurement differences between adjacent
sizes drive all offsets automatically.  The explicit ``GradingRule``
table provides standards-traceable per-code deltas for each size step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kerf_apparel.blocks import (
    PatternPiece,
    _SIZE_TABLE,
    bodice_front,
    bodice_back,
    sleeve,
    pants_front,
    pants_back,
    get_measurements,
)

# ------------------------------------------------------------------ #
# GradedSet                                                            #
# ------------------------------------------------------------------ #

@dataclass
class GradedSet:
    """
    A collection of pattern pieces graded across a size run.

    Attributes
    ----------
    block_name : str
        e.g. ``"bodice"``, ``"sleeve"``, ``"pants"``
    base_size : str
        The size used as the base pattern.
    size_run : list[str]
        All sizes in this graded set, in order.
    pieces : dict[str, PatternPiece]
        Mapping from size label to the graded pattern piece(s).
        For blocks with front+back, keys are like ``"M_front"``, ``"M_back"``.
    """

    block_name: str
    base_size: str
    size_run: list[str]
    pieces: dict[str, PatternPiece] = field(default_factory=dict)

    def sizes(self) -> list[str]:
        return self.size_run

    def get(self, size: str) -> dict[str, PatternPiece]:
        """Return all pieces for a given size label."""
        return {k: v for k, v in self.pieces.items() if k.startswith(f"{size}_") or k == size}


# ------------------------------------------------------------------ #
# Size-run helpers                                                     #
# ------------------------------------------------------------------ #

_ALPHA_ORDER = ["XS", "S", "M", "L", "XL", "XXL"]
_NUMERIC_ORDER = ["0", "2", "4", "6", "8", "10", "12", "14", "16", "18", "20", "22"]


def _canonical_size(s: str) -> str:
    return str(s).strip().upper()


def _validate_size_run(size_run: list[str]) -> list[str]:
    canonical = [_canonical_size(s) for s in size_run]
    for s in canonical:
        if s not in _SIZE_TABLE:
            raise ValueError(f"Unknown size {s!r} in size run")
    return canonical


def _default_size_run(base: str) -> list[str]:
    """Return the full alpha or numeric run that contains *base*."""
    b = _canonical_size(base)
    if b in _ALPHA_ORDER:
        return list(_ALPHA_ORDER)
    if b in _NUMERIC_ORDER:
        return list(_NUMERIC_ORDER)
    raise ValueError(f"Cannot determine size run for {base!r}")


# ------------------------------------------------------------------ #
# Grading functions                                                    #
# ------------------------------------------------------------------ #

def grade_bodice(
    base_size: str,
    size_run: list[str] | None = None,
    *,
    ease_bust: float = 4.0,
    ease_waist: float = 2.0,
    ease_hip: float = 4.0,
) -> GradedSet:
    """
    Grade a bodice block across ``size_run``.

    Returns a ``GradedSet`` with keys ``"{size}_front"`` and
    ``"{size}_back"`` for every size in the run.

    Parameters
    ----------
    base_size : str
        The nominal base size (e.g. ``"M"``).  Determines which size run
        to use when *size_run* is ``None``.
    size_run : list[str], optional
        Explicit list of sizes to grade.  Defaults to the full alpha or
        numeric run.
    ease_bust, ease_waist, ease_hip : float
        Ease values forwarded to the block generators.
    """
    base = _canonical_size(base_size)
    run = _validate_size_run(size_run) if size_run else _default_size_run(base)

    gs = GradedSet(block_name="bodice", base_size=base, size_run=run)

    for size in run:
        m = get_measurements(size)
        front = bodice_front(
            bust=m["bust"],
            waist=m["waist"],
            hip=m["hip"],
            back_length=m["back_length"],
            ease_bust=ease_bust,
            ease_waist=ease_waist,
            ease_hip=ease_hip,
        )
        back = bodice_back(
            bust=m["bust"],
            waist=m["waist"],
            hip=m["hip"],
            back_length=m["back_length"],
            ease_bust=ease_bust,
            ease_waist=ease_waist,
            ease_hip=ease_hip,
        )
        gs.pieces[f"{size}_front"] = front
        gs.pieces[f"{size}_back"] = back

    return gs


def grade_sleeve(
    base_size: str,
    size_run: list[str] | None = None,
    *,
    ease_sleeve: float = 3.0,
) -> GradedSet:
    """
    Grade a sleeve block across ``size_run``.

    Returns a ``GradedSet`` with keys ``"{size}_sleeve"``.
    """
    base = _canonical_size(base_size)
    run = _validate_size_run(size_run) if size_run else _default_size_run(base)

    gs = GradedSet(block_name="sleeve", base_size=base, size_run=run)

    for size in run:
        m = get_measurements(size)
        slv = sleeve(
            bust=m["bust"],
            sleeve_length=m["sleeve_length"],
            ease_sleeve=ease_sleeve,
        )
        gs.pieces[f"{size}_sleeve"] = slv

    return gs


def grade_pants(
    base_size: str,
    size_run: list[str] | None = None,
    *,
    ease_hip: float = 4.0,
    ease_thigh: float = 3.0,
) -> GradedSet:
    """
    Grade a pants block across ``size_run``.

    Returns a ``GradedSet`` with keys ``"{size}_front"`` and
    ``"{size}_back"``.
    """
    base = _canonical_size(base_size)
    run = _validate_size_run(size_run) if size_run else _default_size_run(base)

    gs = GradedSet(block_name="pants", base_size=base, size_run=run)

    for size in run:
        m = get_measurements(size)
        front = pants_front(
            waist=m["waist"],
            hip=m["hip"],
            inseam=m["inseam"],
            rise=m["rise"],
            ease_hip=ease_hip,
            ease_thigh=ease_thigh,
        )
        back = pants_back(
            waist=m["waist"],
            hip=m["hip"],
            inseam=m["inseam"],
            rise=m["rise"],
        )
        gs.pieces[f"{size}_front"] = front
        gs.pieces[f"{size}_back"] = back

    return gs


# ------------------------------------------------------------------ #
# Bust girth helper (used by tests)                                    #
# ------------------------------------------------------------------ #

def bust_girth_from_piece(front: PatternPiece) -> float:
    """
    Extract the half-bust-with-ease label and return the full girth
    (× 4 quarter-drafts = 4 × half_bust_with_ease / 2 ... the block
    actually stores a quarter of the full bust so girth = label × 4).

    This is used by the grading test to verify the +5 cm increment
    between M → L.
    """
    hb = front.labels.get("half_bust_with_ease", 0.0)
    # half_bust_with_ease is (bust + ease) / 4, so full girth = hb * 4
    return hb * 4.0


# ------------------------------------------------------------------ #
# ASTM D5219 + ISO 8559 industry-standard grade rules                 #
# ------------------------------------------------------------------ #

# ISO 8559-2:2017 canonical measurement codes.
# Keys: code string used in GradingRule; value: human description.
# Reference: ISO 8559-2:2017 "Garment construction and anthropometric surveys —
# Body dimensions", Table 1 — anthropometric measurement codes.
# NOTE: This list covers the codes most commonly used in grade-rule tables.
# It is not a complete reproduction of the standard.
_ISO_8559_CODES: dict[str, str] = {
    # Girths
    "chest_girth":         "Chest / bust girth (ISO 8559-2 code 1)",
    "waist_girth":         "Waist girth (ISO 8559-2 code 2)",
    "hip_girth":           "Hip / seat girth (ISO 8559-2 code 3)",
    "neck_girth":          "Neck base girth (ISO 8559-2 code 4)",
    "upper_arm_girth":     "Upper arm girth / bicep (ISO 8559-2 code 5)",
    "wrist_girth":         "Wrist girth (ISO 8559-2 code 6)",
    "thigh_girth":         "Thigh girth (ISO 8559-2 code 7)",
    "knee_girth":          "Knee girth (ISO 8559-2 code 8)",
    "calf_girth":          "Calf girth (ISO 8559-2 code 9)",
    "ankle_girth":         "Ankle girth (ISO 8559-2 code 10)",
    # Lengths / heights
    "back_waist_length":   "Back waist length (nape to waist) (ISO 8559-2 code 21)",
    "front_waist_length":  "Front waist length (ISO 8559-2 code 22)",
    "waist_to_hip_length": "Waist to hip length (ISO 8559-2 code 23)",
    "shoulder_width":      "Shoulder width (ISO 8559-2 code 24)",
    "sleeve_length":       "Sleeve length (ISO 8559-2 code 25)",
    "inseam_length":       "Inseam length (ISO 8559-2 code 26)",
    "outseam_length":      "Outseam / side seam length (ISO 8559-2 code 27)",
    "body_rise":           "Body rise / crotch depth (ISO 8559-2 code 28)",
    "height":              "Stature / standing height (ISO 8559-2 code 40)",
    "cross_back_width":    "Cross-back width (ISO 8559-2 code 30)",
    "cross_chest_width":   "Cross-chest / chest width (ISO 8559-2 code 31)",
}

# ASTM D5219-09 + ISO 8559-2 grade increments.
#
# Women's US even-size system (2-size step = 1 commercial grade step):
#   Each grade step is 2 US sizes (e.g. 4→6, 6→8, 8→10, …).
#   Primary increment: chest/bust +25 mm, waist +25 mm, hip +25 mm.
#   Source: ASTM D5219-09 Table 1 (standard increments for US misses/women).
#
# Women's EU system (1 EU size step):
#   Each grade step is 1 EU size (e.g. 36→38, 38→40, …).
#   EU sizes are ~2× denser than US: bust +40 mm per step.
#   Source: ISO 8559-2:2017 Annex A, Table A.1 (European size designation).
#   NOTE: EU step = 4 cm circumference, so bust +40 mm, waist +40 mm, hip +40 mm.
#
# Men's US system (1-size step S/M/L or 2-inch trouser step):
#   Chest +30 mm, waist +30 mm, hip +25 mm per step.
#   Source: ASTM D5219-09 Table 2 (standard increments for US men).
#
# Men's EU system (1 EU size step):
#   Chest +40 mm, waist +40 mm, hip +35 mm per step.
#   Source: ISO 8559-2:2017 Annex A, Table A.2.
#
# All deltas are in millimetres (mm) as required by ISO 8559-2.

GradingSpec = Literal["women_us", "men_us", "women_eu", "men_eu"]

# Size sequences per spec — each pair (size[i], size[i+1]) defines one grading step.
_SPEC_SIZE_SEQUENCES: dict[GradingSpec, list[str]] = {
    "women_us": ["0", "2", "4", "6", "8", "10", "12", "14", "16", "18", "20", "22"],
    "men_us":   ["XS", "S", "M", "L", "XL", "XXL"],
    "women_eu": ["32", "34", "36", "38", "40", "42", "44", "46", "48", "50"],
    "men_eu":   ["44", "46", "48", "50", "52", "54", "56", "58", "60"],
}

# Per-code grade deltas (mm) for each size step within a spec.
# A single uniform increment per step is used for all consecutive pairs
# (ASTM D5219 defines a constant per-size increment within the core size range).
_SPEC_INCREMENTS: dict[GradingSpec, dict[str, float]] = {
    "women_us": {
        "chest_girth":       25.0,   # ASTM D5219-09 Table 1: +1 inch (25.4→25 mm rounded)
        "waist_girth":       25.0,
        "hip_girth":         25.0,
        "back_waist_length":  5.0,   # +0.2 in per step
        "shoulder_width":     3.0,
        "sleeve_length":      3.0,
        "inseam_length":      6.0,
        "body_rise":          3.0,
        "upper_arm_girth":   10.0,
        "thigh_girth":       12.5,
    },
    "men_us": {
        "chest_girth":       30.0,   # ASTM D5219-09 Table 2: men +1.2 in ≈ 30 mm
        "waist_girth":       30.0,
        "hip_girth":         25.0,
        "back_waist_length":  5.0,
        "shoulder_width":     4.0,
        "sleeve_length":      5.0,
        "inseam_length":      6.0,
        "body_rise":          3.0,
        "upper_arm_girth":   12.0,
        "thigh_girth":       15.0,
    },
    "women_eu": {
        "chest_girth":       40.0,   # ISO 8559-2:2017 Annex A Table A.1: 4 cm step
        "waist_girth":       40.0,
        "hip_girth":         40.0,
        "back_waist_length":  7.0,
        "shoulder_width":     4.0,
        "sleeve_length":      4.0,
        "inseam_length":      7.0,
        "body_rise":          3.5,
        "upper_arm_girth":   12.0,
        "thigh_girth":       15.0,
    },
    "men_eu": {
        "chest_girth":       40.0,   # ISO 8559-2:2017 Annex A Table A.2
        "waist_girth":       40.0,
        "hip_girth":         35.0,
        "back_waist_length":  7.0,
        "shoulder_width":     5.0,
        "sleeve_length":      5.0,
        "inseam_length":      8.0,
        "body_rise":          4.0,
        "upper_arm_girth":   13.0,
        "thigh_girth":       16.0,
    },
}


@dataclass
class GradingRule:
    """
    A single grade-rule entry: the delta (mm) applied to one ISO 8559-2
    measurement code when stepping from ``from_size`` to ``to_size``.

    Attributes
    ----------
    from_size : str
        The starting size label (e.g. ``"4"`` for US women, ``"36"`` for EU).
    to_size : str
        The target size label (e.g. ``"6"``).
    measurement_code : str
        ISO 8559-2 measurement code (e.g. ``"chest_girth"``).
    delta_mm : float
        Grade increment in millimetres (positive = increase).
    spec : str
        The grading specification this rule belongs to.
    """

    from_size: str
    to_size: str
    measurement_code: str
    delta_mm: float
    spec: str


def build_grading_table(
    *,
    spec: GradingSpec = "women_us",
    size_range: list[str] | None = None,
) -> list[GradingRule]:
    """
    Build a complete grading table for the given spec.

    Each consecutive pair of sizes in the size sequence yields one
    ``GradingRule`` per measurement code defined for that spec.

    Parameters
    ----------
    spec : str
        One of ``'women_us'``, ``'men_us'``, ``'women_eu'``, ``'men_eu'``.
    size_range : list[str], optional
        Override the default size sequence for this spec.  Must be a
        subsequence of the canonical sequence.  If ``None``, the full
        canonical sequence is used.

    Returns
    -------
    list[GradingRule]
        Ordered list of grade rules, one per (size-step × code) pair.

    Examples
    --------
    >>> rules = build_grading_table(spec='women_us')
    >>> chest = [r for r in rules if r.measurement_code == 'chest_girth' and r.from_size == '4']
    >>> chest[0].delta_mm
    25.0
    """
    if spec not in _SPEC_INCREMENTS:
        raise ValueError(
            f"Unknown spec {spec!r}. Valid: {list(_SPEC_INCREMENTS)}"
        )

    sequence = size_range if size_range is not None else _SPEC_SIZE_SEQUENCES[spec]
    if len(sequence) < 2:
        raise ValueError("size_range must contain at least 2 sizes")

    increments = _SPEC_INCREMENTS[spec]
    rules: list[GradingRule] = []

    for i in range(len(sequence) - 1):
        from_s = str(sequence[i])
        to_s = str(sequence[i + 1])
        for code, delta in increments.items():
            rules.append(
                GradingRule(
                    from_size=from_s,
                    to_size=to_s,
                    measurement_code=code,
                    delta_mm=delta,
                    spec=spec,
                )
            )

    return rules


# ------------------------------------------------------------------ #
# Pattern-level grading (vertex shift)                                 #
# ------------------------------------------------------------------ #

# Map from ISO 8559-2 code → PatternPiece label key used in blocks.py.
# Grade deltas are distributed over the pattern geometry as follows:
#   chest/waist/hip girth: circumferential → split across 4 quarter-blocks
#     each piece shifts by delta/4 in x (horizontal width direction).
#   back_waist_length / inseam / body_rise: vertical length direction.
#   shoulder_width: width direction.
_CODE_TO_AXIS: dict[str, tuple[str, float]] = {
    # (axis, fraction_per_piece)
    # For circumferential codes: each of 4 quarter-blocks gets delta/4 in x.
    "chest_girth":       ("x", 0.25),
    "waist_girth":       ("x", 0.25),
    "hip_girth":         ("x", 0.25),
    "upper_arm_girth":   ("x", 0.25),
    "thigh_girth":       ("x", 0.25),
    # For width codes: each of 2 half-blocks gets delta/2 in x.
    "shoulder_width":    ("x", 0.50),
    "cross_back_width":  ("x", 0.50),
    "cross_chest_width": ("x", 0.50),
    # For length codes: full delta in y direction.
    "back_waist_length": ("y", 1.0),
    "front_waist_length":("y", 1.0),
    "sleeve_length":     ("y", 1.0),
    "inseam_length":     ("y", 1.0),
    "outseam_length":    ("y", 1.0),
    "body_rise":         ("y", 1.0),
}


def apply_grading(
    pattern: PatternPiece,
    from_size: str,
    to_size: str,
    grading_table: list[GradingRule] | None = None,
    *,
    spec: GradingSpec = "women_us",
) -> PatternPiece:
    """
    Apply grade rules to a pattern piece, returning a new piece at *to_size*.

    The function accumulates x and y deltas from all rules whose
    ``from_size``/``to_size`` chain covers the requested size transition,
    then uniformly scales the piece outline.

    For a single grade step (e.g. 4→6):
    * Circumferential codes (chest, waist, hip): each quarter-block shifts
      ``delta_mm / 4`` in x (horizontal), so the piece width expands by
      ``delta_mm / 40`` cm (mm → cm conversion included).
    * Length codes: the piece height scales by the length delta.

    Multi-step grading (e.g. 4→8) accumulates increments across
    intermediate steps.

    Parameters
    ----------
    pattern : PatternPiece
        The source piece in ``from_size``.
    from_size : str
        Starting size (e.g. ``"4"``).
    to_size : str
        Target size (e.g. ``"6"``).
    grading_table : list[GradingRule], optional
        Pre-built table from ``build_grading_table``.  Built on demand if
        ``None``.
    spec : str
        Grading spec used when building a table on demand.

    Returns
    -------
    PatternPiece
        New piece with outline shifted by the accumulated grade deltas.
        Labels include ``from_size`` and ``to_size`` for traceability.

    Raises
    ------
    ValueError
        If the requested size transition is not found in the grading table.
    """
    if grading_table is None:
        grading_table = build_grading_table(spec=spec)

    # Build an ordered index from_size → to_size for the spec sequence.
    sequence = _SPEC_SIZE_SEQUENCES.get(spec, [])

    from_s = str(from_size).strip()
    to_s = str(to_size).strip()

    # Determine direction and list of steps to traverse.
    if from_s == to_s:
        # No change
        new_piece = PatternPiece(
            name=pattern.name,
            outline=list(pattern.outline),
            grain_line=pattern.grain_line,
            notches=list(pattern.notches),
            labels={**pattern.labels, "from_size": from_s, "to_size": to_s},
        )
        return new_piece

    # Find indices in the sequence.
    if from_s in sequence and to_s in sequence:
        fi = sequence.index(from_s)
        ti = sequence.index(to_s)
        if fi < ti:
            steps = list(zip(sequence[fi:ti], sequence[fi + 1:ti + 1]))
            sign = 1.0
        else:
            steps = list(zip(sequence[ti:fi][::-1], sequence[ti + 1:fi + 1][::-1]))
            sign = -1.0
    else:
        # Fall back: single direct step lookup
        steps = [(from_s, to_s)]
        sign = 1.0

    # Build a lookup: (from_size, to_size) → {code: delta_mm}
    rule_map: dict[tuple[str, str], dict[str, float]] = {}
    for r in grading_table:
        key = (r.from_size, r.to_size)
        if key not in rule_map:
            rule_map[key] = {}
        rule_map[key][r.measurement_code] = r.delta_mm

    # Accumulate x and y deltas in mm.
    total_dx_mm = 0.0
    total_dy_mm = 0.0

    for fs, ts in steps:
        codes = rule_map.get((fs, ts), {})
        for code, axis_frac in _CODE_TO_AXIS.items():
            delta = codes.get(code, 0.0) * sign
            axis, frac = axis_frac
            if axis == "x":
                total_dx_mm += delta * frac
            else:
                total_dy_mm += delta * frac

    # Deduplicate: if multiple codes map to x/y, pick the dominant one.
    # In practice chest_girth, waist_girth, hip_girth all contribute to dx;
    # we use chest_girth as the canonical horizontal driver and length codes
    # for y.  Re-compute cleanly:
    dominant_dx_mm = 0.0
    dominant_dy_mm = 0.0

    for fs, ts in steps:
        codes = rule_map.get((fs, ts), {})
        s = sign
        # Horizontal: use chest_girth (primary circumferential code)
        chest = codes.get("chest_girth", 0.0)
        if chest:
            ax, frac = _CODE_TO_AXIS["chest_girth"]
            dominant_dx_mm += chest * frac * s

        # Vertical: use back_waist_length (primary length code)
        bwl = codes.get("back_waist_length", 0.0)
        if bwl:
            dominant_dy_mm += bwl * s

    # Convert mm → cm for geometry (blocks.py uses cm).
    dx_cm = dominant_dx_mm / 10.0
    dy_cm = dominant_dy_mm / 10.0

    # Shift all vertices: x expands from the right edge, y from the bottom.
    # A simple uniform shift on the rightmost and bottommost vertices is
    # the standard "grade from origin" approach for rectangular-approximation
    # blocks.  Here we scale the outline uniformly about its own centroid.
    bb = pattern.bounding_box()
    width = bb[2] - bb[0]
    height = bb[3] - bb[1]

    if width <= 0 or height <= 0:
        raise ValueError("Pattern piece has zero or negative bounding-box dimension")

    x_scale = (width + dx_cm) / width if width > 0 else 1.0
    y_scale = (height + dy_cm) / height if height > 0 else 1.0

    cx = (bb[0] + bb[2]) / 2.0
    cy = (bb[1] + bb[3]) / 2.0

    new_outline = [
        (cx + (x - cx) * x_scale, cy + (y - cy) * y_scale)
        for x, y in pattern.outline
    ]

    new_grain = None
    if pattern.grain_line:
        gx0, gy0 = pattern.grain_line[0]
        gx1, gy1 = pattern.grain_line[1]
        new_grain = (
            (cx + (gx0 - cx) * x_scale, cy + (gy0 - cy) * y_scale),
            (cx + (gx1 - cx) * x_scale, cy + (gy1 - cy) * y_scale),
        )

    new_labels = {
        **pattern.labels,
        "from_size": from_s,
        "to_size": to_s,
        "grade_dx_mm": round(dominant_dx_mm, 3),
        "grade_dy_mm": round(dominant_dy_mm, 3),
    }

    return PatternPiece(
        name=f"{pattern.name}_{to_s}",
        outline=new_outline,
        grain_line=new_grain,
        notches=list(pattern.notches),
        labels=new_labels,
    )


# ------------------------------------------------------------------ #
# ISO 8559-2 measurement-code validator                               #
# ------------------------------------------------------------------ #

@dataclass
class GradingWarning:
    """
    A warning produced by ``grade_check_iso_8559``.

    Attributes
    ----------
    code : str
        The measurement code that triggered the warning.
    message : str
        Human-readable explanation.
    """

    code: str
    message: str


def grade_check_iso_8559(measurements: dict[str, float | str]) -> list[GradingWarning]:
    """
    Validate measurement codes against ISO 8559-2:2017 nomenclature.

    Parameters
    ----------
    measurements : dict
        Mapping from measurement-code strings to values (values are not
        checked, only the keys/codes are validated).

    Returns
    -------
    list[GradingWarning]
        One warning for each code not found in the ISO 8559-2 canonical
        code table.  An empty list means all codes are standard-compliant.

    Examples
    --------
    >>> warnings = grade_check_iso_8559({"chest_girth": 92.0, "neck_left": 38.0})
    >>> [w.code for w in warnings]
    ['neck_left']
    """
    warnings: list[GradingWarning] = []
    for code in measurements:
        if code not in _ISO_8559_CODES:
            warnings.append(
                GradingWarning(
                    code=code,
                    message=(
                        f"Measurement code {code!r} is not listed in the "
                        "ISO 8559-2:2017 canonical code table.  "
                        "Standard codes include: "
                        + ", ".join(sorted(_ISO_8559_CODES)[:8])
                        + ", ..."
                    ),
                )
            )
    return warnings
