# arch_design_stair_stringer

*Module: `kerf_cad_core.arch.stair_stringer_tools` · Domain: cad*

## Description

Check a stair stringer (inclined beam) for IBC 2021 §1011 geometry code compliance (riser height 4–7 in, tread depth ≥ 11 in), and bending stress / deflection adequacy per AWC NDS-2018 §3.3 (sawn lumber) or AISC 360-22 §F2 (steel channel/HSS).

Model: stringer treated as simply-supported inclined beam.
  span L = √(total_run² + total_rise²)
  tributary width per stringer = stair_width / num_stringers
  w = (live_load_psf + dead_load_psf) × trib_width  [lb/in]
  M_max = w·L²/8   (UDL, Roark 9e §8 Table 8.1 case 2)
  δ_max = 5·w·L⁴/(384·E·I)
  Deflection limit: L/360 (IBC Table 1604.3)

Supported materials (material key):
  'sawn-DF-No2'       DF-Larch No.2 2×12 (Fb=875 psi, E=1.6e6 psi)
  'sawn-SP-No1'       Southern Pine No.1 2×12 (Fb=1500 psi, E=1.7e6 psi)
  'steel-C10x15.3'   AISC C10×15.3 A36 (Sx=13.5 in³, Ix=67.4 in⁴)
  'steel-HSS6x4x1/4' AISC HSS6×4×1/4 A500 Gr.B (Sx=8.53 in³, Ix=25.6 in⁴)

Returns: riser_compliant, tread_compliant, span_length_in, max_moment_in_lb, max_deflection_in, bending_dcr, deflection_dcr, governing_dcr, status ('ok'|'oversize'|'fail-bending'|'fail-deflection'|'fail-code'), warnings, honest_caveat.

SCOPE: BENDING ONLY — shear (NDS §4.4.3 / AISC §G2.1), bearing at connections, and lateral-torsional buckling NOT checked.

## Input schema

```json
{
  "type": "object",
  "required": [
    "num_treads",
    "riser_height_in",
    "tread_depth_in",
    "stair_width_in",
    "material"
  ],
  "properties": {
    "num_treads": {
      "type": "integer",
      "description": "Number of treads in the stair flight.  Must be \u2265 1.  Example: 13 for a typical floor-to-floor flight."
    },
    "riser_height_in": {
      "type": "number",
      "description": "Vertical riser height in inches.  IBC \u00a71011.5.2 commercial limit: 4\u20137 in.  Typical: 6.5\u20137.0 in."
    },
    "tread_depth_in": {
      "type": "number",
      "description": "Horizontal tread depth (nosing to nosing) in inches.  IBC \u00a71011.5.2 minimum: 11 in.  Typical: 11\u201312 in."
    },
    "stair_width_in": {
      "type": "number",
      "description": "Clear width of the stair in inches.  Typical: 36\u201348 in (3\u20134 ft)."
    },
    "material": {
      "type": "string",
      "enum": [
        "sawn-DF-No2",
        "sawn-SP-No1",
        "steel-C10x15.3",
        "steel-HSS6x4x1/4"
      ],
      "description": "Stringer material key.  'sawn-DF-No2' / 'sawn-SP-No1' for wood (AWC NDS-2018 \u00a73.3); 'steel-C10x15.3' / 'steel-HSS6x4x1/4' for steel (AISC 360-22 \u00a7F2)."
    },
    "num_stringers": {
      "type": "integer",
      "description": "Number of stringers supporting the stair (default 2).  Tributary load per stringer = total load / num_stringers."
    },
    "live_load_psf": {
      "type": "number",
      "description": "Design live load in psf (default 100 psf per ASCE 7-22 Table 4.3-1 assembly stair).  Residential stairs may use 40 psf (Table 4.3-1)."
    },
    "dead_load_psf": {
      "type": "number",
      "description": "Superimposed dead load in psf (default 15 psf \u2014 typical tread/riser finish + stringer self-weight estimate)."
    },
    "total_run_in": {
      "type": "number",
      "description": "Total horizontal run of the stair flight in inches.  If omitted or 0, computed as num_treads \u00d7 tread_depth_in."
    },
    "total_rise_in": {
      "type": "number",
      "description": "Total vertical rise of the stair flight in inches.  If omitted or 0, computed as num_treads \u00d7 riser_height_in."
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_design_stair_stringer",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
