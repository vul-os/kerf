"""
kerf_cad_core.gdt.composite_position — ASME Y14.5-2018 §10.5 Composite Positional
Tolerance Evaluation.

Evaluates composite positional tolerance compliance for a feature pattern given
measured 3-D points.  Two independent tolerance zones are checked:

  PLTZF (Pattern-Locating Tolerance Zone Framework, §10.5.1 upper frame):
    Controls the location of the *entire pattern* relative to the full datum
    reference frame (datums A, B, C).  Each feature axis must deviate from its
    nominal position by at most upper_pltzf_tolerance_mm / 2 (diametral zone).

  FRTZF (Feature-Relating Tolerance Zone Framework, §10.5.1 lower frame):
    Controls the *inter-feature spacing and orientation* within the pattern.
    The measured pattern is rigidly translated so that its centroid aligns with
    the nominal pattern centroid (removing the gross location error that the
    PLTZF already governs); residual deviation of each feature from its
    centroid-shifted nominal must be ≤ lower_frtzf_tolerance_mm / 2.

    Physically: the FRTZF tolerance zones translate and rotate (up to the
    orientation datums cited in the lower frame) as a rigid cluster to best
    fit the measured pattern.  This implementation uses centroid translation
    only (no rotation), which is the dominant term for closely spaced patterns
    and is appropriate when the FRTZF cites only the primary orientation datum.
    Callers needing full rigid-body registration (translation + rotation) should
    pre-align their measured points before supplying them.

ASME Y14.5-2018 references
---------------------------
§10.5   — Composite positional tolerancing.
§10.5.1 — The two tolerance zone frameworks: PLTZF (upper) and FRTZF (lower).
§10.5.2 — Composite position for patterns of features of size.
§4.5    — Datum shift (MMC bonus); applied per-feature via `feature_size_mm` when
           `mmc_modifier=True` and an MMC size is not provided — bonus is
           computed as max(0, feature_size_mm − nominal_mmc_size_mm) where the
           nominal MMC size equals feature_size_mm (zero bonus unless you pass
           distinct sizes; see FeaturePoint.mmc_size_mm).

Physics recap
-------------
For N features with nominal positions P_i and measured positions M_i:

  PLTZF (full datum frame, upper tolerance t_upper):
    deviation_i = 2 * ||M_i − P_i||        (diametral, §10.5.1 first tier)
    pass_i      = deviation_i ≤ t_upper

    With MMC bonus (§4.5, mmc_modifier=True):
      effective_tol_i = t_upper + bonus_i
      bonus_i = max(0, feature_size_mm_i − mmc_size_mm_i)   (hole grows → bonus)

  FRTZF (pattern centroid removed, lower tolerance t_lower):
    C_nom  = mean(P_i)
    C_meas = mean(M_i)
    delta  = C_meas − C_nom      ← centroid translation vector
    M'_i   = M_i − delta         ← centroid-shifted measured points
    frtzf_dev_i = 2 * ||M'_i − P_i||
    pass_i      = frtzf_dev_i ≤ t_lower   (same MMC bonus applied if modifier set)

Honest caveat
-------------
PLTZF and FRTZF evaluations use Euclidean 3-D point-to-nominal deviations.
This implementation does NOT:
  • Compute a full datum simulator or minimum-zone fit to the datum surfaces.
  • Perform 6-DOF rigid body registration for the FRTZF (centroid shift only;
    rotation is not optimised to minimise worst-case deviation within the
    pattern — callers should pre-align if orientation datums constrain rotation).
  • Apply projected tolerance zones (§10.5.3 projected zone) or composite
    tolerance for non-circular zones (profile / cylindrical axis orientation
    separate from position).
  • Validate that `datums_frtzf ⊆ datums_pltzf` — use composite_tolerance_check
    for frame-structure validation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

_CODE_SECTION = "ASME Y14.5-2018 §10.5 (Composite Positional Tolerance)"

_HONEST_CAVEAT = (
    "PLTZF and FRTZF deviations are computed as Euclidean 3-D diametral distances "
    "(2‖measured − nominal‖). "
    "FRTZF uses centroid translation only — no 6-DOF rigid-body registration "
    "(rotation not optimised); callers needing minimum-zone FRTZF fit should "
    "pre-align measured points. "
    "Datum simulator computation (minimum rock, maximum inscribed cylinder, etc.) "
    "is not performed; nominal point coordinates are taken as given. "
    "Positional tolerance only: orientation tolerances (perpendicularity, "
    "parallelism, angularity) of the feature axes within the pattern are not "
    "separately evaluated here. "
    "MMC bonus uses feature_size_mm relative to mmc_size_mm on FeaturePoint; "
    "if mmc_size_mm is None the bonus defaults to zero."
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FeaturePoint:
    """
    One feature in the pattern being inspected.

    Attributes
    ----------
    feature_id:
        Unique identifier for this feature, e.g. "H1" or "hole-1".
    nominal_xyz_mm:
        Nominal (drawing) position of the feature axis/centre in 3-D space,
        in millimetres (x, y, z).
    measured_xyz_mm:
        Measured position of the feature axis/centre from CMM or inspection,
        in millimetres (x, y, z).
    feature_size_mm:
        Actual (measured) size of the feature (e.g. hole diameter), in mm.
        Used for MMC bonus tolerance when mmc_modifier=True in the spec.
    mmc_size_mm:
        Maximum Material Condition size for this feature, in mm.  A hole at
        MMC is its *smallest* allowable diameter; a pin at MMC is its
        *largest* allowable diameter.  When None (default), MMC bonus is 0
        regardless of mmc_modifier.
    """
    feature_id: str
    nominal_xyz_mm: tuple[float, float, float]
    measured_xyz_mm: tuple[float, float, float]
    feature_size_mm: float
    mmc_size_mm: float | None = None

    def __post_init__(self) -> None:
        self.feature_id = str(self.feature_id).strip()
        if not self.feature_id:
            raise ValueError("FeaturePoint: feature_id must not be empty")
        # Coerce tuples/lists to 3-tuples of float
        self.nominal_xyz_mm = _coerce_xyz(self.nominal_xyz_mm, "nominal_xyz_mm")
        self.measured_xyz_mm = _coerce_xyz(self.measured_xyz_mm, "measured_xyz_mm")
        fs = float(self.feature_size_mm)
        if fs < 0:
            raise ValueError(
                f"FeaturePoint '{self.feature_id}': feature_size_mm must be ≥ 0, got {fs}"
            )
        self.feature_size_mm = fs
        if self.mmc_size_mm is not None:
            ms = float(self.mmc_size_mm)
            if ms < 0:
                raise ValueError(
                    f"FeaturePoint '{self.feature_id}': mmc_size_mm must be ≥ 0, got {ms}"
                )
            self.mmc_size_mm = ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "nominal_xyz_mm": list(self.nominal_xyz_mm),
            "measured_xyz_mm": list(self.measured_xyz_mm),
            "feature_size_mm": self.feature_size_mm,
            "mmc_size_mm": self.mmc_size_mm,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FeaturePoint":
        return cls(
            feature_id=d["feature_id"],
            nominal_xyz_mm=tuple(d["nominal_xyz_mm"]),  # type: ignore[arg-type]
            measured_xyz_mm=tuple(d["measured_xyz_mm"]),  # type: ignore[arg-type]
            feature_size_mm=d["feature_size_mm"],
            mmc_size_mm=d.get("mmc_size_mm"),
        )


@dataclass
class CompositePositionSpec:
    """
    Complete specification for composite positional tolerance evaluation.

    Attributes
    ----------
    features:
        List of FeaturePoint instances comprising the pattern.  Minimum 1.
    upper_pltzf_tolerance_mm:
        PLTZF (upper frame) positional tolerance — total diametral tolerance
        zone width, in mm.  Each feature deviation from nominal must be
        ≤ upper_pltzf_tolerance_mm (diametral, i.e. radius = tol / 2).
    lower_frtzf_tolerance_mm:
        FRTZF (lower frame) positional tolerance — total diametral tolerance
        zone width controlling inter-feature spacing, in mm.  Must be
        ≤ upper_pltzf_tolerance_mm per §10.5.1 Note 2.
    datums_pltzf:
        Datum reference letters for the PLTZF (full frame), e.g. ["A","B","C"].
        Informational; used in report output only.
    datums_frtzf:
        Datum reference letters for the FRTZF (orientation datums only),
        e.g. ["A"].  Informational; used in report output only.
    mmc_modifier:
        When True, compute MMC bonus per §4.5 using FeaturePoint.mmc_size_mm.
        Bonus = max(0, feature_size_mm − mmc_size_mm) per feature.
        When False (default / RFS), no bonus is applied.
    """
    features: list[FeaturePoint] = field(default_factory=list)
    upper_pltzf_tolerance_mm: float = 0.0
    lower_frtzf_tolerance_mm: float = 0.0
    datums_pltzf: list[str] = field(default_factory=list)
    datums_frtzf: list[str] = field(default_factory=list)
    mmc_modifier: bool = False

    def __post_init__(self) -> None:
        if not self.features:
            raise ValueError(
                "CompositePositionSpec: features list must contain at least one FeaturePoint"
            )
        u = float(self.upper_pltzf_tolerance_mm)
        if u <= 0:
            raise ValueError(
                f"CompositePositionSpec: upper_pltzf_tolerance_mm must be > 0, got {u}"
            )
        self.upper_pltzf_tolerance_mm = u
        lo = float(self.lower_frtzf_tolerance_mm)
        if lo <= 0:
            raise ValueError(
                f"CompositePositionSpec: lower_frtzf_tolerance_mm must be > 0, got {lo}"
            )
        self.lower_frtzf_tolerance_mm = lo
        # §10.5.1 Note 2: FRTZF tolerance must be ≤ PLTZF tolerance
        if lo > u:
            raise ValueError(
                f"CompositePositionSpec: lower_frtzf_tolerance_mm ({lo}) must be "
                f"≤ upper_pltzf_tolerance_mm ({u}) per ASME Y14.5-2018 §10.5.1 Note 2"
            )
        # Normalise datum lists
        self.datums_pltzf = [str(d).strip().upper() for d in self.datums_pltzf]
        self.datums_frtzf = [str(d).strip().upper() for d in self.datums_frtzf]

    def to_dict(self) -> dict[str, Any]:
        return {
            "features": [f.to_dict() for f in self.features],
            "upper_pltzf_tolerance_mm": self.upper_pltzf_tolerance_mm,
            "lower_frtzf_tolerance_mm": self.lower_frtzf_tolerance_mm,
            "datums_pltzf": list(self.datums_pltzf),
            "datums_frtzf": list(self.datums_frtzf),
            "mmc_modifier": self.mmc_modifier,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CompositePositionSpec":
        return cls(
            features=[FeaturePoint.from_dict(f) for f in (d.get("features") or [])],
            upper_pltzf_tolerance_mm=d["upper_pltzf_tolerance_mm"],
            lower_frtzf_tolerance_mm=d["lower_frtzf_tolerance_mm"],
            datums_pltzf=list(d.get("datums_pltzf") or []),
            datums_frtzf=list(d.get("datums_frtzf") or []),
            mmc_modifier=bool(d.get("mmc_modifier", False)),
        )


@dataclass
class CompositePositionReport:
    """
    Result of composite positional tolerance evaluation.

    Attributes
    ----------
    pltzf_violations:
        List of (feature_id, diametral_deviation_mm) for features that violate
        the PLTZF (upper) tolerance zone.  Empty when all features pass.
    frtzf_violations:
        List of (feature_id, diametral_deviation_mm) for features that violate
        the FRTZF (lower) tolerance zone after centroid removal.  Empty on pass.
    overall_pass:
        True only when both pltzf_violations and frtzf_violations are empty.
    max_pltzf_deviation_mm:
        Worst-case diametral deviation from nominal across all features (PLTZF).
        Includes any MMC bonus in the effective tolerance but the raw deviation
        is reported here.
    max_frtzf_deviation_mm:
        Worst-case diametral deviation from centroid-shifted nominal (FRTZF).
    pltzf_centroid_shift_mm:
        Euclidean distance the measured pattern centroid is displaced from the
        nominal pattern centroid.  Non-zero means the whole pattern is shifted
        relative to the full datum frame.
    honest_caveat:
        Scope limitation notice per §10.5 and implementation choices.
    """
    pltzf_violations: list[tuple[str, float]] = field(default_factory=list)
    frtzf_violations: list[tuple[str, float]] = field(default_factory=list)
    overall_pass: bool = False
    max_pltzf_deviation_mm: float = 0.0
    max_frtzf_deviation_mm: float = 0.0
    pltzf_centroid_shift_mm: float = 0.0
    honest_caveat: str = _HONEST_CAVEAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "pltzf_violations": [
                {"feature_id": fid, "deviation_mm": dev}
                for fid, dev in self.pltzf_violations
            ],
            "frtzf_violations": [
                {"feature_id": fid, "deviation_mm": dev}
                for fid, dev in self.frtzf_violations
            ],
            "overall_pass": self.overall_pass,
            "max_pltzf_deviation_mm": self.max_pltzf_deviation_mm,
            "max_frtzf_deviation_mm": self.max_frtzf_deviation_mm,
            "pltzf_centroid_shift_mm": self.pltzf_centroid_shift_mm,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coerce_xyz(
    val: Any, name: str
) -> tuple[float, float, float]:
    """Coerce a 3-element sequence to a (float, float, float) tuple."""
    try:
        seq = list(val)
    except TypeError:
        raise ValueError(f"FeaturePoint: {name} must be a 3-element sequence")
    if len(seq) != 3:
        raise ValueError(
            f"FeaturePoint: {name} must have exactly 3 elements, got {len(seq)}"
        )
    return (float(seq[0]), float(seq[1]), float(seq[2]))


def _dist3(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Euclidean distance between two 3-D points."""
    return math.sqrt(
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    )


