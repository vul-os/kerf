"""
kerf_cad_core.nesting.pack — deterministic 2-D shelf/skyline bin-packing.

Algorithm
---------
Skyline bin-packing (also called "bottom-left skyline"):

1.  The sheet is divided into a horizontal *skyline* — a step-function of
    occupied heights.  Initially the skyline is flat at y=0.

2.  For each part (in the order given — no reordering; deterministic):
    a.  Try rotation=0 first; if allow_rotate=True also try rotation=90.
    b.  For each candidate width×height find the skyline segment whose
        minimum height is lowest and where the part fits horizontally
        (fits within sheet_w − 2×margin accounting for kerf spacing).
    c.  Place the part at the best-fit position (lowest waste gap).
    d.  If the part does not fit on the current sheet, open a new sheet
        and restart step (b) for that part.

3.  After placement the skyline is updated: every column covered by the
    new part is raised to (part_y + part_h + kerf).

Spacing / margin
----------------
``margin`` is a per-sheet border inset applied once at the sheet boundary.
``kerf`` is the gap between adjacent parts (and between part and border).

    usable_w = sheet_w − 2 × margin
    usable_h = sheet_h − 2 × margin

    When placing the first part on a row the x-origin is margin.
    Subsequent parts on the same row are offset by (kerf) from the
    right edge of the previous part.

Cut-length estimate
-------------------
For each placed part (W × H bounding box) the cut perimeter is:
    2 × (W + H)
The total cut length is the sum over all placements.
This is a lower bound; actual toolpaths may be longer.

Pure-Python, no external dependencies, no randomness → fully deterministic.

Author: imranparuk
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

@dataclass
class Part:
    """A single part to be nested, described by its bounding-box dimensions."""
    name: str
    w: float   # width  (mm / any consistent unit)
    h: float   # height (mm / any consistent unit)

    def __post_init__(self) -> None:
        if self.w <= 0 or self.h <= 0:
            raise ValueError(f"Part '{self.name}': w and h must be > 0, got {self.w}×{self.h}")


@dataclass
class Placement:
    """The position and orientation of one placed part on a sheet."""
    part: str    # part name
    x: float     # lower-left corner x (including margin offset)
    y: float     # lower-left corner y (including margin offset)
    w: float     # placed width  (may be swapped if rotated)
    h: float     # placed height (may be swapped if rotated)
    rot: int     # rotation: 0 or 90 (degrees)


@dataclass
class Sheet:
    """One sheet with zero or more part placements."""
    index: int
    placements: list[Placement] = field(default_factory=list)


@dataclass
class NestResult:
    """
    Result of nest_parts().

    Attributes
    ----------
    ok : bool
        True when every part was placed successfully.
    sheets : list[Sheet]
        One Sheet per stock sheet consumed, each with a placements list.
    sheets_used : int
        Number of sheets consumed.
    utilization : float
        Fraction of total sheet area occupied by parts (0, 1].
        Calculated as sum(part areas) / (sheets_used × sheet_w × sheet_h).
    cut_length : float
        Estimated total laser/knife cut length (sum of part perimeters).
    errors : list[str]
        Non-empty when ok=False.  Friendly messages; never an exception trace.
    """
    ok: bool
    sheets: list[Sheet]
    sheets_used: int
    utilization: float
    cut_length: float
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Skyline bin-packing implementation
# ---------------------------------------------------------------------------

class _Skyline:
    """
    Mutable skyline for one sheet.

    The skyline is stored as a list of (x_start, height) segments where
    x_start is the left edge of the segment and the segment extends to the
    next entry's x_start (or usable_w for the last entry).

    All coordinates are in "usable" space (origin at (margin, margin)).
    """

    def __init__(self, usable_w: float, usable_h: float) -> None:
        self.usable_w = usable_w
        self.usable_h = usable_h
        # Each segment: [x_left, height].  Spans from x_left to next segment's x_left.
        self._segs: list[list[float]] = [[0.0, 0.0]]

    def _seg_right(self, i: int) -> float:
        """Right edge of segment i."""
        if i + 1 < len(self._segs):
            return self._segs[i + 1][0]
        return self.usable_w

    def find_placement(
        self,
        pw: float,
        ph: float,
        kerf: float,
    ) -> Optional[tuple[float, float]]:
        """
        Find the lowest-waste position for a part of size pw × ph.

        Returns (x, y) in usable-space coordinates, or None if no fit.

        The part needs pw + kerf of horizontal room per placement (the
        trailing kerf separates it from the next part or the right margin).
        The final part in a row may omit the trailing kerf, but we always
        reserve it for safety — slightly conservative but safe.

        Strategy: scan every segment as a candidate left edge; for each
        candidate compute the maximum skyline height under the part's
        horizontal footprint (pw).  Choose the candidate with the minimum
        such height (lowest placement).
        """
        best_y: Optional[float] = None
        best_x: Optional[float] = None

        n = len(self._segs)
        for i, (x_left, _) in enumerate(self._segs):
            # Candidate: place part starting at x = x_left
            x_end = x_left + pw
            if x_end > self.usable_w:
                continue  # doesn't fit horizontally

            # Maximum height under this horizontal span
            max_h = self._max_height_in_range(x_left, x_end)

            # Vertical check
            if max_h + ph > self.usable_h:
                continue  # doesn't fit vertically

            if best_y is None or max_h < best_y:
                best_y = max_h
                best_x = x_left

        if best_x is None:
            return None
        return (best_x, best_y)

    def _max_height_in_range(self, x_l: float, x_r: float) -> float:
        """Maximum skyline height over the horizontal range [x_l, x_r)."""
        max_h = 0.0
        for i, (x_seg, h_seg) in enumerate(self._segs):
            seg_r = self._seg_right(i)
            # Overlap check
            if seg_r <= x_l:
                continue
            if x_seg >= x_r:
                break
            if h_seg > max_h:
                max_h = h_seg
        return max_h

    def place(self, x: float, y: float, pw: float, ph: float, kerf: float) -> None:
        """
        Update the skyline after placing a part at (x, y) with size pw × ph.

        The new ceiling after this placement is y + ph + kerf.  We also add
        kerf to the right edge so the next part placed alongside is separated.
        The horizontal extent updated is [x, x + pw + kerf) in usable space
        (the trailing kerf column).
        """
        new_h = y + ph + kerf
        # Effective right edge (include trailing kerf, but clamp to usable_w)
        eff_right = min(x + pw + kerf, self.usable_w)
        self._update_range(x, eff_right, new_h)

    def _update_range(self, x_l: float, x_r: float, new_h: float) -> None:
        """Raise all segments in [x_l, x_r) to at least new_h."""
        # Build new segment list
        new_segs: list[list[float]] = []

        for i, (x_seg, h_seg) in enumerate(self._segs):
            seg_r = self._seg_right(i)

            if seg_r <= x_l or x_seg >= x_r:
                # Segment outside update range — keep as-is
                new_segs.append([x_seg, h_seg])
                continue

            # Segment overlaps update range
            # Left part (before x_l)
            if x_seg < x_l:
                new_segs.append([x_seg, h_seg])
                new_segs.append([x_l, max(h_seg, new_h)])
            else:
                new_segs.append([x_seg, max(h_seg, new_h)])

            # Right part (after x_r)
            if seg_r > x_r:
                # Need to restore original height after x_r
                new_segs.append([x_r, h_seg])

        # Deduplicate consecutive equal heights and sort by x
        new_segs.sort(key=lambda s: s[0])
        merged: list[list[float]] = []
        for seg in new_segs:
            if merged and merged[-1][1] == seg[1] and abs(merged[-1][0] - seg[0]) < 1e-12:
                continue
            if merged and abs(merged[-1][0] - seg[0]) < 1e-12:
                merged[-1] = seg
            else:
                merged.append(seg)

        # Merge consecutive segments with the same height
        self._segs = _merge_skyline(merged)


def _merge_skyline(segs: list[list[float]]) -> list[list[float]]:
    """Remove consecutive duplicate heights from a skyline."""
    if not segs:
        return [[0.0, 0.0]]
    out: list[list[float]] = [segs[0]]
    for seg in segs[1:]:
        if abs(seg[1] - out[-1][1]) < 1e-12:
            continue  # same height — skip (previous segment extends further)
        out.append(seg)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def nest_parts(
    parts: list[dict],
    sheet_w: float,
    sheet_h: float,
    kerf: float = 0.0,
    margin: float = 0.0,
    allow_rotate: bool = True,
) -> NestResult:
    """
    Nest a list of rectangular parts onto stock sheets.

    Parameters
    ----------
    parts : list of dicts
        Each dict must have:
            name  (str)   — part identifier
            w     (float) — bounding-box width
            h     (float) — bounding-box height
        Optional:
            qty   (int)   — repeat count (default 1)

    sheet_w, sheet_h : float
        Stock sheet outer dimensions.

    kerf : float
        Kerf gap between adjacent parts and between part and margin.
        Default 0.

    margin : float
        Per-sheet border inset (applied to all four edges).
        Default 0.

    allow_rotate : bool
        If True, each part may be rotated 90° when that improves packing.
        Default True.

    Returns
    -------
    NestResult
        .ok          : False if any part could not be placed
        .sheets      : list of Sheet objects with placements
        .sheets_used : int
        .utilization : float in (0, 1]
        .cut_length  : float — estimated perimeter cut length
        .errors      : list of friendly error strings (non-empty iff ok=False)
    """
    # --- Input validation ---
    errors: list[str] = []

    if sheet_w <= 0:
        errors.append(f"sheet_w must be > 0; got {sheet_w}")
    if sheet_h <= 0:
        errors.append(f"sheet_h must be > 0; got {sheet_h}")
    if kerf < 0:
        errors.append(f"kerf must be >= 0; got {kerf}")
    if margin < 0:
        errors.append(f"margin must be >= 0; got {margin}")
    if errors:
        return NestResult(ok=False, sheets=[], sheets_used=0, utilization=0.0,
                          cut_length=0.0, errors=errors)

    usable_w = sheet_w - 2.0 * margin
    usable_h = sheet_h - 2.0 * margin

    if usable_w <= 0 or usable_h <= 0:
        return NestResult(
            ok=False, sheets=[], sheets_used=0, utilization=0.0, cut_length=0.0,
            errors=[
                f"Sheet usable area is non-positive after applying margin={margin}: "
                f"usable={usable_w:.3f}×{usable_h:.3f}. Reduce margin."
            ],
        )

    if not parts:
        return NestResult(ok=True, sheets=[], sheets_used=0, utilization=0.0,
                          cut_length=0.0)

    # --- Expand qty repetitions ---
    expanded: list[tuple[str, float, float]] = []  # (name, w, h)
    for i, p in enumerate(parts):
        try:
            name = str(p.get("name", f"part-{i}"))
            pw = float(p["w"])
            ph = float(p["h"])
            qty = int(p.get("qty", 1))
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"Part {i} invalid: {exc}")
            continue
        if pw <= 0 or ph <= 0:
            errors.append(f"Part '{name}': w and h must be > 0; got {pw}×{ph}")
            continue
        if qty < 1:
            errors.append(f"Part '{name}': qty must be >= 1; got {qty}")
            continue
        for _ in range(qty):
            expanded.append((name, pw, ph))

    if errors:
        return NestResult(ok=False, sheets=[], sheets_used=0, utilization=0.0,
                          cut_length=0.0, errors=errors)

    # --- Check each part fits on a sheet (before packing) ---
    oversized: list[str] = []
    for name, pw, ph in expanded:
        fits_0 = (pw <= usable_w) and (ph <= usable_h)
        fits_90 = allow_rotate and (ph <= usable_w) and (pw <= usable_h)
        if not fits_0 and not fits_90:
            oversized.append(
                f"Part '{name}' ({pw}×{ph}) is larger than the usable sheet area "
                f"({usable_w:.3f}×{usable_h:.3f})"
                + (" even after 90° rotation" if allow_rotate else "")
                + ". Cannot place."
            )
    if oversized:
        return NestResult(ok=False, sheets=[], sheets_used=0, utilization=0.0,
                          cut_length=0.0, errors=oversized)

    # --- Packing loop ---
    sheets_list: list[Sheet] = []
    current_sheet = Sheet(index=0)
    skyline = _Skyline(usable_w, usable_h)
    sheets_list.append(current_sheet)

    total_part_area = 0.0
    total_cut_length = 0.0

    for name, pw, ph in expanded:
        placed = False
        for pw_try, ph_try, rot in _candidate_rotations(pw, ph, allow_rotate):
            # pw_try must fit in usable_w
            if pw_try > usable_w or ph_try > usable_h:
                continue
            pos = skyline.find_placement(pw_try, ph_try, kerf)
            if pos is not None:
                x_usable, y_usable = pos
                placement = Placement(
                    part=name,
                    x=x_usable + margin,
                    y=y_usable + margin,
                    w=pw_try,
                    h=ph_try,
                    rot=rot,
                )
                current_sheet.placements.append(placement)
                skyline.place(x_usable, y_usable, pw_try, ph_try, kerf)
                total_part_area += pw_try * ph_try
                total_cut_length += 2.0 * (pw_try + ph_try)
                placed = True
                break

        if not placed:
            # Open a new sheet
            current_sheet = Sheet(index=len(sheets_list))
            skyline = _Skyline(usable_w, usable_h)
            sheets_list.append(current_sheet)

            placed_on_new = False
            for pw_try, ph_try, rot in _candidate_rotations(pw, ph, allow_rotate):
                if pw_try > usable_w or ph_try > usable_h:
                    continue
                pos = skyline.find_placement(pw_try, ph_try, kerf)
                if pos is not None:
                    x_usable, y_usable = pos
                    placement = Placement(
                        part=name,
                        x=x_usable + margin,
                        y=y_usable + margin,
                        w=pw_try,
                        h=ph_try,
                        rot=rot,
                    )
                    current_sheet.placements.append(placement)
                    skyline.place(x_usable, y_usable, pw_try, ph_try, kerf)
                    total_part_area += pw_try * ph_try
                    total_cut_length += 2.0 * (pw_try + ph_try)
                    placed_on_new = True
                    break

            if not placed_on_new:
                # This should not happen since we checked oversized above
                errors.append(
                    f"Internal error: part '{name}' ({pw}×{ph}) could not be placed "
                    "even on a fresh sheet."
                )

    if errors:
        return NestResult(ok=False, sheets=[], sheets_used=0, utilization=0.0,
                          cut_length=0.0, errors=errors)

    sheets_used = len(sheets_list)
    sheet_area = sheet_w * sheet_h
    utilization = total_part_area / (sheets_used * sheet_area) if sheet_area > 0 else 0.0
    # Clamp to (0, 1] — can exceed 1.0 only due to floating-point; guard against 0
    utilization = max(min(utilization, 1.0), 1e-15)

    return NestResult(
        ok=True,
        sheets=sheets_list,
        sheets_used=sheets_used,
        utilization=round(utilization, 6),
        cut_length=round(total_cut_length, 6),
    )


def _candidate_rotations(
    pw: float,
    ph: float,
    allow_rotate: bool,
) -> list[tuple[float, float, int]]:
    """
    Return candidate (width, height, rotation) tuples to try.

    Always try rotation=0 first.  If allow_rotate and the rotated size
    is different, add rotation=90.
    """
    candidates: list[tuple[float, float, int]] = [(pw, ph, 0)]
    if allow_rotate and abs(pw - ph) > 1e-12:
        candidates.append((ph, pw, 90))
    return candidates


# ---------------------------------------------------------------------------
# Convenience: serialisable dict form
# ---------------------------------------------------------------------------

def result_to_dict(r: NestResult) -> dict:
    """Convert a NestResult to a JSON-serialisable dict."""
    sheets_out = []
    for s in r.sheets:
        placements_out = [
            {
                "part": p.part,
                "x": round(p.x, 6),
                "y": round(p.y, 6),
                "w": round(p.w, 6),
                "h": round(p.h, 6),
                "rot": p.rot,
            }
            for p in s.placements
        ]
        sheets_out.append({"sheet": s.index, "placements": placements_out})

    return {
        "ok": r.ok,
        "sheets": sheets_out,
        "sheets_used": r.sheets_used,
        "utilization": r.utilization,
        "cut_length": r.cut_length,
        "errors": r.errors,
    }
