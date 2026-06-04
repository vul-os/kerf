# E-Textiles (Conductive Yarns and LED Layout)

> Size resistive heater patches, route conductive-thread circuits, and lay out addressable LEDs on fabric.

**Module**: `packages/kerf-textiles/src/kerf_textiles/etextiles.py`
**Shipped**: Wave 10
**LLM tools**: `textiles_etextiles`

---

## What it is

Design tools for electronic textiles: resistive-yarn heater element sizing (power density and temperature rise), conductive-thread routing with resistance and voltage-drop prediction, and WS2812-style addressable LED layout on fabric substrates with branch current analysis.

## How to use it

### From chat

> "Size a resistive heating patch using Shieldex 117 yarn at 5V, 0.5 m stitch length."

### From Python

```python
from kerf_textiles.etextiles import (
    ResistiveYarn, HeaterSegment, heating_calc,
    LEDNode, LEDBranch, LEDLayout, led_layout,
)

yarn = ResistiveYarn(name="shieldex_117", resistance_per_metre=30.0)
seg  = HeaterSegment(yarn=yarn, length_m=0.5, voltage_v=5.0)
heat = heating_calc(seg)
print(heat.power_w, heat.temp_rise_k)

layout = led_layout(
    path_points=[[0,0],[50,0],[100,0],[150,0]],
    n_leds=4, supply_v=5.0, wire_resistance_per_m=0.5,
)
print(layout.voltage_drop_end)
```

### From an LLM tool spec

```json
{"tool": "textiles_etextiles", "input": {"yarn_resistance_per_m": 30, "length_m": 0.5, "voltage_v": 5.0, "mode": "heater"}}
```

## How it works

`heating_calc` computes heater power as `P = V² / R_total` where `R_total = resistance_per_metre × length_m`. Temperature rise is estimated from power density and thermal resistance of the fabric layer (10–20 K/W/m² empirical). `led_layout` distributes LED nodes at equal spacings along the path and computes the daisy-chain voltage at each node using `V_n = V_supply − Σ I × R_wire`, where `I` is the total LED current drawn downstream of node `n`.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `heating_calc(segment)` | `HeaterResult` | Power, temperature rise |
| `thread_route(route)` | `ThreadResult` | Resistance and voltage drop along route |
| `led_layout(path_points, n_leds, supply_v, wire_resistance_per_m)` | `LEDLayout` | LED placement and voltage profile |

## Example

```python
heat = heating_calc(HeaterSegment(yarn, length_m=0.5, voltage_v=5.0))
# HeaterResult(power_w=0.83, temp_rise_k=12.5, resistance_ohm=30.0)
```

## Honest caveats

Yarn resistance values are typical mid-range; actual values vary by twist, tension, wash cycles, and contact resistance at stitched joints (typically 1–5 Ω). The heater model assumes uniform stitch density and ignores thermal conduction to adjacent garment layers. LED current calculations assume constant current draw per LED regardless of supply voltage variation.

## References

- Stoppa & Chiolerio, "Wearable electronics and smart textiles," *Sensors* 14(7), 2014.
- Post et al., "E-broidery: Design and fabrication of textile-based computing," *IBM Syst. J.* 39(3-4), 2000.
