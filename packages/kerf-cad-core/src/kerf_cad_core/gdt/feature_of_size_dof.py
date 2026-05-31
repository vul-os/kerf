"""
kerf_cad_core.gdt.feature_of_size_dof — ASME Y14.5-2018 Feature of Size (FOS) DOF enumerator.

Given a feature of size and its applied geometric tolerance, enumerates the
Degrees of Freedom (DOF) that the tolerance *constrains* vs those that remain
*released* (free), per ASME Y14.5-2018 §4.7 (Datum Reference Frame and DOF)
and §7.3 (Features of Size — Position / Orientation / Runout).

DOF coordinate convention (ISO / ASME Y14.5-2018 §4.7):
  Translations:  TX (along X), TY (along Y), TZ (along Z)
  Rotations:     RX (about X),  RY (about Y),  RZ (about Z)
  Total:         6 DOF maximum

Feature primary DOF table (from §4.7 + §7.3):
  Cylinder / Hole (axis along Z):
    position          → constrains TX, TY  (2 translation DOFs; axis location)
    perpendicularity  → constrains RX, RY  (2 rotation DOFs; axis orientation)
    parallelism       → constrains RX, RY  (same — parallelism = orientation to ref)
    angularity        → constrains RX, RY  (orientation relative to reference)
    runout            → constrains TX, TY, RX, RY  (4 DOF — circular runout couples
                        location and orientation per §7.3.4)
    total_runout      → constrains TX, TY, RX, RY  (same coupling, §7.3.5)

  Hole (identical DOF model as cylinder):
    same as cylinder — hole is a cylindrical FOS; the direction of material is
    inside vs outside but the DOF analysis is identical.

  Slot / Width (centre-plane in XZ, open along Y):
    position          → constrains TX  (one translation — perpendicular to the
                        slot's centre-plane; §7.3 width FOS)
    perpendicularity  → constrains RX, RY  (2 rotation DOFs; slot wall orientation)
    parallelism       → constrains RX, RY
    angularity        → constrains RX, RY

  Sphere (centre point):
    position          → constrains TX, TY, TZ  (3 translation DOFs; point location)
    (orientation tolerances not physically meaningful on a sphere — returns no DOFs)

  Planar pair (two opposing planes, e.g. a tab or boss width):
    position          → constrains TX  (one translation perpendicular to planes; §7.3)
    perpendicularity  → constrains RX, RY  (two rotations — wall angular error)
    parallelism       → constrains RX, RY
    angularity        → constrains RX, RY

Honest caveat
-------------
This is a feature-class lookup table derived from §4.7 + §7.3. It gives
*primary* (single-feature) DOF contribution only. Complex use cases are
explicitly out of scope:
  - Pattern-of-features compositions (§11.3) where DOFs compound across
    multiple instances are not modelled.
  - Simultaneous requirement and composite tolerance (§10.5 PLTZF/FRTZF)
    interactions are not resolved here.
  - The chosen coordinate frame (which axis is the feature's primary axis)
    is a modelling assumption; the caller must orient the result to the
    actual drawing DRF.
  - Datum shift effects on effective tolerance zone size (§4.5) are
    separate — see `compute_datum_shift` in `datum_shift_check`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALL_DOF: list[str] = ["TX", "TY", "TZ", "RX", "RY", "RZ"]

_VALID_FEATURE_TYPES = frozenset({
    "cylinder",
    "hole",
    "slot",
    "sphere",
    "planar_pair",
    "width",       # synonym for slot / planar_pair (width FOS)
})

_VALID_TOLERANCE_SYMBOLS = frozenset({
    "position",
    "perpendicularity",
    "parallelism",
    "angularity",
    "runout",
    "total_runout",
})

_CODE_SECTION = "ASME Y14.5-2018 §4.7 (Datum Reference Frame and DOF) + §7.3 (FOS tolerances)"

_HONEST_CAVEAT = (
    "Feature-class DOF lookup table per §4.7 + §7.3: gives PRIMARY single-feature "
    "DOF contribution (cylinder/hole axis assumed along Z). Out of scope: "
    "(1) pattern-of-features compositions (§11.3) where DOFs compound across "
    "multiple feature instances; (2) simultaneous-requirement and composite-tolerance "
    "PLTZF/FRTZF interactions (§10.5); (3) coordinate-frame orientation — the "
    "caller must map TX/TY/TZ/RX/RY/RZ to the actual part drawing DRF; "
    "(4) datum-shift effects on effective tolerance zone size (§4.5) — use "
    "gdt_compute_datum_shift separately."
)

# ---------------------------------------------------------------------------
# DOF lookup table
# Keyed by (normalised_feature_type, normalised_tolerance_symbol)
# Value: sorted list of DOF strings that this tolerance constrains
# ---------------------------------------------------------------------------

# Cylinder and hole share identical DOF analysis (§7.3 — FOS of cylindrical type).
# Axis assumed along Z; location tolerance constrains the two radial translations (TX, TY);
# orientation tolerance constrains the two tilts (RX, RY).
_CYLINDER_HOLE_DOF: dict[str, list[str]] = {
    "position":         ["TX", "TY"],
    "perpendicularity": ["RX", "RY"],
    "parallelism":      ["RX", "RY"],
    "angularity":       ["RX", "RY"],
    # Runout couples radial location + tilt of axis (§7.3.4 / §7.3.5).
    "runout":           ["RX", "RY", "TX", "TY"],
    "total_runout":     ["RX", "RY", "TX", "TY"],
}

# Slot / width / planar_pair — centre-plane FOS (§7.3).
# Centre-plane assumed in XZ; position constrains TX (perpendicular to centre-plane).
# Orientation tolerances constrain the wall tilts (RX, RY).
_SLOT_PLANAR_DOF: dict[str, list[str]] = {
    "position":         ["TX"],
    "perpendicularity": ["RX", "RY"],
    "parallelism":      ["RX", "RY"],
    "angularity":       ["RX", "RY"],
    # Runout is not a standard callout on slots/planar-pairs; return empty.
    "runout":           [],
    "total_runout":     [],
}

# Sphere — point FOS (§7.3).
# Position constrains all three translations (TX, TY, TZ) — sphere centre point location.
# Orientation tolerances are physically meaningless on a sphere (it is rotationally
# symmetric about every axis) — return empty list.
_SPHERE_DOF: dict[str, list[str]] = {
    "position":         ["TX", "TY", "TZ"],
    "perpendicularity": [],
    "parallelism":      [],
    "angularity":       [],
    "runout":           [],
    "total_runout":     [],
}

# Combined lookup: normalised feature type → per-symbol dict
_DOF_TABLE: dict[str, dict[str, list[str]]] = {
    "cylinder":    _CYLINDER_HOLE_DOF,
    "hole":        _CYLINDER_HOLE_DOF,
    "slot":        _SLOT_PLANAR_DOF,
    "width":       _SLOT_PLANAR_DOF,     # synonym
    "planar_pair": _SLOT_PLANAR_DOF,
    "sphere":      _SPHERE_DOF,
}

# Required datum count (minimum) per tolerance symbol to be meaningful:
# - position:        needs a full DRF (primary at minimum, typically primary+secondary)
# - orientation tols: need at least one orientation-reference datum
# This is informational metadata for inspection planning.
_DATUM_REQUIRED_COUNT: dict[str, int] = {
    "position":         1,
    "perpendicularity": 1,
    "parallelism":      1,
    "angularity":       1,
    "runout":           1,
    "total_runout":     1,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FOSSpec:
    """
    Specification for a Feature of Size (FOS) with its applied geometric tolerance.

    Attributes
    ----------
    feature_type:
        Geometric type of the feature of size.
        One of: "cylinder" | "hole" | "slot" | "sphere" | "planar_pair" | "width"
    tolerance_symbol:
        The GD&T characteristic applied to this feature.
        One of: "position" | "perpendicularity" | "parallelism" |
                "angularity" | "runout" | "total_runout"
    """
    feature_type: str
    tolerance_symbol: str

    def __post_init__(self) -> None:
        ft = str(self.feature_type).strip().lower()
        if ft not in _VALID_FEATURE_TYPES:
            raise ValueError(
                f"FOSSpec: feature_type must be one of "
                f"{sorted(_VALID_FEATURE_TYPES)}, got '{self.feature_type}'"
            )
        self.feature_type = ft

        ts = str(self.tolerance_symbol).strip().lower()
        if ts not in _VALID_TOLERANCE_SYMBOLS:
            raise ValueError(
                f"FOSSpec: tolerance_symbol must be one of "
                f"{sorted(_VALID_TOLERANCE_SYMBOLS)}, got '{self.tolerance_symbol}'"
            )
        self.tolerance_symbol = ts

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_type": self.feature_type,
            "tolerance_symbol": self.tolerance_symbol,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FOSSpec":
        return cls(
            feature_type=d["feature_type"],
            tolerance_symbol=d["tolerance_symbol"],
        )


@dataclass
class FOSDoFReport:
    """
    DOF enumeration result for a Feature of Size + tolerance combination.

    Attributes
    ----------
    dof_constrained:
        Degrees of freedom constrained by the tolerance (from the 6-DOF set
        TX, TY, TZ, RX, RY, RZ).
    dof_released:
        Degrees of freedom NOT constrained by this tolerance — remain free.
    total_constrained:
        Number of DOFs constrained (len(dof_constrained)).
    datum_required_count:
        Minimum number of datum references typically required in the feature
        control frame for this tolerance type.
    code_section:
        ASME Y14.5-2018 section references.
    honest_caveat:
        Scope limitation notice.
    """
    dof_constrained: list[str]
    dof_released: list[str]
    total_constrained: int
    datum_required_count: int
    code_section: str = _CODE_SECTION
    honest_caveat: str = _HONEST_CAVEAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "dof_constrained": self.dof_constrained,
            "dof_released": self.dof_released,
            "total_constrained": self.total_constrained,
            "datum_required_count": self.datum_required_count,
            "code_section": self.code_section,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_fos_dof(fos: FOSSpec) -> FOSDoFReport:
    """
    Enumerate the DOFs constrained vs released by a feature of size + tolerance.

    Per ASME Y14.5-2018 §4.7 + §7.3:
    - Cylinder/hole + position → constrains TX, TY (axis radial location)
    - Cylinder/hole + perpendicularity/parallelism/angularity → constrains RX, RY (axis tilt)
    - Cylinder/hole + runout/total_runout → constrains TX, TY, RX, RY (§7.3.4/§7.3.5)
    - Slot/width/planar_pair + position → constrains TX (centre-plane location)
    - Slot/width/planar_pair + orientation → constrains RX, RY
    - Sphere + position → constrains TX, TY, TZ (all translations)
    - Sphere + orientation → constrains nothing (rotationally symmetric)

    Parameters
    ----------
    fos:
        FOSSpec with feature_type and tolerance_symbol (normalised in __post_init__).

    Returns
    -------
    FOSDoFReport
        Contains dof_constrained, dof_released, total_constrained,
        datum_required_count, code_section, honest_caveat.

    Raises
    ------
    ValueError
        If fos is not a FOSSpec instance (guard against direct dict passing).
    """
    if not isinstance(fos, FOSSpec):
        raise ValueError(
            "compute_fos_dof: fos must be a FOSSpec instance; "
            "use FOSSpec(feature_type=..., tolerance_symbol=...) to construct it"
        )

    # Lookup constrained DOFs — guaranteed present since FOSSpec.__post_init__
    # validates both keys against the known sets.
    constrained: list[str] = sorted(
        _DOF_TABLE[fos.feature_type][fos.tolerance_symbol]
    )

    constrained_set = set(constrained)
    released: list[str] = [d for d in _ALL_DOF if d not in constrained_set]

    return FOSDoFReport(
        dof_constrained=constrained,
        dof_released=released,
        total_constrained=len(constrained),
        datum_required_count=_DATUM_REQUIRED_COUNT[fos.tolerance_symbol],
    )


# ---------------------------------------------------------------------------
# LLM tool wrapper (gated import — registry not available in unit-test context)
# ---------------------------------------------------------------------------

try:
    import json as _json
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]  # noqa: F401

    _gdt_compute_fos_dof_spec = ToolSpec(
        name="gdt_compute_fos_dof",
        description=(
            "Enumerate the Degrees of Freedom (DOF) constrained vs released by "
            "a Feature of Size (FOS) + geometric tolerance combination, per "
            "ASME Y14.5-2018 §4.7 (Datum Reference Frame and DOF) + §7.3 (FOS).\n"
            "\n"
            "Critical for inspection planning: identifies which translation (TX/TY/TZ) "
            "and rotation (RX/RY/RZ) DOFs are controlled by the tolerance, and which "
            "remain free (require additional datums or gauging to constrain).\n"
            "\n"
            "feature_type options:\n"
            "  cylinder   — external cylindrical shaft / pin (axis along Z assumed)\n"
            "  hole       — internal cylindrical bore / hole (same DOF as cylinder)\n"
            "  slot       — open slot (centre-plane FOS, §7.3)\n"
            "  width      — synonym for slot\n"
            "  planar_pair — two opposing flat surfaces (tab, boss — centre-plane FOS)\n"
            "  sphere     — spherical feature (point FOS, §7.3)\n"
            "\n"
            "tolerance_symbol options:\n"
            "  position        — location of feature axis/centre-plane/point\n"
            "  perpendicularity — 90° orientation to reference datum\n"
            "  parallelism     — parallel orientation to reference datum\n"
            "  angularity      — angular orientation to reference datum\n"
            "  runout          — circular runout (§7.3.4 — couples axis + tilt)\n"
            "  total_runout    — total runout (§7.3.5 — same DOF coupling)\n"
            "\n"
            "DOF model (cylinder/hole — axis along Z):\n"
            "  position         → constrains TX, TY\n"
            "  perpendicularity / parallelism / angularity → constrains RX, RY\n"
            "  runout / total_runout → constrains TX, TY, RX, RY\n"
            "\n"
            "DOF model (slot/width/planar_pair):\n"
            "  position → constrains TX\n"
            "  orientation → constrains RX, RY\n"
            "\n"
            "DOF model (sphere):\n"
            "  position → constrains TX, TY, TZ\n"
            "  orientation → constrains nothing (symmetric)\n"
            "\n"
            "Returns {dof_constrained, dof_released, total_constrained, "
            "datum_required_count, code_section, honest_caveat}.\n"
            "\n"
            "HONEST FLAG: feature-class lookup table only; does not handle complex "
            "pattern-of-feature compositions (§11.3) or PLTZF/FRTZF interactions (§10.5)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "feature_type": {
                    "type": "string",
                    "enum": sorted(_VALID_FEATURE_TYPES),
                    "description": (
                        "Geometric type of the feature of size: "
                        "cylinder | hole | slot | sphere | planar_pair | width"
                    ),
                },
                "tolerance_symbol": {
                    "type": "string",
                    "enum": sorted(_VALID_TOLERANCE_SYMBOLS),
                    "description": (
                        "GD&T characteristic applied to this feature: "
                        "position | perpendicularity | parallelism | "
                        "angularity | runout | total_runout"
                    ),
                },
            },
            "required": ["feature_type", "tolerance_symbol"],
        },
    )

    @register(_gdt_compute_fos_dof_spec, write=False)
    async def run_gdt_compute_fos_dof(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        for field_name in ("feature_type", "tolerance_symbol"):
            if field_name not in a:
                return err_payload(f"'{field_name}' is required", "BAD_ARGS")

        try:
            fos = FOSSpec.from_dict(a)
        except (ValueError, KeyError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        try:
            report = compute_fos_dof(fos)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(report.to_dict())

    _TOOL_REGISTERED = True

except ImportError:
    # Registry not available (pure unit-test context or kerf_chat not installed).
    # FOSSpec, FOSDoFReport, and compute_fos_dof() remain fully usable.
    _TOOL_REGISTERED = False
