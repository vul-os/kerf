"""
kerf_cad_core.gdt.runout_check — ASME Y14.5-2018 §13 / ISO 1101 §18 Runout checker.

Verifies circular runout and total runout tolerance compliance for a rotational
feature given a set of inspection points measured around a datum axis.

ASME Y14.5-2018 references:
  §13.1  — Runout: general definition; applies to surfaces of revolution
           relative to a datum axis.
  §13.2  — Circular Runout: measured at each cross-sectional circle
           independently; indicator traverses a single circle without axial
           movement; tolerance = full indicator movement (FIM) at any
           single circular element.
  §13.3  — Total Runout: tolerance applies to the entire surface simultaneously
           during a full indicator movement along the datum axis; captures both
           circular form error and taper/coaxiality combined.

ISO 1101:2017 §18 (Runout):
  §18.3  — Circular run-out tolerance: each circular section must stay within
           a tolerance band of width t centred on the nominal profile at that
           axial position.
  §18.4  — Total run-out tolerance: the entire surface must stay within a
           tolerance band of width t when the indicator traverses the full
           axial extent.

Physics summary
---------------
Given N measurement points at various (theta, z) pairs with measured radii R_i:

Circular runout (ASME §13.2 / ISO §18.3):
  1. Group points by axial position z (cross-sectional slices).
  2. For each slice: circular_runout_at_z = max(R_i) - min(R_i)
     (= Full Indicator Movement in that cross section)
  3. Overall circular runout = max over all slices.
  Compliant when: circular_runout ≤ tolerance_mm.

Total runout (ASME §13.3 / ISO §18.4):
  1. Consider ALL points across all axial positions together.
  2. total_runout = max(R_i) - min(R_i)  [over ALL points]
  Compliant when: total_runout ≤ tolerance_mm.

Note: total_runout ≥ circular_runout always (total scope ≥ per-section scope).

Figure of Merit (FoM):
  fom = max_runout / tolerance_mm
  fom < 1.0 → compliant; fom >= 1.0 → non-compliant.

Honest caveat
-------------
This implementation assumes an **ideal datum axis** — the axis is perfectly
defined by the datum (e.g. datum A spindle axis), and all radii are measured
orthogonally from that axis.  It does NOT compute the Chebyshev-optimal (minimum
zone) axis fit from a cloud of measured points (that requires iterative
optimisation per ASME B89.3.1 / ISO 12181-1 §4.3).  Callers supplying
inspection data from a real CMM must pre-process the data to extract radii
relative to their best-fit axis before passing them to this function.

Additionally, total runout as defined here is the radial-only variant (max R -
min R over all points), which corresponds to the common CMM single-axis traversal
measure.  The full ASME §13.3 total runout also includes axial deviation for
face runout surfaces; axial deviation checking is not implemented.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

_CODE_SECTION = "ASME Y14.5-2018 §13 (Runout) + ISO 1101:2017 §18"

_HONEST_CAVEAT = (
    "Ideal datum axis assumed: all radii are measured orthogonally from a "
    "perfectly-defined datum axis. Chebyshev-optimal (minimum zone) axis fit "
    "(ASME B89.3.1 / ISO 12181-1 §4.3) is not performed — callers must "
    "pre-process CMM point clouds to radii relative to their best-fit axis. "
    "Total runout is radial-only (max R - min R over all points); axial "
    "deviation for face-runout surfaces (ASME §13.3 full definition) is not "
    "checked. Circular runout per-section uses grouping by exact z value; "
    "real CMM data may require z-binning tolerance before passing."
)

_VALID_RUNOUT_TYPES = frozenset({"circular", "total"})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class InspectionPoint:
    """
    A single measured point on a surface of revolution during runout inspection.

    Attributes
    ----------
    theta_deg:
        Angular position of the measurement, in degrees [0, 360).
    axial_z_mm:
        Axial position along the datum axis in mm.
    radius_measured_mm:
        Measured radial distance from the datum axis to the surface (mm, > 0).
    """
    theta_deg: float
    axial_z_mm: float
    radius_measured_mm: float

    def __post_init__(self) -> None:
        try:
            self.theta_deg = float(self.theta_deg)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"InspectionPoint: theta_deg must be numeric, got '{self.theta_deg}'"
            ) from exc

        try:
            self.axial_z_mm = float(self.axial_z_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"InspectionPoint: axial_z_mm must be numeric, got '{self.axial_z_mm}'"
            ) from exc

        try:
            r = float(self.radius_measured_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"InspectionPoint: radius_measured_mm must be numeric, "
                f"got '{self.radius_measured_mm}'"
            ) from exc
        if r <= 0:
            raise ValueError(
                f"InspectionPoint: radius_measured_mm must be > 0, got {r}"
            )
        self.radius_measured_mm = r

    def to_dict(self) -> dict[str, Any]:
        return {
            "theta_deg": self.theta_deg,
            "axial_z_mm": self.axial_z_mm,
            "radius_measured_mm": self.radius_measured_mm,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InspectionPoint":
        return cls(
            theta_deg=d["theta_deg"],
            axial_z_mm=d["axial_z_mm"],
            radius_measured_mm=d["radius_measured_mm"],
        )


@dataclass
class RunoutCheckSpec:
    """
    Specification for a runout tolerance check.

    Attributes
    ----------
    feature_id:
        Identifier for the feature being inspected (e.g. "shaft-OD", "bore-1").
    runout_tolerance_mm:
        Runout tolerance value from the feature control frame (mm, > 0).
    runout_type:
        "circular" (ASME §13.2 / ISO §18.3) or "total" (ASME §13.3 / ISO §18.4).
    nominal_radius_mm:
        Nominal (design) radius of the feature in mm (> 0). Used for reference
        and mean-radius deviation reporting; not used in compliance decision.
    """
    feature_id: str
    runout_tolerance_mm: float
    runout_type: str
    nominal_radius_mm: float

    def __post_init__(self) -> None:
        fid = str(self.feature_id).strip()
        if not fid:
            raise ValueError("RunoutCheckSpec: feature_id must not be empty")
        self.feature_id = fid

        try:
            tol = float(self.runout_tolerance_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"RunoutCheckSpec: runout_tolerance_mm must be numeric, "
                f"got '{self.runout_tolerance_mm}'"
            ) from exc
        if tol <= 0:
            raise ValueError(
                f"RunoutCheckSpec: runout_tolerance_mm must be > 0, got {tol}"
            )
        self.runout_tolerance_mm = tol

        rt = str(self.runout_type).strip().lower()
        if rt not in _VALID_RUNOUT_TYPES:
            raise ValueError(
                f"RunoutCheckSpec: runout_type must be one of "
                f"{sorted(_VALID_RUNOUT_TYPES)}, got '{self.runout_type}'"
            )
        self.runout_type = rt

        try:
            nom = float(self.nominal_radius_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"RunoutCheckSpec: nominal_radius_mm must be numeric, "
                f"got '{self.nominal_radius_mm}'"
            ) from exc
        if nom <= 0:
            raise ValueError(
                f"RunoutCheckSpec: nominal_radius_mm must be > 0, got {nom}"
            )
        self.nominal_radius_mm = nom

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "runout_tolerance_mm": self.runout_tolerance_mm,
            "runout_type": self.runout_type,
            "nominal_radius_mm": self.nominal_radius_mm,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunoutCheckSpec":
        return cls(
            feature_id=d["feature_id"],
            runout_tolerance_mm=d["runout_tolerance_mm"],
            runout_type=d.get("runout_type", "circular"),
            nominal_radius_mm=d["nominal_radius_mm"],
        )


@dataclass
class RunoutCheckReport:
    """
    Result of a runout tolerance check.

    Attributes
    ----------
    max_runout_mm:
        Worst-case runout value (mm).
        Circular: max FIM across all sections.
        Total: FIM over all points simultaneously.
    mean_radius_mm:
        Mean of all measured radii (mm). Indicates systematic axis offset from nominal.
    fom:
        Figure of Merit = max_runout_mm / runout_tolerance_mm.
        fom < 1.0 → compliant; fom >= 1.0 → non-compliant.
    compliant:
        True when max_runout_mm <= runout_tolerance_mm (i.e. fom <= 1.0).
    per_section_runout:
        List of dicts, one per axial z-section, each with:
          { z_mm, n_points, r_max_mm, r_min_mm, runout_mm }.
        For total runout, contains a single entry for the combined section.
    honest_caveat:
        Scope limitation notice per ASME B89.3.1 / ISO 12181-1.
    """
    max_runout_mm: float
    mean_radius_mm: float
    fom: float
    compliant: bool
    per_section_runout: list[dict]
    honest_caveat: str = _HONEST_CAVEAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_runout_mm": self.max_runout_mm,
            "mean_radius_mm": self.mean_radius_mm,
            "fom": self.fom,
            "compliant": self.compliant,
            "per_section_runout": self.per_section_runout,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def check_runout(
    spec: RunoutCheckSpec,
    points: list[InspectionPoint],
) -> RunoutCheckReport:
    """
    Verify circular or total runout tolerance compliance.

    Parameters
    ----------
    spec:
        RunoutCheckSpec with tolerance value, type, and nominal radius.
    points:
        List of InspectionPoint measurements.  Must have >= 2 points.

    Returns
    -------
    RunoutCheckReport
        Contains max_runout_mm, mean_radius_mm, fom, compliant, per_section_runout.

    Raises
    ------
    ValueError
        If points is empty or has fewer than 2 elements.

    Algorithm
    ---------
    Circular runout (ASME §13.2 / ISO §18.3):
        - Group points by axial_z_mm value.
        - For each group g: runout_g = max(R) - min(R)  [FIM at that section]
        - max_runout = max(runout_g over all groups)
        - Compliant when max_runout <= runout_tolerance_mm.

    Total runout (ASME §13.3 / ISO §18.4):
        - Consider all N points as a single set.
        - total_runout = max(R_i) - min(R_i)  over all points.
        - Compliant when total_runout <= runout_tolerance_mm.
        - per_section_runout reports one entry covering the full surface.
    """
    if not points:
        raise ValueError("check_runout: points list must not be empty")
    if len(points) < 2:
        raise ValueError(
            f"check_runout: need at least 2 inspection points, got {len(points)}"
        )

    radii = [p.radius_measured_mm for p in points]
    mean_radius = sum(radii) / len(radii)

    tol = spec.runout_tolerance_mm

    if spec.runout_type == "circular":
        # Group by axial z position (exact match — caller must pre-bin if needed)
        sections: dict[float, list[float]] = {}
        for p in points:
            sections.setdefault(p.axial_z_mm, []).append(p.radius_measured_mm)

        per_section: list[dict] = []
        max_runout = 0.0
        for z_val in sorted(sections.keys()):
            rs = sections[z_val]
            r_max = max(rs)
            r_min = min(rs)
            runout_z = r_max - r_min
            per_section.append({
                "z_mm": z_val,
                "n_points": len(rs),
                "r_max_mm": round(r_max, 10),
                "r_min_mm": round(r_min, 10),
                "runout_mm": round(runout_z, 10),
            })
            if runout_z > max_runout:
                max_runout = runout_z

    else:
        # total runout: all points in one section
        r_max = max(radii)
        r_min = min(radii)
        max_runout = r_max - r_min
        z_vals = [p.axial_z_mm for p in points]
        per_section = [{
            "z_mm": None,  # spans entire axial range
            "z_range_mm": [min(z_vals), max(z_vals)],
            "n_points": len(points),
            "r_max_mm": round(r_max, 10),
            "r_min_mm": round(r_min, 10),
            "runout_mm": round(max_runout, 10),
        }]

    max_runout = round(max_runout, 10)
    mean_radius = round(mean_radius, 10)
    fom = round(max_runout / tol, 10) if tol > 0 else math.inf
    compliant = max_runout <= tol

    return RunoutCheckReport(
        max_runout_mm=max_runout,
        mean_radius_mm=mean_radius,
        fom=fom,
        compliant=compliant,
        per_section_runout=per_section,
    )


# ---------------------------------------------------------------------------
# LLM tool wrapper (gated import — registry not available in unit-test context)
# ---------------------------------------------------------------------------

try:
    import json as _json
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]  # noqa: F401

    _gdt_check_runout_spec = ToolSpec(
        name="gdt_check_runout",
        description=(
            "Verify circular or total runout tolerance compliance for a rotational "
            "feature per ASME Y14.5-2018 §13 and ISO 1101:2017 §18.\n"
            "\n"
            "runout_type options:\n"
            "  'circular' (§13.2 / ISO §18.3) — checks each axial cross-section "
            "independently; compliant when FIM at each section ≤ tolerance.\n"
            "  'total'    (§13.3 / ISO §18.4) — checks entire surface simultaneously; "
            "compliant when max(R) - min(R) over ALL points ≤ tolerance.\n"
            "\n"
            "Each inspection_point requires:\n"
            "  theta_deg            — angular position (degrees)\n"
            "  axial_z_mm           — axial position along datum axis (mm)\n"
            "  radius_measured_mm   — measured radius from datum axis (mm, > 0)\n"
            "\n"
            "Returns {max_runout_mm, mean_radius_mm, fom, compliant, "
            "per_section_runout, honest_caveat}.\n"
            "\n"
            "fom (Figure of Merit) = max_runout / tolerance; fom < 1.0 = pass.\n"
            "\n"
            "HONEST FLAG: ideal datum axis assumed — radii must be pre-computed "
            "from a known datum axis. Chebyshev-optimal axis fit (ASME B89.3.1 / "
            "ISO 12181-1 §4.3) is not performed. Axial deviation for face runout "
            "surfaces (ASME §13.3 full definition) is not checked."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "feature_id": {
                    "type": "string",
                    "description": "Feature identifier, e.g. 'shaft-OD', 'bore-1'.",
                },
                "runout_tolerance_mm": {
                    "type": "number",
                    "description": "Runout tolerance from the feature control frame (mm, > 0).",
                },
                "runout_type": {
                    "type": "string",
                    "enum": ["circular", "total"],
                    "description": (
                        "'circular' — per cross-section FIM check (ASME §13.2); "
                        "'total' — full-surface FIM check (ASME §13.3)."
                    ),
                },
                "nominal_radius_mm": {
                    "type": "number",
                    "description": "Nominal design radius (mm, > 0). Used for reference reporting.",
                },
                "inspection_points": {
                    "type": "array",
                    "description": "List of measured inspection points (>= 2 required).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "theta_deg": {
                                "type": "number",
                                "description": "Angular position in degrees [0, 360).",
                            },
                            "axial_z_mm": {
                                "type": "number",
                                "description": "Axial position along datum axis (mm).",
                            },
                            "radius_measured_mm": {
                                "type": "number",
                                "description": "Measured radius from datum axis (mm, > 0).",
                            },
                        },
                        "required": ["theta_deg", "axial_z_mm", "radius_measured_mm"],
                    },
                    "minItems": 2,
                },
            },
            "required": [
                "feature_id",
                "runout_tolerance_mm",
                "runout_type",
                "nominal_radius_mm",
                "inspection_points",
            ],
        },
    )

    @register(_gdt_check_runout_spec, write=False)
    async def run_gdt_check_runout(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        for field_name in (
            "feature_id",
            "runout_tolerance_mm",
            "runout_type",
            "nominal_radius_mm",
            "inspection_points",
        ):
            if field_name not in a:
                return err_payload(f"'{field_name}' is required", "BAD_ARGS")

        try:
            spec = RunoutCheckSpec.from_dict(a)
        except (ValueError, KeyError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        raw_points = a.get("inspection_points")
        if not isinstance(raw_points, list):
            return err_payload("inspection_points must be an array", "BAD_ARGS")

        try:
            pts = [InspectionPoint.from_dict(p) for p in raw_points]
        except (ValueError, KeyError, TypeError) as exc:
            return err_payload(f"inspection_points parse error: {exc}", "BAD_ARGS")

        try:
            report = check_runout(spec, pts)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(report.to_dict())

    _TOOL_REGISTERED = True

except ImportError:
    # Registry not available (pure unit-test context or kerf_chat not installed).
    # InspectionPoint, RunoutCheckSpec, RunoutCheckReport, and check_runout()
    # remain fully usable.
    _TOOL_REGISTERED = False