def _centroid(
    points: list[tuple[float, float, float]]
) -> tuple[float, float, float]:
    """Arithmetic mean of a list of 3-D points."""
    n = len(points)
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


def _sub3(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Vector subtraction a − b."""
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add3(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Vector addition a + b."""
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mmc_bonus(fp: FeaturePoint) -> float:
    """
    Compute MMC bonus for a single FeaturePoint.

    For a hole (internal FOS): the feature is at MMC when smallest.
    Bonus = max(0, measured_size − mmc_size)   — hole larger than MMC → bonus.
    If mmc_size_mm is None, returns 0.
    """
    if fp.mmc_size_mm is None:
        return 0.0
    # Hole: at MMC when diameter is smallest (mmc_size_mm = smallest allowed).
    # Measured size > mmc → feature has departed from MMC → bonus available.
    return max(0.0, fp.feature_size_mm - fp.mmc_size_mm)


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------

def check_composite_position(spec: CompositePositionSpec) -> CompositePositionReport:
    """
    Evaluate composite positional tolerance compliance per ASME Y14.5-2018 §10.5.

    Parameters
    ----------
    spec:
        CompositePositionSpec describing the feature pattern, tolerances,
        datums, and optional MMC modifier.

    Returns
    -------
    CompositePositionReport
        Detailed pass/fail results for both the PLTZF and FRTZF tiers.
        Never raises on valid spec input.

    Algorithm
    ---------
    PLTZF (upper tier, full datum frame location):
      For each feature i:
        effective_tol_i = upper_pltzf_tolerance_mm + (bonus_i if mmc_modifier else 0)
        diametral_dev_i = 2 × ‖measured_i − nominal_i‖
        pass if diametral_dev_i ≤ effective_tol_i

    FRTZF (lower tier, pattern inter-feature spacing):
      centroid_shift = mean(measured) − mean(nominal)
      shifted_measured_i = measured_i − centroid_shift
      effective_tol_i = lower_frtzf_tolerance_mm + (bonus_i if mmc_modifier else 0)
      diametral_dev_i = 2 × ‖shifted_measured_i − nominal_i‖
      pass if diametral_dev_i ≤ effective_tol_i
    """
    nominals = [fp.nominal_xyz_mm for fp in spec.features]
    measured = [fp.measured_xyz_mm for fp in spec.features]

    # ── PLTZF check ───────────────────────────────────────────────────────────
    pltzf_violations: list[tuple[str, float]] = []
    max_pltzf_dev = 0.0

    for fp in spec.features:
        bonus = _mmc_bonus(fp) if spec.mmc_modifier else 0.0
        effective_tol = spec.upper_pltzf_tolerance_mm + bonus
        dev = 2.0 * _dist3(fp.measured_xyz_mm, fp.nominal_xyz_mm)
        if dev > max_pltzf_dev:
            max_pltzf_dev = dev
        if dev > effective_tol:
            pltzf_violations.append((fp.feature_id, round(dev, 9)))

    # ── FRTZF check ───────────────────────────────────────────────────────────
    # Compute centroid translation: measured centroid − nominal centroid
    c_nom = _centroid(nominals)
    c_meas = _centroid(measured)
    centroid_shift_vec = _sub3(c_meas, c_nom)
    centroid_shift_dist = _dist3(c_meas, c_nom)

    frtzf_violations: list[tuple[str, float]] = []
    max_frtzf_dev = 0.0

    for fp in spec.features:
        bonus = _mmc_bonus(fp) if spec.mmc_modifier else 0.0
        effective_tol = spec.lower_frtzf_tolerance_mm + bonus
        # Centroid-align: subtract pattern translation to isolate inter-feature error
        shifted = _sub3(fp.measured_xyz_mm, centroid_shift_vec)
        dev = 2.0 * _dist3(shifted, fp.nominal_xyz_mm)
        if dev > max_frtzf_dev:
            max_frtzf_dev = dev
        if dev > effective_tol:
            frtzf_violations.append((fp.feature_id, round(dev, 9)))

    overall_pass = (len(pltzf_violations) == 0) and (len(frtzf_violations) == 0)

    return CompositePositionReport(
        pltzf_violations=pltzf_violations,
        frtzf_violations=frtzf_violations,
        overall_pass=overall_pass,
        max_pltzf_deviation_mm=round(max_pltzf_dev, 9),
        max_frtzf_deviation_mm=round(max_frtzf_dev, 9),
        pltzf_centroid_shift_mm=round(centroid_shift_dist, 9),
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool wrapper (gated import — kerf_chat not available in unit tests)
# ---------------------------------------------------------------------------

try:
    import json as _json
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]  # noqa: F401

    _gdt_check_composite_position_spec = ToolSpec(
        name="gdt_check_composite_position",
        description=(
            "Evaluate composite positional tolerance compliance for a feature pattern "
            "per ASME Y14.5-2018 §10.5 (Composite Position).\n"
            "\n"
            "Two independent tolerance zones are evaluated:\n"
            "  PLTZF (upper frame, §10.5.1): each feature deviation from nominal ≤ "
            "upper_pltzf_tolerance_mm (diametral). Governs location relative to the "
            "full datum reference frame (datums_pltzf e.g. [A, B, C]).\n"
            "  FRTZF (lower frame, §10.5.1): measured pattern centroid-shifted to "
            "align with nominal pattern; residual inter-feature deviation ≤ "
            "lower_frtzf_tolerance_mm (diametral). Governs pattern spacing/orientation "
            "relative to orientation-only datums (datums_frtzf e.g. [A]).\n"
            "\n"
            "Both tolerances are diametral (total zone width). lower_frtzf must be ≤ "
            "upper_pltzf per §10.5.1 Note 2.\n"
            "\n"
            "With mmc_modifier=true: bonus = max(0, feature_size_mm − mmc_size_mm) "
            "is added to each feature's effective tolerance per §4.5.\n"
            "\n"
            "Returns: pltzf_violations, frtzf_violations, overall_pass, "
            "max_pltzf_deviation_mm, max_frtzf_deviation_mm, "
            "pltzf_centroid_shift_mm, honest_caveat.\n"
            "\n"
            "HONEST FLAG: positional tolerance only (not orientation). "
            "FRTZF uses centroid translation only — no 6-DOF rigid-body "
            "registration. Datum simulator computation not performed."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "features": {
                    "type": "array",
                    "description": (
                        "Feature points in the pattern. Each has nominal and "
                        "measured 3-D positions (x, y, z) in mm."
                    ),
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "feature_id": {
                                "type": "string",
                                "description": "Unique identifier, e.g. 'H1'.",
                            },
                            "nominal_xyz_mm": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 3,
                                "maxItems": 3,
                                "description": "Nominal [x, y, z] position in mm.",
                            },
                            "measured_xyz_mm": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 3,
                                "maxItems": 3,
                                "description": "Measured [x, y, z] position in mm.",
                            },
                            "feature_size_mm": {
                                "type": "number",
                                "description": "Measured feature size (e.g. hole diameter) in mm.",
                            },
                            "mmc_size_mm": {
                                "type": ["number", "null"],
                                "description": (
                                    "MMC size for bonus calc. "
                                    "Hole at MMC = smallest diameter. Null disables bonus."
                                ),
                            },
                        },
                        "required": [
                            "feature_id",
                            "nominal_xyz_mm",
                            "measured_xyz_mm",
                            "feature_size_mm",
                        ],
                    },
                },
                "upper_pltzf_tolerance_mm": {
                    "type": "number",
                    "description": (
                        "PLTZF diametral positional tolerance in mm "
                        "(upper frame — controls pattern location vs. full datum frame)."
                    ),
                },
                "lower_frtzf_tolerance_mm": {
                    "type": "number",
                    "description": (
                        "FRTZF diametral positional tolerance in mm "
                        "(lower frame — controls inter-feature spacing). "
                        "Must be ≤ upper_pltzf_tolerance_mm."
                    ),
                },
                "datums_pltzf": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "PLTZF datum reference letters, e.g. ['A','B','C'].",
                },
                "datums_frtzf": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "FRTZF datum reference letters, e.g. ['A'].",
                },
                "mmc_modifier": {
                    "type": "boolean",
                    "description": (
                        "Apply MMC bonus per §4.5 using mmc_size_mm on each feature. "
                        "Default false (RFS)."
                    ),
                },
            },
            "required": [
                "features",
                "upper_pltzf_tolerance_mm",
                "lower_frtzf_tolerance_mm",
            ],
        },
    )

    @register(_gdt_check_composite_position_spec, write=False)
    async def run_gdt_check_composite_position(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        raw_features = a.get("features")
        if not isinstance(raw_features, list) or len(raw_features) < 1:
            return err_payload("features must be a non-empty array", "BAD_ARGS")

        features: list[FeaturePoint] = []
        for i, f in enumerate(raw_features):
            if not isinstance(f, dict):
                return err_payload(f"features[{i}] must be an object", "BAD_ARGS")
            try:
                features.append(FeaturePoint.from_dict(f))
            except (ValueError, KeyError, TypeError) as exc:
                return err_payload(f"features[{i}]: {exc}", "BAD_ARGS")

        try:
            spec = CompositePositionSpec(
                features=features,
                upper_pltzf_tolerance_mm=a["upper_pltzf_tolerance_mm"],
                lower_frtzf_tolerance_mm=a["lower_frtzf_tolerance_mm"],
                datums_pltzf=list(a.get("datums_pltzf") or []),
                datums_frtzf=list(a.get("datums_frtzf") or []),
                mmc_modifier=bool(a.get("mmc_modifier", False)),
            )
        except (ValueError, KeyError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        report = check_composite_position(spec)
        return ok_payload(report.to_dict())

    _TOOL_REGISTERED = True

except ImportError:
    # Registry not available in pure unit-test context.
    # Data model and check_composite_position() remain fully usable.
    _TOOL_REGISTERED = False
