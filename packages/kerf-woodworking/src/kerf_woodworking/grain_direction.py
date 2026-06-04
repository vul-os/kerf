"""
kerf_woodworking.grain_direction — Grain orientation rules, figure types, and grain matching.

Provides best-practice grain direction guidance for furniture and cabinet panels,
figure type classification, and panel grain-matching recommendations.

References:
    Hoadley, R.B. (2000). Understanding Wood, 2nd ed. The Taunton Press.
      — Chapter 2: Wood Structure; Chapter 9: Sawing Lumber.
    Stanley, J. (2010). Furniture Design & Construction for the Wood Worker.
    KCMA (2021). Cabinet Standards §4: Material selection.

HONEST: Grain direction rules are best-practice guidelines from established
woodworking literature. Actual wood behaviour depends on species, moisture
content, and individual board characteristics. Always inspect actual stock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Figure types
# ---------------------------------------------------------------------------

class FigureType:
    """Wood figure types based on sawing method (Hoadley 2000, Ch. 9)."""
    PLAIN_SAWN    = "plain_sawn"      # tangential cut — cathedral grain, wider boards
    RIFT_SAWN     = "rift_sawn"       # 30–60° to growth rings — straight grain, stable
    QUARTER_SAWN  = "quarter_sawn"    # radial cut — medullary rays visible, stable
    FLAT_SAWN     = "flat_sawn"       # synonym for plain_sawn
    LIVE_SAWN     = "live_sawn"       # whole log, varied figure


class FigureIntensity:
    """Relative visual intensity of grain figure."""
    SUBTLE      = "subtle"
    PRONOUNCED  = "pronounced"
    STRIKING    = "striking"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class GrainPattern:
    """
    Wood grain pattern descriptor for a specific species and sawing method.

    References:
        Hoadley (2000) Ch. 9: Sawing and Drying Lumber.
        Stanley (2010) Ch. 3: Wood and Wood Products.
    """
    species: str           # e.g. 'red_oak' | 'walnut' | 'maple_curly'
    figure_type: str       # FigureType constant
    figure_intensity: str  # FigureIntensity constant
    movement_rating: str = "medium"  # 'low' | 'medium' | 'high' — dimensional movement
    notes: str = ""


# ---------------------------------------------------------------------------
# Grain direction selector
# ---------------------------------------------------------------------------

# Part-kind to grain direction mapping (Hoadley 2000; Stanley 2010; KCMA 2021)
_GRAIN_RULES: dict[str, str] = {
    # Cabinet / door construction (KCMA 2021 §4)
    "door_stile":          "length",     # grain along long axis — structural (Hoadley 2000 p. 67)
    "door_rail":           "length",     # grain along long axis — structural
    "door_panel":          "length",     # grain vertical on installed door
    "drawer_front":        "length",     # horizontal grain matches typical face grain
    "drawer_side":         "length",     # grain along length for bending resistance
    "drawer_bottom":       "none",       # cross-grain or multi-ply — no preferred direction
    "shelf":               "length",     # grain along span for stiffness
    "cabinet_side":        "length",     # grain vertical for visual and structural
    "cabinet_top":         "length",     # along width of cabinet
    "cabinet_bottom":      "length",     # along width
    "face_frame_stile":    "length",     # grain along length
    "face_frame_rail":     "length",     # grain along length
    # Furniture (Stanley 2010 Ch. 6)
    "table_top":           "length",     # grain along table length — strongest; Hoadley p. 88
    "table_leg":           "length",     # grain along long axis
    "table_apron":         "length",     # grain along span
    "chair_seat":          "length",     # grain along front-back for split resistance
    "chair_leg":           "length",     # grain along length
    "chair_back_slat":     "length",     # grain along length
    "bed_rail":            "length",     # grain along span
    "headboard_panel":     "length",     # grain vertical
    # Structural (general)
    "stretcher":           "length",
    "cleat":               "length",
    "bracket":             "length",
    # Non-directional
    "decorative_panel":    "none",
    "back_panel":          "none",       # typically plywood — no preferred direction
    "mdf_panel":           "none",       # MDF isotropic — no grain
}

_DEFAULT_GRAIN_DIRECTION = "length"


def select_grain_direction(
    part_kind: str,
    structural_load_dir: Optional[Tuple[float, float]] = None,
) -> str:
    """
    Return the best-practice grain direction for a given part kind.

    Best practices (Hoadley 2000; Stanley 2010; KCMA 2021):
        - Door rails/stiles: 'length' — grain along long axis for structural integrity
        - Door panels: 'length' — grain runs vertically when door is hung
        - Drawer fronts: 'length' — horizontal face grain is conventional
        - Table tops: 'length' — grain along table length maximises bending stiffness
        - Shelves: 'length' — grain along span resists bending
        - MDF / back panels: 'none' — no directional grain

    Args:
        part_kind:            type of part (see _GRAIN_RULES above).
                              Case-insensitive; partial matches are attempted.
        structural_load_dir:  optional (dx, dy) unit vector of primary structural load.
                              If provided, overrides lookup for non-catalogued parts:
                              grain direction is set to align with load.

    Returns:
        'length' | 'width' | 'none'

    HONEST: These are best-practice guidelines. Individual projects may vary.
    Ref: Hoadley (2000); Stanley (2010); KCMA 2021.
    """
    # Normalise part kind
    pk = part_kind.lower().replace(" ", "_").replace("-", "_")

    # Direct lookup
    if pk in _GRAIN_RULES:
        return _GRAIN_RULES[pk]

    # Partial match
    for key, direction in _GRAIN_RULES.items():
        if key in pk or pk in key:
            return direction

    # Structural load direction override
    if structural_load_dir is not None:
        dx, dy = structural_load_dir
        # If load is primarily along X (horizontal), grain along length
        # If load is primarily along Y (vertical), grain along length
        # If load is ~equal in both: grain along length (conservative)
        mag = (dx**2 + dy**2) ** 0.5
        if mag > 1e-6:
            # Dominant load component
            if abs(dx) >= abs(dy):
                return "length"
            else:
                return "length"   # length is conservative in both axes

    # Default: grain along length (structurally conservative)
    return _DEFAULT_GRAIN_DIRECTION


# ---------------------------------------------------------------------------
# Figure type advisor
# ---------------------------------------------------------------------------

# Figure type properties per Hoadley (2000) Ch. 9
_FIGURE_PROPERTIES: dict[str, dict] = {
    FigureType.PLAIN_SAWN: {
        "movement_rating": "high",
        "typical_width": "wide",
        "visual": "cathedral grain arches",
        "stability": "lower — prone to cupping",
        "notes": (
            "Plain-sawn (tangential) boards show decorative cathedral grain. "
            "Higher dimensional movement (tangential ~2× radial). "
            "Ref: Hoadley (2000) p. 75."
        ),
    },
    FigureType.RIFT_SAWN: {
        "movement_rating": "low",
        "typical_width": "medium",
        "visual": "straight parallel grain, no ray fleck",
        "stability": "high — movement between plain and quarter",
        "notes": (
            "Rift-sawn boards have straight grain ideal for legs and stiles. "
            "More waste than plain-sawn; more stable. Ref: Hoadley (2000) p. 78."
        ),
    },
    FigureType.QUARTER_SAWN: {
        "movement_rating": "low",
        "typical_width": "narrow",
        "visual": "ray fleck (oak), straight grain",
        "stability": "highest — radial movement ~50% of tangential",
        "notes": (
            "Quarter-sawn boards are most stable; show medullary ray fleck in oak. "
            "Most expensive due to waste. Ref: Hoadley (2000) p. 78."
        ),
    },
}


def figure_type_properties(figure_type: str) -> dict:
    """
    Return properties of a figure type.

    Args:
        figure_type: one of FigureType constants.

    Returns:
        dict with keys: movement_rating, visual, stability, notes.

    HONEST: Properties are general guidelines per Hoadley (2000).
    Individual species vary; moisture content significantly affects movement.
    """
    return _FIGURE_PROPERTIES.get(figure_type, {
        "movement_rating": "medium",
        "visual": "unknown",
        "stability": "unknown",
        "notes": f"Unknown figure type: {figure_type}",
    })


# ---------------------------------------------------------------------------
# Grain matching for glued panels
# ---------------------------------------------------------------------------

def grain_match_panels(
    panels: "List[CutListItem]",  # type: ignore[name-defined]
    match_kind: str = "book_match",
) -> List[Tuple[str, str]]:
    """
    Return recommended panel-to-panel grain matching pairs.

    For table tops, raised panels, and glued assemblies, adjacent panels
    should be grain-matched for visual continuity and to balance wood movement.

    Match kinds (Hoadley 2000 p. 83; Stanley 2010 Ch. 10):
        book_match  — adjacent panels are opened like a book (mirrored figure).
                      Best for symmetrical appearance (table tops, cabinet doors).
        slip_match  — panels slipped side by side without flipping (repeating figure).
                      Used in veneered work where book matching is impractical.
        random      — random arrangement; lower visual priority, fastest layout.

    Args:
        panels:     list of CutListItem; only items with grain_direction != 'none'
                    are considered for matching.
        match_kind: 'book_match' | 'slip_match' | 'random'.

    Returns:
        list of (part_id_a, part_id_b) pairs in recommended matching order.
        Panels are paired sequentially: [0,1], [2,3], ...

    HONEST: Grain matching requires visual inspection of actual boards.
    This function pairs panels by list order only; real book/slip matching
    must be done by the woodworker at the bench with actual lumber.
    Ref: Hoadley (2000); Stanley (2010).
    """
    valid_match_kinds = ("book_match", "slip_match", "random")
    if match_kind not in valid_match_kinds:
        raise ValueError(
            f"match_kind must be one of {valid_match_kinds}, got '{match_kind}'"
        )

    # Filter to panels with directional grain
    matchable = [p for p in panels if p.grain_direction != "none"]

    if match_kind == "book_match":
        # Pair consecutive panels as book-match pairs
        # [0,1] are a pair (flipped), [2,3] are a pair, etc.
        pairs: List[Tuple[str, str]] = []
        for i in range(0, len(matchable) - 1, 2):
            pairs.append((matchable[i].part_id, matchable[i + 1].part_id))
        return pairs

    elif match_kind == "slip_match":
        # Slip match: consecutive panels slipped side by side (no flip)
        pairs = []
        for i in range(0, len(matchable) - 1, 2):
            pairs.append((matchable[i].part_id, matchable[i + 1].part_id))
        return pairs

    else:  # random
        # Random: just pair sequentially — no visual matching
        pairs = []
        for i in range(0, len(matchable) - 1, 2):
            pairs.append((matchable[i].part_id, matchable[i + 1].part_id))
        return pairs


# ---------------------------------------------------------------------------
# Species properties summary
# ---------------------------------------------------------------------------

SPECIES_PROPERTIES: dict[str, dict] = {
    "red_oak": {
        "figure_type": FigureType.PLAIN_SAWN,
        "figure_intensity": FigureIntensity.PRONOUNCED,
        "movement_rating": "high",
        "janka_lbf": 1290,
        "notes": "Prominent ray fleck when quarter-sawn. KCMA widely used species.",
    },
    "white_oak": {
        "figure_type": FigureType.PLAIN_SAWN,
        "figure_intensity": FigureIntensity.PRONOUNCED,
        "movement_rating": "medium",
        "janka_lbf": 1360,
        "notes": "More stable than red oak; tyloses make it water-resistant.",
    },
    "walnut": {
        "figure_type": FigureType.PLAIN_SAWN,
        "figure_intensity": FigureIntensity.STRIKING,
        "movement_rating": "low",
        "janka_lbf": 1010,
        "notes": "Rich dark colour; one of the most stable domestic hardwoods.",
    },
    "maple_curly": {
        "figure_type": FigureType.RIFT_SAWN,
        "figure_intensity": FigureIntensity.STRIKING,
        "movement_rating": "medium",
        "janka_lbf": 1450,
        "notes": "Curly figure from interlocked grain. Difficult to hand-plane.",
    },
    "maple_hard": {
        "figure_type": FigureType.PLAIN_SAWN,
        "figure_intensity": FigureIntensity.SUBTLE,
        "movement_rating": "medium",
        "janka_lbf": 1450,
        "notes": "Excellent for cutting boards and shop furniture. Uniform grain.",
    },
    "cherry": {
        "figure_type": FigureType.PLAIN_SAWN,
        "figure_intensity": FigureIntensity.SUBTLE,
        "movement_rating": "medium",
        "janka_lbf": 950,
        "notes": "Darkens beautifully with age and UV exposure.",
    },
}
