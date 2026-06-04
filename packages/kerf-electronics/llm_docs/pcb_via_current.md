# electronics_compute_pcb_via_current

*Module: `kerf_electronics.tools.pcb_via_current` · Domain: electronics*

## Description

Compute the maximum allowable DC current through a PCB plated-through-hole (PTH) via and recommend how many parallel vias are needed for a target current.

Model (IPC-2152 §6.3 + IPC-2221A §6):
  A_barrel [µm²] = π × D_drill_µm × t_plating_µm   (thin-wall barrel)
  I_via [A]      = 0.048 × ΔT^0.44 × A_mil²^0.725  (IPC-2221B Eq. 6-4)
  N_vias         = ceil(target_current_A / I_per_via)

Typical values:
  • 0.3 mm drill, 25 µm plating, ΔT=10 °C → ~1.0–1.5 A per via
  • 0.5 mm drill, 25 µm plating, ΔT=10 °C → ~1.6–2.2 A per via
  • IPC-6012 Class 2 minimum plating: 20 µm average (18 µm min)
  • High-reliability (Class 3): 25 µm average

Reference: IPC-2152 (2009) §6.3 + IPC-2221A (1998) §6.

Honest caveats:
  • IPC empirical model only. Adjacent copper planes increase capacity 10–30% (IPC-2152 cf_pl correction) — NOT modelled here (conservative).
  • Dense via arrays: mutual heating reduces individual capacity ~10–20% (IPC-7093 §4.1) — apply 0.80–0.90 derating factor manually.
  • Via fill: resin/copper-filled vias carry more heat than air-filled (assumed here).

Input:  { drill_diameter_mm, plating_thickness_um, via_length_mm, temp_rise_C?, copper_pad_size_mm?, target_current_A? }
Returns: { ok, max_current_A, via_cross_section_um2, equivalent_trace_width_mm, recommended_via_count_for_target_current, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "drill_diameter_mm": {
      "type": "number",
      "description": "Finished drill hole diameter [mm]. Typical: 0.20\u20130.30 mm (microvias), 0.30\u20130.60 mm (standard signal), 0.60\u20131.00 mm (power/thermal). IPC-2221A \u00a79.1 minimum: 0.15 mm."
    },
    "plating_thickness_um": {
      "type": "number",
      "description": "Copper plating thickness on via barrel wall [\u00b5m]. IPC-6012 Class 2 minimum: 20 \u00b5m average (18 \u00b5m min). IPC-6012 Class 3 (high-reliability): 25 \u00b5m average. Typical standard fab: 25 \u00b5m. Heavy copper HDI: 35\u201350 \u00b5m."
    },
    "via_length_mm": {
      "type": "number",
      "description": "Via barrel length [mm], equal to PCB board thickness. Used to compute barrel DC resistance (informational). Typical: 0.8 mm (thin board), 1.6 mm (standard FR-4), 2.4\u20133.2 mm (thick board)."
    },
    "temp_rise_C": {
      "type": "number",
      "description": "Allowable temperature rise above ambient [\u00b0C]. Default 10 \u00b0C (IPC-2221B conservative guideline). Typical: 10 \u00b0C (conservative), 20 \u00b0C (moderate), 30 \u00b0C (aggressive)."
    },
    "copper_pad_size_mm": {
      "type": "number",
      "description": "Annular copper pad diameter [mm] surrounding the via hole (informational; not used in the current calculation). Default 1.0 mm. Typical IPC-2221A: drill + 0.25\u20130.50 mm annular ring."
    },
    "target_current_A": {
      "type": "number",
      "description": "Optional target current [A] to determine how many parallel vias are needed. When provided, returns recommended_via_count_for_target_current = ceil(target / per_via). Example: 5 A target with 1.5 A per via \u2192 4 vias."
    }
  },
  "required": [
    "drill_diameter_mm",
    "plating_thickness_um",
    "via_length_mm"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_compute_pcb_via_current",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
