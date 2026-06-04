# Differential Pair Length Tuner

> Serpentine meander generation for differential pair and matched-length net groups — eliminate inter-pair skew and group delay mismatch.

**Module**: `packages/kerf-electronics/src/kerf_electronics/routing/push_shove.py`, `tools/diffpair.py`, `tools/length_tuning.py`
**Shipped**: Wave 12D1
**LLM tools**: `pcb_tune_diff_pair`, `pcb_check_length_match`

---

## What it is

High-speed interfaces (DDR4, PCIe, HDMI, USB 3) require that the positive and negative traces of each differential pair arrive at the receiver within a few picoseconds of each other (intra-pair skew) and that all byte-lane pairs arrive within a few hundred picoseconds of each other (inter-pair skew). Serpentine meanders on the shorter trace add the required path length. This module generates meanders, validates the result, and checks group-delay match for multi-net length groups.

## How to use it

### From chat

> "Match the DDR4 DQ[0] differential pair: P trace is 48.3 mm, N trace is 46.7 mm, target skew < 5 ps. Use 0.1 mm amplitude serpentines."

### From Python

```python
from kerf_electronics.routing.push_shove import tune_diff_pair_skew
from kerf_electronics.tools.diffpair import check_length_match

tuned = tune_diff_pair_skew(
    diff_pair_segs=dp_segs,
    target_length_diff_mm=0.0   # aim for zero skew
)
print(f"Achieved skew: {tuned['achieved_skew_mm']:.4f} mm")

match = check_length_match(
    circuit_json, group_name="DDR4_DQ",
    target_length_mm=50.0, max_skew_mm=0.5
)
for net in match["nets"]:
    print(f"{net['name']}: {net['length_mm']:.2f} mm, delta: {net['delta_mm']:+.2f} mm")
```

### From an LLM tool spec

```json
{"diff_pair_net_pos": "DDR4_DQS0_P",
 "diff_pair_net_neg": "DDR4_DQS0_N",
 "target_skew_ps": 5,
 "serpentine_amplitude_mm": 0.1}
```

## How it works

`tune_diff_pair_skew` measures the lengths of the positive and negative traces from their route point lists. The shorter trace has its last straight segment replaced by a U-shaped serpentine of specified amplitude: two 90° turns spaced by `amplitude` add `2 × amplitude + gap` extra length per meander. The algorithm adds meanders until the length difference is within tolerance. `check_length_match` sums all `pcb_trace` segment lengths for each net in the group and reports the delta to the target length in mm and the equivalent propagation-delay skew in ps (using the board's effective permittivity).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `tune_diff_pair_skew(diff_pair_segs, target_length_diff_mm)` | `dict` | Serpentine meander generation |
| `add_diff_pair(circuit_json, net_pos, net_neg, spacing_mm)` | `dict` | Define diff pair |
| `check_length_match(circuit_json, group_name, target_length_mm, max_skew_mm)` | `dict` | Group length + skew report |
| `calc_impedance(type, W, H, T, er, S)` | `dict` | Z0, Zdiff, propagation delay |

## Example

```python
from kerf_electronics.tools.diffpair import calc_impedance

z = calc_impedance("microstrip_diff", W=0.15e-3, H=0.1e-3, T=0.035e-3,
                    er=4.3, S=0.15e-3)
print(f"Zdiff = {z['zdiff_ohm']:.1f} Ω, Td = {z['td_ps_mm']:.2f} ps/mm")
```

## Honest caveats

Serpentine placement is at the end of the trace only; inter-obstacle placement (serpentines between vias) is not yet supported. The skew model assumes uniform dielectric; microstrip traces over voids or cavities have local permittivity variation not captured here. The impedance calculator uses closed-form approximations (IPC-2141A, Wadell); field-solver accuracy requires a 2D EM solver.

## References

- Wadell, B.C. (1991). *Transmission Line Design Handbook*. Artech House. §3.7, §4.3.
- JEDEC JESD79-4 (2012). *DDR4 SDRAM Standard*. Appendix B (routing guidelines).
