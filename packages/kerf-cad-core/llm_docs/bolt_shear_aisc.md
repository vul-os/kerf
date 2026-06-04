# arch_check_bolt_shear

*Module: `kerf_cad_core.arch.bolt_shear_aisc` · Domain: cad*

## Description

AISC 360-22 §J3.6 bolt-group shear strength check (LRFD).

Supports single-shear and double-shear, bearing-type and slip-critical connections.  Checks three limit states per bolt:
  1. Bolt shear §J3.6: φ·Rn = φ_v·Fnv·Ab·n_planes (φ_v=0.75)
  2. Bearing §J3.10a: φ·Rn = φ·2.4·d·t·Fu
  3. Tearout §J3.10b: φ·Rn = φ·1.2·Lc·t·Fu (Lc = Le − dh/2)
  4. Slip-critical §J3.8 (optional): Rn = μ·Du·hf·Tb·ns per bolt (φ_sc=1.00 std holes)

Table J3.2 Fnv: A325-N=54 ksi, A325-X=68 ksi, A490-N=68 ksi, A490-X=84 ksi, A307=27 ksi.

Returns phi_Rn_per_bolt_kip, phi_Rn_group_kip, bearing_phi_Rn_kip, tearout_phi_Rn_kip, governing_mode, slip_critical_phi_Rn_kip (null if bearing-type), and honest_caveat.

SCOPE: LRFD only. Shear-lag (§J4.3), combined tension+shear (§J3.7), block shear (§J4.3), eccentric bolt groups (ICR), and weld+bolt combined groups (§J8) NOT checked. Fatigue NOT included. A307 not permitted for slip-critical connections.

## Input schema

```json
{
  "type": "object",
  "required": [
    "grade",
    "diameter_in",
    "num_bolts",
    "plate_thickness_in",
    "end_distance_in"
  ],
  "properties": {
    "grade": {
      "type": "string",
      "enum": [
        "A325-N",
        "A325-X",
        "A490-N",
        "A490-X",
        "A307"
      ],
      "description": "Bolt grade and thread condition. -N = threads IN the shear plane; -X = threads EXCLUDED. A307 = Grade A (threads in shear plane only)."
    },
    "diameter_in": {
      "type": "number",
      "description": "Nominal bolt diameter (inches). Common: 0.5, 0.625, 0.75, 0.875, 1.0. Must be > 0."
    },
    "threads_in_shear_plane": {
      "type": "boolean",
      "description": "Informational: True if threads are in the shear plane (already encoded in the grade suffix -N/-X). Default true."
    },
    "num_shear_planes": {
      "type": "integer",
      "description": "Number of shear planes per bolt. 1 = single-shear (lap splice); 2 = double-shear (web connection). Default 1."
    },
    "num_bolts": {
      "type": "integer",
      "description": "Total number of bolts in the group. Must be >= 1."
    },
    "plate_thickness_in": {
      "type": "number",
      "description": "Thickness of the bearing/tearout plate \u2014 thinnest element at the bolt hole (inches). Must be > 0."
    },
    "plate_Fu_ksi": {
      "type": "number",
      "description": "Ultimate tensile strength of the bearing plate (ksi). Default 58.0 ksi (A36 per AISC Table 2-4)."
    },
    "end_distance_in": {
      "type": "number",
      "description": "Distance from bolt centre to the end of the connected part in the direction of load (inches). Used for tearout Lc. AISC \u00a7J3.4 minimum \u2248 1.25\u00b7d. Must be > 0."
    },
    "spacing_in": {
      "type": "number",
      "description": "Centre-to-centre bolt spacing along load direction (inches). AISC \u00a7J3.3 preferred = 3d. Default 3.0 in. Must be > 0."
    },
    "slip_critical": {
      "type": "boolean",
      "description": "If true, also compute slip-critical design strength \u00a7J3.8. Requires standard bolt diameter (Table J3.1). NOT valid for A307. Default false."
    },
    "faying_class": {
      "type": "string",
      "enum": [
        "A",
        "B"
      ],
      "description": "Faying surface class for slip-critical connections. 'A' = unpainted clean mill scale or hot-dip galvanised (\u03bc=0.35); 'B' = unpainted blast-cleaned (\u03bc=0.50). Default 'A'."
    },
    "num_slip_planes": {
      "type": "integer",
      "description": "Number of slip planes (faying surfaces). Usually equals num_shear_planes. Default 1."
    },
    "phi_v": {
      "type": "number",
      "description": "Resistance factor for bolt shear. Default 0.75 per AISC 360-22 \u00a7J3.6."
    },
    "phi_br": {
      "type": "number",
      "description": "Resistance factor for bearing and tearout. Default 0.75 per AISC 360-22 \u00a7J3.10."
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_bolt_shear",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
