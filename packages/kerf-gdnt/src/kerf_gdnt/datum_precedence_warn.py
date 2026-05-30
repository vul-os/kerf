"""
Datum Precedence Consistency Analyser — ASME Y14.5-2018 §4.7 + §4.11.

Analyses a *set* of feature control frames that reference overlapping datums
and warns when those frames are mutually inconsistent in ways that indicate a
drawing error.  Four classes of inconsistency are detected:

P1  Datum feature-type inconsistency (§4.7)
    The same datum letter is declared with a conflicting feature type across
    frames (planar in one, FOS in another).  A datum must have a unique type.

P2  Datum precedence reversal (§4.11)
    Two frames sharing the same datums use them in a different primary /
    secondary / tertiary order (e.g. A|B|C vs B|A|C).

P3  Degree-of-freedom (DOF) inconsistency (§4.7 / §4.11)
    A frame's declared datum sequence removes more than 6 DOF — impossible
    for a rigid body.

P4  Material-condition modifier conflict (§4.11.5)
    The same datum letter appears with different modifiers in different frames
    (e.g. A|M in one frame, A|L in another).

HONEST FLAG
-----------
This module analyses *declared* datum properties only — it does not model the
3D geometry of the actual features.  Geometric consistency requires the actual
solid model and is NOT performed here.  Per ASME Y14.5-2018 §4.3: the drawing
declaration is analysed, not the manufactured part.

References
----------
ASME Y14.5-2018 §4.7   Degrees of freedom constrained by datum reference frames.
ASME Y14.5-2018 §4.11  Datum precedence — primary, secondary, tertiary.
ASME Y14.5-2018 §4.11.5 Material-boundary modifiers on datum features.

Kerf is not ASME-certified; this is engineering support software.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Constants — DOF budgets per ASME Y14.5-2018 §4.7
# ---------------------------------------------------------------------------

#: Maximum available degrees of freedom for a rigid body in 3-D space.
_MAX_DOF: int = 6

#: DOF removed by feature type at each precedence level.
#: References:
#:   §4.7, §4.11.1 — primary planar removes 3 (1 translation + 2 rotations)
#:   §4.7, §4.11.1 — primary cylinder removes 2 (2 translations perp to axis)
#:   §4.11.2        — secondary planar removes 2 (1 translation + 1 rotation)
#:   §4.11.2        — secondary cylinder removes 1 (1 remaining translation)
#:   §4.11.3        — tertiary removes 1 regardless of type

_DOF_REMOVED: dict[tuple[str, int], int] = {
    # Primary planar: constrains Z-translation + Rx + Ry (Fig. 4-1)
    ("flat_face", 0): 3,
    ("plane",     0): 3,
    # Primary cylindrical FOS: constrains X,Y translations (Fig. 4-2)
    ("cylinder",  0): 2,
    ("cone",      0): 2,
    ("sphere",    0): 3,   # sphere primary: 3 translations
    ("slot",      0): 2,
    ("width",     0): 2,
    # Secondary planar: constrains 1 rotation + 1 translation
    ("flat_face", 1): 2,
    ("plane",     1): 2,
    # Secondary cylindrical FOS: 1 remaining perpendicular translation
    ("cylinder",  1): 1,
    ("cone",      1): 1,
    ("sphere",    1): 1,
    ("slot",      1): 1,
    ("width",     1): 1,
    # Tertiary: always 1 (last rotational or translational DOF)
    ("flat_face", 2): 1,
    ("plane",     2): 1,
    ("cylinder",  2): 1,
    ("cone",      2): 1,
    ("sphere",    2): 1,
    ("slot",      2): 1,
    ("width",     2): 1,
}

#: FOS types (features of size).
_FOS_TYPES: frozenset[str] = frozenset({
    "cylinder", "cone", "sphere", "slot", "width",
})

#: Planar types.
_PLANAR_TYPES: frozenset[str] = frozenset({"flat_face", "plane"})


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FrameDatumRef:
    """
    A single datum compartment within one feature control frame.

    Parameters
    ----------
    label:
        Datum letter, e.g. ``"A"``.
    modifier:
        Material-boundary modifier: ``"M"`` (MMB), ``"L"`` (LMB), ``"S"`` (RMB/RFS),
        or ``None`` (RFS implied).
    """
    label: str
    modifier: Optional[str] = None  # None | "M" | "L" | "S"


@dataclass
class FrameSpec:
    """
    A feature control frame's datum reference compartments plus a frame identifier.

    Parameters
    ----------
    frame_id:
        Human-readable identifier for error messages, e.g. ``"F1"``.
    datum_refs:
        Ordered list: position 0 = primary, 1 = secondary, 2 = tertiary.
    """
    frame_id: str
    datum_refs: list[FrameDatumRef]


@dataclass
class DatumFeatureInfo:
    """
    Declared properties of a datum feature on the drawing.

    Parameters
    ----------
    label:
        Datum letter.
    feature_type:
        Geometric type: ``"flat_face"``, ``"cylinder"``, ``"slot"``, etc.
    """
    label: str
    feature_type: str

    @property
    def is_fos(self) -> bool:
        return self.feature_type in _FOS_TYPES

    @property
    def is_planar(self) -> bool:
        return self.feature_type in _PLANAR_TYPES


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PrecedenceWarning:
    """
    A single datum precedence inconsistency found across multiple frames.

    Attributes
    ----------
    code:
        Machine-readable warning code.
    severity:
        ``"ERROR"`` (drawing error, geometry incoherent) or ``"WARNING"``
        (likely drawing error but may be intentional).
    message:
        Human-readable description.
    rule:
        ASME Y14.5-2018 §x.x rule citation.
    affected_frames:
        Frame IDs involved in this inconsistency.
    datum_label:
        Datum letter at the centre of the inconsistency, if applicable.
    recommendation:
        Actionable fix suggestion.
    """
    code: str
    severity: str          # "ERROR" | "WARNING"
    message: str
    rule: str
    affected_frames: list[str] = field(default_factory=list)
    datum_label: Optional[str] = None
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "rule": self.rule,
            "affected_frames": self.affected_frames,
            "datum_label": self.datum_label,
            "recommendation": self.recommendation,
        }

    def __str__(self) -> str:
        return (
            f"[{self.severity}:{self.code}] {self.message} "
            f"(frames: {', '.join(self.affected_frames)}) ({self.rule})"
        )


@dataclass
class PrecedenceReport:
    """
    Result of :func:`analyze_datum_precedence_consistency`.

    Attributes
    ----------
    warnings:
        List of :class:`PrecedenceWarning` objects.  Empty when fully consistent.
    consistent:
        True when no warnings were generated.
    frames_analysed:
        Number of input frames checked.
    recommendations:
        Deduplicated list of actionable fix suggestions.

    Notes
    -----
    HONEST FLAG: consistency is assessed on declared datum properties only.
    Geometric consistency (actual 3D feature shapes and DOF elimination) requires
    the solid model and is out of scope.  See module docstring.
    """
    warnings: list[PrecedenceWarning] = field(default_factory=list)
    consistent: bool = True
    frames_analysed: int = 0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "consistent": self.consistent,
            "frames_analysed": self.frames_analysed,
            "warning_count": len(self.warnings),
            "warnings": [w.to_dict() for w in self.warnings],
            "recommendations": self.recommendations,
        }


# ---------------------------------------------------------------------------
# Analysis engine
# ---------------------------------------------------------------------------

def analyze_datum_precedence_consistency(
    frames: list[FrameSpec],
    datums: dict[str, DatumFeatureInfo],
) -> PrecedenceReport:
    """
    Analyse a set of feature control frames for datum precedence inconsistencies.

    Implements four checks per ASME Y14.5-2018 §4.7 and §4.11:

    P1  Feature-type conflict (§4.7)
        Same datum label at same position with conflicting feature types, or
        same label at different precedence positions across frames (different
        DOF semantics apply at each position).

    P2  Precedence reversal (§4.11)
        Two frames sharing >= 2 common datum labels use them in a different
        order (e.g. A|B|C vs B|A|C).

    P3  DOF over-constraint (§4.7)
        A frame's datum sequence removes more than 6 DOF.

    P4  Modifier conflict (§4.11.5)
        Same datum letter appears with different material-boundary modifiers
        across frames.

    Parameters
    ----------
    frames:
        List of :class:`FrameSpec` objects to analyse.
    datums:
        Mapping from datum letter to :class:`DatumFeatureInfo`.

    Returns
    -------
    PrecedenceReport
        ``consistent=True`` when no warnings are generated.

    Notes
    -----
    HONEST FLAG: analyses declared datum properties only.  Per ASME Y14.5-2018
    §4.3, the drawing declaration is analysed, not the manufactured part.
    Actual geometric DOF elimination requires the solid model.

    References
    ----------
    ASME Y14.5-2018 §4.7   — Degrees of freedom constrained by datums.
    ASME Y14.5-2018 §4.11  — Datum precedence.
    ASME Y14.5-2018 §4.11.5 — Material-boundary modifiers.
    """
    warnings: list[PrecedenceWarning] = []

    if not frames:
        return PrecedenceReport(consistent=True, frames_analysed=0)

    # ------------------------------------------------------------------
    # P1a: Feature-type conflict — same datum label, same position, different type
    # ------------------------------------------------------------------
    pos_type_map: dict[str, dict[int, list[tuple[str, str]]]] = {}
    for frame in frames:
        for pos, ref in enumerate(frame.datum_refs[:3]):
            label = ref.label.upper()
            info = datums.get(label)
            if info is None:
                continue
            ft = info.feature_type
            pos_type_map.setdefault(label, {}).setdefault(pos, []).append(
                (ft, frame.frame_id)
            )

    for label, pos_map in pos_type_map.items():
        for pos, entries in pos_map.items():
            fts = {ft for ft, _ in entries}
            if len(fts) > 1:
                frame_ids = [fid for _, fid in entries]
                pos_name = ("primary", "secondary", "tertiary")[pos] if pos < 3 else f"pos{pos}"
                planar_frames = [fid for ft, fid in entries if ft in _PLANAR_TYPES]
                fos_frames = [fid for ft, fid in entries if ft in _FOS_TYPES]
                warnings.append(PrecedenceWarning(
                    code="FEATURE_TYPE_CONFLICT",
                    severity="ERROR",
                    message=(
                        f"Datum '{label}' is declared as {sorted(fts)} at {pos_name} position "
                        f"across frames — a datum feature must have a single geometry type "
                        f"(ASME Y14.5-2018 §4.7). Planar in: {planar_frames}; FOS in: {fos_frames}."
                    ),
                    rule="ASME Y14.5-2018 §4.7",
                    affected_frames=frame_ids,
                    datum_label=label,
                    recommendation=(
                        f"Verify that datum '{label}' is consistently nominated on the "
                        "same physical feature throughout the drawing.  If two different "
                        "features are intended, assign separate datum letters."
                    ),
                ))

    # ------------------------------------------------------------------
    # P1b: Same datum label at different precedence positions across frames
    # ------------------------------------------------------------------
    label_frame_positions: dict[str, list[tuple[int, str]]] = {}
    for frame in frames:
        for pos, ref in enumerate(frame.datum_refs[:3]):
            label = ref.label.upper()
            label_frame_positions.setdefault(label, []).append((pos, frame.frame_id))

    label_positions: dict[str, set[int]] = {
        label: {pos for pos, _ in entries}
        for label, entries in label_frame_positions.items()
    }

    for label, positions in label_positions.items():
        if len(positions) > 1:
            info = datums.get(label)
            if info is None:
                continue
            pos_list = sorted(positions)
            affected = [fid for _, fid in label_frame_positions[label]]
            pos_names = [
                ("primary", "secondary", "tertiary")[p] if p < 3 else f"pos{p}"
                for p in pos_list
            ]
            warnings.append(PrecedenceWarning(
                code="DATUM_USED_AT_MULTIPLE_LEVELS",
                severity="WARNING",
                message=(
                    f"Datum '{label}' appears at multiple precedence levels across frames: "
                    f"{'  , '.join(pos_names)}.  Each position removes different DOFs "
                    f"(§4.11.1–§4.11.3). Verify this is intentional."
                ),
                rule="ASME Y14.5-2018 §4.11",
                affected_frames=affected,
                datum_label=label,
                recommendation=(
                    f"Review whether datum '{label}' is intentionally used at different "
                    "precedence levels, or whether a datum letter assignment error occurred."
                ),
            ))

    # ------------------------------------------------------------------
    # P2: Precedence reversal
    # ------------------------------------------------------------------
    for i in range(len(frames)):
        for j in range(i + 1, len(frames)):
            fi = frames[i]
            fj = frames[j]
            labels_i = [r.label.upper() for r in fi.datum_refs]
            labels_j = [r.label.upper() for r in fj.datum_refs]
            set_i = set(labels_i)
            set_j = set(labels_j)
            shared = set_i & set_j

            if len(shared) < 2:
                continue

            pos_i = {lbl: idx for idx, lbl in enumerate(labels_i) if lbl in shared}
            pos_j = {lbl: idx for idx, lbl in enumerate(labels_j) if lbl in shared}
            shared_sorted = sorted(shared)
            swaps: list[tuple[str, str]] = []
            for a_idx in range(len(shared_sorted)):
                for b_idx in range(a_idx + 1, len(shared_sorted)):
                    a = shared_sorted[a_idx]
                    b = shared_sorted[b_idx]
                    if a not in pos_i or b not in pos_i:
                        continue
                    if a not in pos_j or b not in pos_j:
                        continue
                    order_i = pos_i[a] < pos_i[b]
                    order_j = pos_j[a] < pos_j[b]
                    if order_i != order_j:
                        swaps.append((a, b))

            if swaps:
                swap_desc = "; ".join(
                    f"'{a}' and '{b}' swapped" for a, b in swaps
                )
                order_i_str = "|".join(labels_i)
                order_j_str = "|".join(labels_j)
                warnings.append(PrecedenceWarning(
                    code="PRECEDENCE_REVERSAL",
                    severity="WARNING",
                    message=(
                        f"Datum precedence reversal between frame '{fi.frame_id}' "
                        f"({order_i_str}) and frame '{fj.frame_id}' ({order_j_str}): "
                        f"{swap_desc}.  Per §4.11, the primary datum establishes the "
                        "highest-priority constraint — unintentional reversals indicate "
                        "a drawing error (ASME Y14.5-2018 §4.11)."
                    ),
                    rule="ASME Y14.5-2018 §4.11",
                    affected_frames=[fi.frame_id, fj.frame_id],
                    recommendation=(
                        "Verify that the intended DRF hierarchy is correctly specified.  "
                        "If different controlled features genuinely require different datum "
                        "priority orders, add an engineering note explaining the intent."
                    ),
                ))

    # ------------------------------------------------------------------
    # P3: DOF over-constraint
    # ------------------------------------------------------------------
    for frame in frames:
        total_dof = 0
        for pos, ref in enumerate(frame.datum_refs[:3]):
            label = ref.label.upper()
            info = datums.get(label)
            if info is None:
                continue
            ft = info.feature_type
            removed = _DOF_REMOVED.get((ft, pos), 1)
            total_dof += removed

        if total_dof > _MAX_DOF:
            warnings.append(PrecedenceWarning(
                code="DOF_OVER_CONSTRAINT",
                severity="ERROR",
                message=(
                    f"Frame '{frame.frame_id}' removes {total_dof} degrees of freedom "
                    f"based on declared datum feature types and precedence positions, "
                    f"but a rigid body only has {_MAX_DOF} DOF.  The datum sequence is "
                    f"over-constrained (ASME Y14.5-2018 §4.7)."
                ),
                rule="ASME Y14.5-2018 §4.7",
                affected_frames=[frame.frame_id],
                recommendation=(
                    "Review the datum feature types and precedence structure.  Each "
                    "datum adds DOF constraints; together they must not exceed 6.  "
                    "Sphere primary (3) + planar secondary (2) + tertiary (1) = 6 "
                    "is the maximum permitted for a 3-datum DRF (§4.7 Fig. 4-7)."
                ),
            ))

    # ------------------------------------------------------------------
    # P4: Material-condition modifier conflict
    # ------------------------------------------------------------------
    modifier_map: dict[str, list[tuple[Optional[str], str]]] = {}
    for frame in frames:
        for ref in frame.datum_refs:
            label = ref.label.upper()
            modifier_map.setdefault(label, []).append((ref.modifier, frame.frame_id))

    for label, mod_entries in modifier_map.items():
        distinct_mods = {m for m, _ in mod_entries}
        if len(distinct_mods) > 1:
            def _mod_display(m: Optional[str]) -> str:
                return m if m is not None else "None(RFS)"
            mod_frame_map: dict[str, list[str]] = {}
            for m, fid in mod_entries:
                mod_frame_map.setdefault(_mod_display(m), []).append(fid)
            detail = "; ".join(
                f"{mod} in {fids}" for mod, fids in sorted(mod_frame_map.items())
            )
            warnings.append(PrecedenceWarning(
                code="MODIFIER_CONFLICT",
                severity="WARNING",
                message=(
                    f"Datum '{label}' is referenced with different material-boundary "
                    f"modifiers across frames: {detail}.  Per §4.11.5, a datum feature "
                    "should be referenced consistently — modifier changes across frames "
                    "imply different simulated datum boundaries (ASME Y14.5-2018 §4.11.5)."
                ),
                rule="ASME Y14.5-2018 §4.11.5",
                affected_frames=sorted({fid for _, fid in mod_entries}),
                datum_label=label,
                recommendation=(
                    f"Standardise the modifier for datum '{label}' across all frames "
                    "that reference it, unless different material boundaries are "
                    "intentionally required for different controlled features."
                ),
            ))

    # ------------------------------------------------------------------
    # Build report
    # ------------------------------------------------------------------
    recs = list({w.recommendation for w in warnings if w.recommendation})
    return PrecedenceReport(
        warnings=warnings,
        consistent=len(warnings) == 0,
        frames_analysed=len(frames),
        recommendations=recs,
    )

