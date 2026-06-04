# electronics_compute_crystal_load_caps

*Module: `kerf_electronics.crystal_load_cap` · Domain: electronics*

## Description

Compute external load capacitor values (C1, C2) for a Pierce crystal oscillator given the crystal's specified load capacitance CL and PCB stray capacitance. Required for accurate on-frequency operation.

Formula (NXP AN-2867 §3 + AVR ATmega §28.5):
  CL = (C1·C2)/(C1+C2) + C_stray
  Symmetric design: C1 = C2 = 2·(CL − C_stray)

C_stray = pcb_stray_capacitance_pF + mcu_pad_capacitance_pF

Gain-margin check uses a pessimistic gm = 4 mA/V estimate (NXP AN-2867 §4.2; ≥5× ESR for reliable startup).

HONEST: drive-level limiting NOT modelled; PI-network compensation for >20 MHz crystals NOT applied; C_stray is a first-order estimate; use C0G/NPO grade ±1% capacitors.

Input: { frequency_MHz, load_capacitance_CL_pF, esr_max_ohms, drive_level_uW, [pcb: {pcb_stray_capacitance_pF=2.0, mcu_pad_capacitance_pF=1.0}], [c1_override_pF], [c2_override_pF] }

Returns: { ok, C1_pF, C2_pF, effective_load_cap_pF, c1_c2_symmetric, gain_margin_check, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "frequency_MHz": {
      "type": "number",
      "description": "Crystal nominal frequency [MHz], e.g. 16.0."
    },
    "load_capacitance_CL_pF": {
      "type": "number",
      "description": "Crystal load capacitance CL from datasheet [pF]. Common values: 6, 8, 10, 12, 18, 20 pF."
    },
    "esr_max_ohms": {
      "type": "number",
      "description": "Crystal maximum equivalent series resistance ESR [\u03a9]. Typical: 50\u2013200 \u03a9 for MHz range crystals."
    },
    "drive_level_uW": {
      "type": "number",
      "description": "Crystal maximum rated drive level [\u00b5W]. Typical: 10\u2013200 \u00b5W; used for caveats only (not limiting computed caps)."
    },
    "pcb": {
      "type": "object",
      "description": "PCB and MCU parasitic capacitances. Defaults: pcb_stray_capacitance_pF=2.0, mcu_pad_capacitance_pF=1.0.",
      "properties": {
        "pcb_stray_capacitance_pF": {
          "type": "number",
          "description": "PCB stray capacitance per oscillator node [pF]. Typical: 1\u20135 pF. Default: 2.0 pF (NXP AN-2867 \u00a73.1)."
        },
        "mcu_pad_capacitance_pF": {
          "type": "number",
          "description": "MCU OSC pin input capacitance [pF]. From MCU datasheet. Typical: 1\u20135 pF. Default: 1.0 pF."
        }
      }
    },
    "c1_override_pF": {
      "type": "number",
      "description": "Custom C1 value [pF] for asymmetric verification. Provide both c1_override_pF and c2_override_pF to verify a specific asymmetric cap pair."
    },
    "c2_override_pF": {
      "type": "number",
      "description": "Custom C2 value [pF] for asymmetric verification. Provide both c1_override_pF and c2_override_pF to verify a specific asymmetric cap pair."
    }
  },
  "required": [
    "frequency_MHz",
    "load_capacitance_CL_pF",
    "esr_max_ohms",
    "drive_level_uW"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_compute_crystal_load_caps",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
