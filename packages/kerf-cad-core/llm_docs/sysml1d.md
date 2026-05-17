# SysML 1-D Network Simulation (`sysml1d`)

Acausal lumped-parameter network simulator for electrical, thermal,
hydraulic, and mechanical domains via the effort/flow analogy; uses
generalised Modified Nodal Analysis (MNA) with implicit trapezoidal
(Crank–Nicolson) integration and Newton–Raphson for nonlinear elements.

---

## When to use

Reach for this tool when the user asks about:

- DC operating point or transient response of an electrical circuit (R, L, C, diode, voltage/current sources)
- thermal lumped-network simulation (thermal resistance / capacitance, heat sources)
- hydraulic pipe-network transient (resistance, accumulator compliance, inertance)
- mechanical spring-mass-damper 1-D dynamics via bond-graph analogy
- cross-domain models where the same MNA engine covers multiple physics

---

## Tool

### `sysml1d_simulate`

Assemble and simulate a lumped-parameter network.

**Required:** `elements` (array of element descriptor objects)
**Optional:** `t_end` (s), `dt` (s), `t_start` (default 0), `initial_conditions` (dict), `mode` (`"transient"` | `"dc"`)

**Element descriptor format:**

```json
{"type": "R",       "name": "R1",    "n_plus": "n1", "n_minus": "GND", "resistance": 1000.0}
{"type": "C",       "name": "C1",    "n_plus": "n2", "n_minus": "GND", "capacitance": 1e-6}
{"type": "L",       "name": "L1",    "n_plus": "n3", "n_minus": "n4",  "inductance": 1e-3}
{"type": "VSource", "name": "V1",    "n_plus": "n1", "n_minus": "GND", "voltage": 10.0}
{"type": "ISource", "name": "I1",    "n_plus": "n1", "n_minus": "GND", "current": 0.001}
{"type": "Diode",   "name": "D1",    "n_plus": "n1", "n_minus": "n2",  "Is": 1e-14, "Vt": 0.02585}
```

Ground node: `"GND"`, `"0"`, or `"ground"` (case-insensitive).

**Transient mode** (`mode: "transient"`, default) — requires `t_end` and `dt`:

```json
{
  "ok": true,
  "t": [0.0, 1e-6, ...],
  "nodes": {"n1": [10.0, 9.9, ...], "n2": [...]},
  "branches": {"V1": [0.01, ...], "L1": [...]}
}
```

**DC mode** (`mode: "dc"`) — returns steady-state operating point:

```json
{
  "ok": true,
  "nodes":    {"n1": 10.0, "n2": 3.3},
  "branches": {"V1": -0.01}
}
```

**Errors:** `{ok: false, reason}` — never raises.

---

## Domain analogy table

| Domain | Effort (e) | Flow (f) | R | C | L |
|--------|-----------|----------|---|---|---|
| Electrical | voltage (V) | current (A) | resistance (Ω) | capacitance (F) | inductance (H) |
| Thermal | temperature (K) | heat-flow (W) | R_th (K/W) | C_th (J/K) | — |
| Hydraulic | pressure (Pa) | volumetric flow (m³/s) | R_hyd | C_hyd (m³/Pa) | L_hyd (kg/m⁴) |
| Mechanical | force (N) | velocity (m/s) | damper (N·s/m) | mass (kg) | 1/k (m/N) |

---

## Programmatic API

```python
from kerf_cad_core.sysml1d.network import (
    Network, R, C, L, VSource, ISource, Diode,
    steady_state, simulate,
    make_thermal_r, make_thermal_c, make_thermal_source,
    make_hydraulic_r, make_hydraulic_c, make_hydraulic_l,
    make_mech_r, make_mech_m, make_mech_k,
)

# RC low-pass filter transient
net = Network()
net.add(VSource("V1", "in", "GND", voltage=5.0))
net.add(R("R1", "in", "out", 1000.0))
net.add(C("C1", "out", "GND", 1e-6))

dc = steady_state(net)
# dc["nodes"]["out"] ≈ 5.0 (RC at DC)

result = simulate(net, t_end=5e-3, dt=1e-6)
# result["nodes"]["out"] → exponential charge-up to 5 V
```

---

## Usage examples

**Simple voltage divider (DC):**

```
sysml1d_simulate
  elements: [
    {type:"VSource", name:"V1", n_plus:"n1", n_minus:"GND", voltage:12.0},
    {type:"R",       name:"R1", n_plus:"n1", n_minus:"n2",  resistance:10000.0},
    {type:"R",       name:"R2", n_plus:"n2", n_minus:"GND", resistance:10000.0}
  ]
  mode: "dc"
→ {nodes: {n1:12.0, n2:6.0}}
```

**Thermal RC: wall heating (transient):**

```
sysml1d_simulate
  elements: [
    {type:"ISource", name:"Q1", n_plus:"T_wall", n_minus:"GND", current:100.0},
    {type:"R",       name:"Rth", n_plus:"T_wall", n_minus:"GND", resistance:0.1},
    {type:"C",       name:"Cth", n_plus:"T_wall", n_minus:"GND", capacitance:5000.0}
  ]
  t_end: 3600  dt: 10  mode: "transient"
→ {nodes: {T_wall: [...]}}    # temperature rises exponentially to Q·Rth = 10 K
```

---

## Notes

- MNA size: N_nodes + N_vsources + N_inductors unknowns.  Pure Python — no numpy.
- Diode uses Newton–Raphson linearisation per step (clamped at exp_arg ≤ 300).
- `VSource` branch current sign: MNA internal sign is negated at output so
  callers see "current out of n_plus" convention.
- Capacitor IC: set via `initial_conditions: {"C1_v": 5.0}`.

---

## References

Ho, C.W., Ruehli, A.E., Brennan, P.A. — "The modified nodal approach to network analysis", IEEE Trans. Circuits Syst., 1975.
Pillage, L.T., Rohrer, R.A., Visweswariah, C. — *Electronic Circuit and System Simulation Methods*, McGraw-Hill, 1995 (trapezoidal companion models, §4.3).
