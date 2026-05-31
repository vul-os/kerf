"""
kerf_cad_core.gdt.runout_circular — ASME Y14.5-2018 §12.4 Circular Runout Evaluation.

Evaluates *circular* (single-plane) runout tolerance compliance given a set of
measured radial points taken around a feature at a specific axial position.  Each
set of points at a given axial position is called a *cross-section*; the FIM
(Full Indicator Movement) for that section is:

    FIM = max(radial_measurement) − min(radial_measurement)

This is the value an indicator would traverse if it followed the surface as the
part rotated one full revolution with the indicator held fixed axially.

ASME Y14.5-2018 references
---------------------------
§12.4   — Circular runout tolerance: the tolerance zone is a circular band of
           width t, at each cross-sectional plane, centred on the datum axis.
           The surface must not deviate more than t in total radial movement at
           any single circular element.
§12.2   — FIM (Full Indicator Movement): total range of indicator deflection
           during one complete revolution of the part about the datum axis.
§12.3   — Distinction from total runout (§12.5): circular runout is assessed
           independently at each cross-section; the indicator does not traverse
           axially.  Total runout sweeps the entire surface axially and checks
           the combined form + coaxiality error.

Distinction from runout_check.py
---------------------------------
`runout_check.py` implements the pre-existing `InspectionPoint`-based API with
`RunoutCheckSpec` and supports both circular and total runout using a generic
point cloud.  *This* module provides a distinct, section-oriented API explicitly
designed for §12.4 single-plane circular runout:

  • Input is structured as a list of *cross-section lists* — each inner list
    contains measurements taken at a single axial position.  This mirrors the
    physical inspection procedure (fixture part at z₀, rotate 360°, record N
    radial readings, then move to z₁).
  • The dataclass names (`RunoutMeasurement`, `CircularRunoutSpec`,
    `CircularRunoutReport`) are distinct and co-exist safely with the existing
    `InspectionPoint`/`RunoutCheckSpec`/`RunoutCheckReport` in the same gdt package.
  • Governing section reporting: the report identifies which axial section has
    the worst FIM and reports its axial position.
  • `margin_mm`: signed distance from pass/fail boundary (positive = further from
    violation, negative = amount of overrun).

Physics summary
---------------
For S cross-sections each with N_s measurements at radii {r₁, …, r_{N_s}}:

    FIM_s = max({r_i}) − min({r_i})      for section s

    max_FIM = max(FIM_s  for s = 1 … S)

    pass ⟺ max_FIM ≤ tolerance_mm

Honest caveat
-------------
This implementation assumes measurements are already expressed as radial distances
from the TRUE datum axis A (or whichever datum axis is cited in the feature
control frame).  It does NOT:

  • Perform datum simulator computation (minimum circumscribed cylinder, maximum
    inscribed cylinder, or minimum zone cylinder per ASME B89.3.1 / ISO 12181-1).
  • Fit an optimal axis through the measured point cloud using Chebyshev or
    least-squares methods.
  • Correct for probe offset, cosine error, or thermal drift in the inspection
    data.
  • Model surface form errors on conical or curved-profile features beyond the
    scalar FIM at each section.

Callers supplying CMM data must pre-process their point cloud to extract radial
distances relative to the established datum axis before using this module.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

_CODE_SECTION = "ASME Y14.5-2018 §12.4 (Circular Runout)"

_HONEST_CAVEAT = (
    "Measurements must be pre-computed as radial distances from the TRUE datum "
    "axis (datum_axis_id). Datum simulator computation (minimum circumscribed "
    "cylinder, maximum inscribed cylinder, minimum zone cylinder — ASME B89.3.1 / "
    "ISO 12181-1 §4.3) is NOT performed. FIM = max(r) − min(r) per section; "
    "this is the scalar radial FIM only — angular position of the maximum is not "
    "resolved. Probe offset, cosine error, and thermal corrections must be "
    "applied by the caller before passing measurements. This module evaluates "
    "single-plane circular runout (§12.4) only; total runout (§12.5 axial sweep) "
    "is not computed here."
)

_MIN_POINTS_PER_SECTION = 3


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RunoutMeasurement:
    """
    A single radial measurement on a surface of revolution.

    Attributes
    ----------
    angular_position_deg:
        Angular position (degrees) of this measurement point around the feature.
        Typically in [0, 360).  Only used for documentation / debugging; FIM
        computation uses the scalar radial values only.
    radial_measurement_mm:
        Measured radial distance from the datum axis to the surface at this
        angular position (mm, must be > 0).
    axial_position_mm:
        Axial position along the datum axis where this measurement was taken (mm).
        Default 0.0; all measurements in a cross-section should share the same
        axial position.
    """
    angular_position_deg: float
    radial_measurement_mm: float
    axial_position_mm: float = 0.0

    def __post_init__(self) -> None:
        try:
            self.angular_position_deg = float(self.angular_position_deg)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"RunoutMeasurement: angular_position_deg must be numeric, "
                f"got '{self.angular_position_deg}'"
            ) from exc

        try:
            r = float(self.radial_measurement_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"RunoutMeasurement: radial_measurement_mm must be numeric, "
                f"got '{self.radial_measurement_mm}'"
            ) from exc
        if r <= 0.0:
            raise ValueError(
                f"RunoutMeasurement: radial_measurement_mm must be > 0, got {r}"
            )
        self.radial_measurement_mm = r

        try:
            self.axial_position_mm = float(self.axial_position_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"RunoutMeasurement: axial_position_mm must be numeric, "
                f"got '{self.axial_position_mm}'"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "angular_position_deg": self.angular_position_deg,
            "radial_measurement_mm": self.radial_measurement_mm,
            "axial_position_mm": self.axial_position_mm,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunoutMeasurement":
        return cls(
            angular_position_deg=d["angular_position_deg"],
            radial_measurement_mm=d["radial_measurement_mm"],
            axial_position_mm=float(d.get("axial_position_mm", 0.0)),
        )


@dataclass
class CircularRunoutSpec:
    """
    Specification for ASME Y14.5-2018 §12.4 circular runout evaluation.

    Attributes
    ----------
    measurements_per_cross_section:
        Ordered list of cross-section lists.  Each inner list contains the
        radial measurements taken at a single axial position.  At least one
        cross-section is required; each cross-section must have at least
        ``_MIN_POINTS_PER_SECTION`` (3) measurements for a statistically
        meaningful FIM.
    tolerance_mm:
        Circular runout tolerance from the feature control frame (mm, > 0).
        Pass condition: max_FIM ≤ tolerance_mm.
    datum_axis_id:
        Datum axis identifier cited in the feature control frame (e.g. "A").
        Informational — used in report output and honest caveat only.
    """
    measurements_per_cross_section: list[list[RunoutMeasurement]] = field(
        default_factory=list
    )
    tolerance_mm: float = 0.0
    datum_axis_id: str = "A"

    def __post_init__(self) -> None:
        # Validate cross-section list
        if not self.measurements_per_cross_section:
            raise ValueError(
                "CircularRunoutSpec: measurements_per_cross_section must not be empty"
            )
        for idx, section in enumerate(self.measurements_per_cross_section):
            if not isinstance(section, list):
                raise ValueError(
                    f"CircularRunoutSpec: cross-section {idx} must be a list of "
                    f"RunoutMeasurement, got {type(section).__name__}"
                )
            if len(section) < _MIN_POINTS_PER_SECTION:
                raise ValueError(
                    f"CircularRunoutSpec: cross-section {idx} has {len(section)} "
                    f"measurement(s) — minimum {_MIN_POINTS_PER_SECTION} required "
                    f"for a valid FIM per §12.4"
                )
            for jdx, m in enumerate(section):
                if not isinstance(m, RunoutMeasurement):
                    raise ValueError(
                        f"CircularRunoutSpec: cross-section {idx}[{jdx}] must be a "
                        f"RunoutMeasurement, got {type(m).__name__}"
                    )

        # Validate tolerance
        try:
            tol = float(self.tolerance_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"CircularRunoutSpec: tolerance_mm must be numeric, "
                f"got '{self.tolerance_mm}'"
            ) from exc
        if tol <= 0.0:
            raise ValueError(
                f"CircularRunoutSpec: tolerance_mm must be > 0, got {tol}"
            )
        self.tolerance_mm = tol

        # Normalise datum ID
        self.datum_axis_id = str(self.datum_axis_id).strip().upper()
        if not self.datum_axis_id:
            raise ValueError(
                "CircularRunoutSpec: datum_axis_id must not be empty"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "measurements_per_cross_section": [
                [m.to_dict() for m in section]
                for section in self.measurements_per_cross_section
            ],
            "tolerance_mm": self.tolerance_mm,
            "datum_axis_id": self.datum_axis_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CircularRunoutSpec":
        raw_sections = d.get("measurements_per_cross_section") or []
        sections: list[list[RunoutMeasurement]] = []
        for raw_section in raw_sections:
            sections.append([RunoutMeasurement.from_dict(m) for m in raw_section])
        return cls(
            measurements_per_cross_section=sections,
            tolerance_mm=d["tolerance_mm"],
            datum_axis_id=str(d.get("datum_axis_id", "A")),
        )


@dataclass
class CircularRunoutReport:
    """
    Result of ASME Y14.5-2018 §12.4 circular runout evaluation.

    Attributes
    ----------
    fim_per_section_mm:
        FIM (Full Indicator Movement = max(r) − min(r)) for each cross-section,
        in the same order as ``CircularRunoutSpec.measurements_per_cross_section``.
        Units: mm.
    max_fim_mm:
        Worst-case FIM across all cross-sections (mm).  This is the value
        compared against ``tolerance_mm`` for pass/fail.
    governing_axial_position_mm:
        Axial position (mm) of the cross-section that produced ``max_fim_mm``.
        If multiple sections tie, the first (lowest index) is reported.
    pass_fail:
        "PASS" when max_fim_mm ≤ tolerance_mm, "FAIL" otherwise.
    margin_mm:
        Signed margin = tolerance_mm − max_fim_mm.
        Positive → how far inside tolerance (headroom).
        Negative → amount by which the feature violates the tolerance.
    num_measurements_total:
        Total count of individual radial measurements across all cross-sections.
    honest_caveat:
        Scope limitation notice per ASME B89.3.1 / ISO 12181-1.
    """
    fim_per_section_mm: list[float] = field(default_factory=list)
    max_fim_mm: float = 0.0
    governing_axial_position_mm: float = 0.0
    pass_fail: str = "PASS"
    margin_mm: float = 0.0
    num_measurements_total: int = 0
    honest_caveat: str = _HONEST_CAVEAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "fim_per_section_mm": [round(f, 10) for f in self.fim_per_section_mm],
            "max_fim_mm": round(self.max_fim_mm, 10),
            "governing_axial_position_mm": self.governing_axial_position_mm,
            "pass_fail": self.pass_fail,
            "margin_mm": round(self.margin_mm, 10),
            "num_measurements_total": self.num_measurements_total,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------

def check_circular_runout(spec: CircularRunoutSpec) -> CircularRunoutReport:
    """
    Evaluate circular runout tolerance compliance per ASME Y14.5-2018 §12.4.

    For each cross-section in ``spec.measurements_per_cross_section``:
        FIM_s = max(radial_measurement_mm) − min(radial_measurement_mm)

    Overall max_FIM = max(FIM_s  for all sections s).
    The result passes when max_FIM ≤ spec.tolerance_mm.

    Parameters
    ----------
    spec:
        CircularRunoutSpec with section measurements, tolerance, and datum ID.

    Returns
    -------
    CircularRunoutReport
        FIM per section, overall max FIM, governing axial position, pass/fail,
        margin, total measurement count, and honest caveat.

    Notes
    -----
    - Uses the axial_position_mm of the *first* measurement in each section as
      the representative axial position for that section.
    - FIM values are rounded to 10 decimal places for numeric stability.
    """
    fim_per_section: list[float] = []
    governing_axial: float = 0.0
    max_fim: float = 0.0
    governing_idx: int = 0
    total_count: int = 0

    for s_idx, section in enumerate(spec.measurements_per_cross_section):
        radii = [m.radial_measurement_mm for m in section]
        total_count += len(radii)
        r_max = max(radii)
        r_min = min(radii)
        fim_s = round(r_max - r_min, 10)
        fim_per_section.append(fim_s)

        if fim_s > max_fim:
            max_fim = fim_s
            governing_idx = s_idx

    # Governing axial position: axial_position_mm of first point in the worst section
    governing_axial = spec.measurements_per_cross_section[governing_idx][0].axial_position_mm

    max_fim = round(max_fim, 10)
    tol = spec.tolerance_mm
    margin = round(tol - max_fim, 10)
    pass_fail = "PASS" if max_fim <= tol else "FAIL"

    return CircularRunoutReport(
        fim_per_section_mm=fim_per_section,
        max_fim_mm=max_fim,
        governing_axial_position_mm=governing_axial,
        pass_fail=pass_fail,
        margin_mm=margin,
        num_measurements_total=total_count,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool wrapper (gated import — registry not available in unit-test context)
# ---------------------------------------------------------------------------

try:
    import json as _json
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]  # noqa: F401

    _gdt_check_circular_runout_spec = ToolSpec(
        name="gdt_check_circular_runout",
        description=(
            "Evaluate circular (single-plane) runout tolerance compliance per "
            "ASME Y14.5-2018 §12.4.\n"
            "\n"
            "Given a set of measured radial points around a feature at one or more "
            "axial positions, computes the FIM (Full Indicator Movement) = "
            "max(r) − min(r) for each cross-section, and pass/fail against the "
            "tolerance value.\n"
            "\n"
            "Distinct from total runout (§12.5 / runout_check with 'total'): "
            "circular runout is evaluated independently at each axial cross-section "
            "without any axial sweep — the indicator remains fixed axially while the "
            "part makes one full revolution.\n"
            "\n"
            "Input structure:\n"
            "  measurements_per_cross_section: list of sections; each section is a "
            "list of {angular_position_deg, radial_measurement_mm, axial_position_mm} "
            "objects.  Minimum 3 measurements per section.\n"
            "  tolerance_mm: circular runout tolerance from the feature control frame (mm).\n"
            "  datum_axis_id: datum letter cited in the FCF (default 'A').\n"
            "\n"
            "Returns: fim_per_section_mm, max_fim_mm, governing_axial_position_mm, "
            "pass_fail ('PASS'|'FAIL'), margin_mm (tolerance − max_fim; negative = "
            "violation), num_measurements_total, honest_caveat.\n"
            "\n"
            "HONEST FLAG: measurements must be pre-computed radial distances from the "
            "TRUE datum axis. Datum simulator computation (minimum zone cylinder per "
            "ASME B89.3.1 / ISO 12181-1 §4.3) is NOT performed. Probe offset/cosine "
            "error corrections must be applied by the caller."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "measurements_per_cross_section": {
                    "type": "array",
                    "description": (
                        "List of cross-section measurement arrays. Each inner array "
                        "represents one axial position. Minimum 1 section; minimum 3 "
                        "measurements per section."
                    ),
                    "minItems": 1,
                    "items": {
                        "type": "array",
                        "description": "Measurements at a single axial position.",
                        "minItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {
                                "angular_position_deg": {
                                    "type": "number",
                                    "description": "Angular position in degrees [0, 360).",
                                },
                                "radial_measurement_mm": {
                                    "type": "number",
                                    "description": "Measured radius from datum axis (mm, > 0).",
                                },
                                "axial_position_mm": {
                                    "type": "number",
                                    "description": (
                                        "Axial position where this measurement was taken (mm). "
                                        "All points in the same section should share this value. "
                                        "Default 0.0."
                                    ),
                                },
                            },
                            "required": ["angular_position_deg", "radial_measurement_mm"],
                        },
                    },
                },
                "tolerance_mm": {
                    "type": "number",
                    "description": (
                        "Circular runout tolerance from the feature control frame (mm, > 0). "
                        "Pass when max_fim_mm ≤ tolerance_mm."
                    ),
                },
                "datum_axis_id": {
                    "type": "string",
                    "description": (
                        "Datum axis letter cited in the feature control frame, e.g. 'A'. "
                        "Informational — used in the honest caveat only. Default 'A'."
                    ),
                },
            },
            "required": ["measurements_per_cross_section", "tolerance_mm"],
        },
    )

    @register(_gdt_check_circular_runout_spec, write=False)
    async def run_gdt_check_circular_runout(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        raw_sections = a.get("measurements_per_cross_section")
        if not isinstance(raw_sections, list) or len(raw_sections) < 1:
            return err_payload(
                "measurements_per_cross_section must be a non-empty array", "BAD_ARGS"
            )

        sections: list[list[RunoutMeasurement]] = []
        for s_idx, raw_section in enumerate(raw_sections):
            if not isinstance(raw_section, list):
                return err_payload(
                    f"measurements_per_cross_section[{s_idx}] must be an array",
                    "BAD_ARGS",
                )
            if len(raw_section) < _MIN_POINTS_PER_SECTION:
                return err_payload(
                    f"cross-section {s_idx} has {len(raw_section)} measurement(s) — "
                    f"minimum {_MIN_POINTS_PER_SECTION} required",
                    "BAD_ARGS",
                )
            section_pts: list[RunoutMeasurement] = []
            for m_idx, raw_m in enumerate(raw_section):
                if not isinstance(raw_m, dict):
                    return err_payload(
                        f"measurements_per_cross_section[{s_idx}][{m_idx}] must be an object",
                        "BAD_ARGS",
                    )
                try:
                    section_pts.append(RunoutMeasurement.from_dict(raw_m))
                except (ValueError, KeyError, TypeError) as exc:
                    return err_payload(
                        f"section {s_idx} measurement {m_idx}: {exc}", "BAD_ARGS"
                    )
            sections.append(section_pts)

        try:
            spec = CircularRunoutSpec(
                measurements_per_cross_section=sections,
                tolerance_mm=a["tolerance_mm"],
                datum_axis_id=str(a.get("datum_axis_id", "A")),
            )
        except (ValueError, KeyError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        report = check_circular_runout(spec)
        return ok_payload(report.to_dict())

    _TOOL_REGISTERED = True

except ImportError:
    # Registry not available in pure unit-test context.
    # RunoutMeasurement, CircularRunoutSpec, CircularRunoutReport, and
    # check_circular_runout() remain fully usable.
    _TOOL_REGISTERED = False
