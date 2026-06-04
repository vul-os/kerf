# E-Textiles (Conductive Yarns and LED Layout)

*Domain: Textiles · Module: `packages/kerf-textiles/src/kerf_textiles/etextiles.py` · Shipped: Wave 10*

## Overview

Design tools for electronic textiles: resistive-yarn heater element sizing, conductive-thread routing with resistance and voltage-drop prediction, and addressable LED layout on fabric substrates. `heating_calc` computes power density and temperature rise for a given yarn resistivity, stitch density, and driving voltage. `led_layout` places WS2812-style addressable LEDs along a fabric path and generates a wiring diagram with branch currents.

## When to use

- Designing resistive heating patches for garments or medical wearables.
- Routing conductive-thread power and data lines across a fabric panel.
- Laying out addressable LED arrays on costumes or smart textiles.

## API

```python
from kerf_textiles.etextiles import (
    ResistiveYarn, HeaterSegment, heating_calc,
    ThreadRoute, thread_route,
    LEDNode, LEDBranch, LEDLayout, led_layout,
)

yarn = ResistiveYarn(name="shieldex_117", resistance_per_metre=30.0)
seg  = HeaterSegment(yarn=yarn, length_m=0.5, voltage_v=5.0)
heat = heating_calc(seg)
print(heat.power_w, heat.temp_rise_k)

layout = led_layout(
    path_points=[[0,0],[50,0],[100,0],[150,0]],
    n_leds=4,
    supply_v=5.0,
    wire_resistance_per_m=0.5,
)
print(layout.voltage_drop_end)
```

## LLM tools

`textiles_etextiles`

## References

- Stoppa & Chiolerio, "Wearable electronics and smart textiles", *Sensors* 14(7), 2014.
- Post et al., "E-broidery: Design and fabrication of textile-based computing", *IBM Syst. J.* 39(3-4), 2000.

## Honest caveats

Yarn resistance values are typical; actual values vary by twist, tension, and wash cycles. The heater model assumes uniform stitch density and ignores thermal conduction to adjacent layers. LED branch current calculations assume ideal wire resistances; contact resistance at stitched joints (typically 1–5 Ω) must be added by the user.
