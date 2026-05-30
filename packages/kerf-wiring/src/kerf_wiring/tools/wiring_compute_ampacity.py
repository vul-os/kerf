"""
LLM tool: wiring_compute_ampacity

Computes NEC 2023 (NFPA 70-2023) wire ampacity (current-carrying capacity)
given conductor size, material, insulation rating, ambient temperature,
bundle count, and installation method.

References:
  - NEC 2023 Table 310.16 — base ampacity
  - NEC 2023 §310.15(B)(2)(a) — ambient temperature correction factor
  - NEC 2023 §310.15(B)(3)(a) — bundling/fill adjustment factor

Schema:
  {
    "awg": "12",
    "material": "Cu",
    "insulation_temp_c": 90,
    "ambient_c": 30.0,
    "bundle_count": 1,
    "installation": "conduit"
  }

Returns:
  ok_payload({
    "awg": "12",
    "material": "Cu",
    "insulation_temp_c": 90,
    "ambient_c": 30.0,
    "bundle_count": 1,
    "installation": "conduit",
    "base_ampacity_a": 30.0,
    "ambient_correction_factor": 1.0,
    "bundling_factor": 1.0,
    "derated_ampacity_a": 30.0,
    "notes": [...]
  })
  err_payload(...) on bad args or unsupported size.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_wiring._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # type: ignore


wiring_compute_ampacity_spec = ToolSpec(
    name="wiring_compute_ampacity",
    description=(
        "Compute NEC 2023 (NFPA 70-2023) wire ampacity — the safe current-carrying "
        "capacity of a conductor — given its size, material, insulation rating, "
        "ambient temperature, bundling conditions, and installation method.  "
        "Applies Table 310.16 base values plus §310.15(B)(2)(a) temperature "
        "correction and §310.15(B)(3)(a) bundling adjustment factors.  "
        "Supports AWG 14 through 4/0 and kcmil 250–750; copper (Cu) and "
        "aluminium (Al) conductors; 60/75/90 °C insulation ratings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "awg": {
                "type": "string",
                "description": (
                    "Wire size as AWG string or kcmil string.  "
                    "AWG: '14', '12', '10', '8', '6', '4', '3', '2', '1', "
                    "'1/0', '2/0', '3/0', '4/0'.  "
                    "kcmil: '250', '300', '350', '400', '500', '600', '700', '750'."
                ),
            },
            "material": {
                "type": "string",
                "enum": ["Cu", "Al"],
                "description": (
                    "'Cu' for copper (default) or 'Al' for aluminium.  "
                    "Aluminium is not rated below AWG 12 per NEC 310.16.  "
                    "Al ampacity is ~78% of Cu for the same AWG."
                ),
            },
            "insulation_temp_c": {
                "type": "integer",
                "enum": [60, 75, 90],
                "description": (
                    "Insulation temperature rating in °C: "
                    "60 (TW/UF), 75 (THWN/RHW), or 90 (THHN/THWN-2/XHHW-2).  "
                    "Most modern building wire is 90 °C THHN.  "
                    "Note NEC 110.14(C): terminal ratings may limit usable ampacity."
                ),
            },
            "ambient_c": {
                "type": "number",
                "description": (
                    "Ambient air temperature in °C.  NEC standard reference is 30 °C.  "
                    "Higher ambient reduces ampacity per §310.15(B)(2)(a).  "
                    "Must be less than insulation_temp_c."
                ),
            },
            "bundle_count": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Total number of current-carrying conductors in the same "
                    "raceway, conduit, or cable bundle.  "
                    "1–3: no derating; 4–6: 0.80; 7–9: 0.70; 10–20: 0.50 "
                    "(NEC Table 310.15(B)(3)(a)).  Neutral conductors carrying "
                    "only unbalanced current are typically NOT counted."
                ),
            },
            "installation": {
                "type": "string",
                "enum": ["conduit", "free_air", "cable_tray"],
                "description": (
                    "'conduit' (default) — raceway or conduit, Table 310.16.  "
                    "'free_air' — open air installation (Table 310.17 values not "
                    "yet embedded; conservative Table 310.16 values used).  "
                    "'cable_tray' — follows NEC 392.80, same as conduit for bundles."
                ),
            },
        },
        "required": ["awg"],
    },
)


@register(wiring_compute_ampacity_spec, write=False)
async def wiring_compute_ampacity(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args JSON: {e}", "BAD_ARGS")

    awg = a.get("awg")
    if awg is None:
        return err_payload("'awg' is required", "BAD_ARGS")

    material = a.get("material", "Cu")
    insulation_temp_c = a.get("insulation_temp_c", 90)
    ambient_c = float(a.get("ambient_c", 30.0))
    bundle_count = int(a.get("bundle_count", 1))
    installation = a.get("installation", "conduit")

    # Validate enum-like args before calling the engine
    if material not in ("Cu", "Al"):
        return err_payload(
            f"material must be 'Cu' or 'Al', got '{material}'", "BAD_ARGS"
        )
    if insulation_temp_c not in (60, 75, 90):
        return err_payload(
            f"insulation_temp_c must be 60, 75, or 90; got {insulation_temp_c}",
            "BAD_ARGS",
        )
    if installation not in ("conduit", "free_air", "cable_tray"):
        return err_payload(
            f"installation must be 'conduit', 'free_air', or 'cable_tray'; "
            f"got '{installation}'",
            "BAD_ARGS",
        )
    if bundle_count < 1:
        return err_payload("bundle_count must be >= 1", "BAD_ARGS")

    try:
        from kerf_wiring.ampacity import compute_ampacity
        result = compute_ampacity(
            awg=awg,
            material=material,
            insulation_temp_c=insulation_temp_c,
            ambient_c=ambient_c,
            bundle_count=bundle_count,
            installation=installation,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"ampacity calculation failed: {exc}", "ERROR")

    return ok_payload({
        "awg": result.awg,
        "material": result.material,
        "insulation_temp_c": result.insulation_temp_c,
        "ambient_c": result.ambient_c,
        "bundle_count": result.bundle_count,
        "installation": result.installation,
        "base_ampacity_a": result.base_ampacity_a,
        "ambient_correction_factor": result.ambient_correction_factor,
        "bundling_factor": result.bundling_factor,
        "derated_ampacity_a": result.derated_ampacity_a,
        "notes": result.notes,
    })
