# arch_check_diaphragm_shear

*Module: `kerf_cad_core.arch.diaphragm_shear_tools` · Domain: cad*

## Description

Check in-plane shear capacity of a horizontal wood or cold-formed steel (metal deck) diaphragm per AWC SDPWS-2021 §4.2 (wood) or AISI S400-20 / SDI DDM04 (steel deck), with IBC §2305.2 aspect-ratio check.

Checks performed:
  1. Applied unit shear: v = V_lateral_lbs / length_along_load (plf)
  2. Allowable unit shear from SDPWS-2021 Table 4.2A (wood) or SDI DDM04 (steel);
     species factor C_s (DF_L=1.0, SP=1.0, HF=0.9, SPF=0.8) applied to wood.
     Unblocked: 50% reduction per SDPWS §4.2.7 Case 1.
  3. Aspect ratio AR = L/W ≤ 4:1 (wood, SDPWS Table 4.2.4) or ≤ 2:1 (steel deck).
  4. DCR = v / v_allow ≤ 1.0

Returns unit_shear_v_plf, allowable_unit_shear_v_allow_plf, demand_capacity_ratio, adequate, governing_factor, honest_caveat.

SCOPE: In-plane unit shear only. Chord forces (tension/compression at diaphragm boundaries) are NOT calculated. Diaphragm deflection NOT calculated. ASD basis throughout — V_lateral_lbs must reflect the governing ASD load combo. SDPWS Table 4.2A values are for SDC A–C; SDC D–F may require additional checks. Inputs: all dimensions in mm; V_lateral_lbs in US pounds; unit shear output in plf.

## Input schema

```json
{
  "type": "object",
  "required": [
    "length_along_load_mm",
    "width_perp_to_load_mm",
    "sheathing_type",
    "nail_spacing_mm",
    "blocked",
    "framing_species",
    "V_lateral_lbs"
  ],
  "properties": {
    "length_along_load_mm": {
      "type": "number",
      "description": "Diaphragm dimension parallel to the lateral load direction (mm). Shear V is distributed along this length: v = V/L. Must be > 0."
    },
    "width_perp_to_load_mm": {
      "type": "number",
      "description": "Diaphragm dimension perpendicular to the lateral load direction (mm). Chord members run along this edge. Used for aspect-ratio check AR=L/W. Must be > 0."
    },
    "sheathing_type": {
      "type": "string",
      "enum": [
        "plywood_15_32",
        "plywood_19_32",
        "osb_15_32",
        "metal_deck_22ga",
        "metal_deck_18ga"
      ],
      "description": "Sheathing material and thickness:\n  plywood_15_32   \u2014 15/32\" structural plywood (SDPWS Table 4.2A)\n  plywood_19_32   \u2014 19/32\" structural plywood (SDPWS Table 4.2A)\n  osb_15_32       \u2014 15/32\" OSB (=plywood capacity per SDPWS \u00a74.2.3)\n  metal_deck_22ga \u2014 22 ga cold-formed steel deck (SDI DDM04 36/6 ASD)\n  metal_deck_18ga \u2014 18 ga cold-formed steel deck (SDI DDM04 36/6 ASD)"
    },
    "nail_spacing_mm": {
      "type": "number",
      "description": "Nail spacing at panel edges (mm). Ignored for metal deck. Typical: 152.4 mm (6\"), 101.6 mm (4\"), 63.5 mm (2.5\"), 50.8 mm (2\"). Allowable shear is linearly interpolated between SDPWS table entries. Must be between 50 and 165 mm for wood."
    },
    "blocked": {
      "type": "boolean",
      "description": "True = blocked diaphragm (all panel edges supported and blocked). False = unblocked (unsupported edges at intermediate framing); allowable shear reduced by 0.50 per SDPWS \u00a74.2.7."
    },
    "framing_species": {
      "type": "string",
      "enum": [
        "DF_L",
        "SP",
        "HF",
        "SPF"
      ],
      "description": "Framing lumber species group (SDPWS Table 4.2A footnote 3). Ignored for metal deck.\n  DF_L \u2014 Douglas Fir-Larch (C_s=1.00, reference)\n  SP   \u2014 Southern Pine    (C_s=1.00)\n  HF   \u2014 Hem-Fir           (C_s=0.90)\n  SPF  \u2014 Spruce-Pine-Fir   (C_s=0.80)"
    },
    "V_lateral_lbs": {
      "type": "number",
      "description": "Total applied lateral (in-plane) shear force (US pounds, ASD level). Must reflect the governing ASD load combination per ASCE 7 \u00a72.4. Must be \u2265 0."
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_diaphragm_shear",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
