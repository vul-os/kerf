# electronics_check_diffpair_skew

*Module: `kerf_electronics.diffpair_skew_check` · Domain: electronics*

## Description

Check intra-pair length-matching skew for a PCB differential pair.

Computes propagation-velocity-aware time skew (mm and ps) from trace lengths and substrate dielectric constant, then verifies against the protocol skew budget.

Physics (Howard Johnson 'High-Speed Digital Design' §12.4 + IPC-2141A §6):
  v = c / √εr   (propagation velocity, c = 0.3 mm/ps)
  Δt = |L_pos − L_neg| / v

Protocol budgets (intra-pair):
  hdmi_21  → 15 ps  (HDMI 2.1 Spec §10.4.5)
  usb_30   → 20 ps  (USB 3.0 Spec §6.9)
  pcie_40  →  2 ps  (PCIe CEM 4.0 §3.2.1)
  ddr5     →  5 ps  (JEDEC JESD79-5 §8.1)
  sata_iii → 15 ps  (SATA Rev 3.0 §8.2.2)
  custom   → supply custom_skew_budget_ps

HONEST: assumes single uniform εr; meander-delay skew NOT modelled; via/connector transitions NOT included; inter-pair skew NOT checked.

Input: { signal_name, pos_length_mm, neg_length_mm, [dielectric_constant_er=4.5], [protocol='hdmi_21'], [custom_skew_budget_ps] }

Returns: { ok, length_skew_mm, time_skew_ps, skew_budget_ps, compliant, recommended_max_length_mismatch_mm, propagation_velocity_mm_per_ps, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "signal_name": {
      "type": "string",
      "description": "Pair label, e.g. 'USB_DP'."
    },
    "pos_length_mm": {
      "type": "number",
      "description": "Routed length of positive (P) conductor [mm]."
    },
    "neg_length_mm": {
      "type": "number",
      "description": "Routed length of negative (N) conductor [mm]."
    },
    "dielectric_constant_er": {
      "type": "number",
      "description": "Effective relative permittivity \u03b5r of the substrate. FR4 typical = 4.5; Rogers 4350B \u2248 3.66; air = 1.0. Default: 4.5."
    },
    "protocol": {
      "type": "string",
      "enum": [
        "hdmi_21",
        "usb_30",
        "pcie_40",
        "ddr5",
        "sata_iii",
        "custom"
      ],
      "description": "Protocol to check against. Use 'custom' and supply custom_skew_budget_ps for non-standard interfaces."
    },
    "custom_skew_budget_ps": {
      "type": "number",
      "description": "Custom intra-pair skew budget [ps]. Required when protocol == 'custom'; ignored otherwise."
    }
  },
  "required": [
    "signal_name",
    "pos_length_mm",
    "neg_length_mm"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_check_diffpair_skew",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
