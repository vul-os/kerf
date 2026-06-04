# PCB Autorouting and Push-Shove

*Domain: Electronics · Module: `packages/kerf-electronics/src/kerf_electronics/routes_autoroute.py` · Shipped: Wave 9*

## Overview

PCB autorouting via FreeRouting (external JVM-based router) with a push-shove pre-pass for congestion relief. Takes a CircuitJSON netlist, places components (or uses existing placements), runs FreeRouting with configurable design rules (clearance, via drill, copper weight), and returns a fully-routed CircuitJSON with trace geometry, via placements, and DRC status. The push-shove pre-pass implements the KiCad-compatible shove algorithm in Python for trace rip-up and re-route.

## When to use

- Automatically routing all nets on a new PCB design.
- Rerouting a specific net after a component change.
- Checking if a board is routable under given design rules before manual routing.

## API

```python
from kerf_electronics.routes_autoroute import (
    autoroute_board, AutorouteConfig,
)

config = AutorouteConfig(
    clearance_mm=0.15,
    trace_width_mm=0.2,
    via_drill_mm=0.3,
    via_annular_mm=0.5,
    max_passes=10,
)

result = autoroute_board(
    circuit_json=circuit,
    config=config,
)

print(result["completion_pct"])
print(result["unrouted_nets"])
```

## LLM tools

`pcb_autoroute`, `pcb_push_shove`

## References

- FreeRouting, Alfons Wirtz, open-source PCB router (github.com/freerouting/freerouting).
- Mikami-Tabuchi algorithm for maze routing (Mikami & Tabuchi, 1968).

## Honest caveats

Autorouting quality depends on component placement and board density. FreeRouting is a Java process and requires JVM 17+ to be available on the server. Differential pair routing and length-matching are not supported by the autorouter integration — route these manually. High-speed signals should have their routing reviewed by a signal integrity engineer regardless of DRC pass status.
