# kerf-microfluidics — Microfluidics and MEMS design

`kerf-microfluidics` provides analytical tools for the design and analysis of
microfluidic chips and MEMS (Micro-Electro-Mechanical Systems) devices.  All
solvers are pure-Python — no heavy numerical dependencies.

---

## Plugin registration

```python
async def register(app, ctx):
    app.include_router(router)          # GET /microfluidics/health
    ctx.tools.register("microfluidics_channel",  ...)
    ctx.tools.register("microfluidics_network",  ...)
    ctx.tools.register("microfluidics_mems",     ...)
    ctx.tools.register("microfluidics_mixer",    ...)
    return PluginManifest(
        name="microfluidics",
        provides=["microfluidics.channels", "microfluidics.networks",
                  "microfluidics.mixers", "microfluidics.mems"],
        depends=["cad-core"],
    )
```

---

## Module: `channels.py`

Hydraulic resistance and pressure-flow relations for single microchannels.

### `rect_channel_resistance(mu, L, w, h) → float`

Hydraulic resistance of a rectangular microchannel (h ≤ w).

Formula (Bruus 2008, eq. 2.27):

```
R = 12 μ L / (w h³ (1 − 0.63 h/w))
```

All SI units: `mu` [Pa·s], `L` [m], `w` [m], `h` [m]. Returns R [Pa·s/m³].

```python
from kerf_microfluidics.channels import rect_channel_resistance
R = rect_channel_resistance(mu=1e-3, L=1e-3, w=100e-6, h=50e-6)
# R ≈ 1.40e+12 Pa·s/m³
```

### `circ_channel_resistance(mu, L, r) → float`

Hagen-Poiseuille resistance of a circular channel:

```
R = 8 μ L / (π r⁴)
```

### `pressure_drop(Q, R) → float`

```
ΔP = Q · R
```

### `flow_rate(delta_p, R) → float`

```
Q = ΔP / R
```

---

## Module: `networks.py`

Kirchhoff-law solver for microfluidic resistor networks.  Channels act as
hydraulic resistors; pressures are solved at every node via a conductance
(Laplacian) matrix system using pure-Python Gaussian elimination.

### `MicrofluidicNetwork`

```python
from kerf_microfluidics.networks import MicrofluidicNetwork

net = MicrofluidicNetwork()
net.add_node("inlet")
net.add_node("outlet")
net.add_node("junction")
net.add_channel("inlet",    "junction", resistance=1e12)
net.add_channel("junction", "outlet",   resistance=2e12)
net.set_pressure("inlet",  1000.0)   # Pa
net.set_pressure("outlet", 0.0)

result = net.solve()
# result["pressures"] → {"inlet": 1000.0, "junction": 333.3, "outlet": 0.0}
# result["flows"]     → {("inlet","junction","..."): Q, ...}   [m³/s]
```

### `equivalent_resistance(channels, source_node, sink_node) → float`

Convenience function: builds and solves a network, returns the two-terminal
equivalent resistance.

```python
from kerf_microfluidics.networks import equivalent_resistance

# Two parallel channels of equal resistance R
R_eq = equivalent_resistance(
    [{"node_a": "in", "node_b": "out", "resistance": 1e12},
     {"node_a": "in", "node_b": "out", "resistance": 1e12}],
    "in", "out",
)
# R_eq == 5e11  (R/2)
```

---

## Module: `mems_cantilever.py`

Euler-Bernoulli analysis of rectangular MEMS cantilever beams.

### `cantilever_stiffness(E, t, w, L) → float`

End-loaded bending stiffness:

```
k = E t³ w / (4 L³)
```

Parameters: `E` [Pa], `t` [m] (thickness, bending direction), `w` [m], `L` [m].
Returns k [N/m].

### `cantilever_resonance(E, rho, t, w, L) → float`

Fundamental flexural resonance frequency — exact Euler-Bernoulli result:

```
f₁ = (β₁L)² / (2π L²) · √(EI / ρA)
```

where β₁L ≈ 1.8751040631 is the first root of cos(βL)cosh(βL) = −1,
I = wt³/12, and A = wt.

```python
from kerf_microfluidics.mems_cantilever import cantilever_resonance

# Silicon MEMS cantilever: 100 µm × 10 µm × 1 µm
f1 = cantilever_resonance(
    E=170e9, rho=2330.0,
    t=1e-6, w=10e-6, L=100e-6,
)
# f1 ≈ 137.98 kHz
```

### `cantilever_resonance_lumped(E, rho, t, w, L) → float`

Lumped-mass approximation:

```
f = 1/(2π) · √(k / m_eff)
```

where `m_eff = 0.2427 · ρ · w · t · L` (mode-shape integral).
Matches `cantilever_resonance` to < 0.1%.

---

## Module: `mixers.py`

Passive mixer geometry generators.  Return dicts of waypoints / metadata
suitable for export to a CAD kernel or direct visualisation.

### `serpentine_geometry(n_turns, channel_width, straight_length, ...) → dict`

Generates the centreline waypoints of an S-channel serpentine mixer.

Returns:

```
{
  "waypoints":    [(x, y), ...],   # centreline path in metres
  "channel_width": float,
  "total_length":  float,          # approximate arc length [m]
  "n_turns":       int,
}
```

### `herringbone_geometry(channel_length, channel_width, groove_depth, ...) → dict`

Staggered herringbone groove (SHG) mixer geometry (Stroock et al., 2002).

Returns:

```
{
  "centreline":     [(x_start, y), (x_end, y)],
  "grooves": [
    {
      "x":         float,   # axial position of groove apex [m]
      "angle_deg": float,   # V-arm half-angle [degrees]
      "offset_y":  float,   # lateral offset of apex from centreline [m]
      "depth":     float,   # groove depth [m]
      "width":     float,   # groove ridge width [m]
    },
    ...
  ],
  "channel_width":  float,
  "channel_length": float,
}
```

---

## LLM tools

| Tool | Description |
|---|---|
| `microfluidics_channel` | Resistance + ΔP/Q for a single rectangular or circular channel |
| `microfluidics_network` | Kirchhoff network solver: nodal pressures + flow rates |
| `microfluidics_mems` | MEMS cantilever stiffness and resonance frequency |
| `microfluidics_mixer` | Serpentine or herringbone mixer geometry |

---

## Physical references

| Formula | Reference |
|---|---|
| Rectangular channel resistance | Bruus (2008) *Theoretical Microfluidics*, eq. 2.27 |
| Hagen-Poiseuille (circular) | Bruus (2008) eq. 2.10 |
| Cantilever stiffness | Senturia (2001) *Microsystem Design*, ch. 9 |
| Cantilever resonance (Euler-Bernoulli) | Blevins (1979) *Natural Frequency and Mode Shape*, Table 8-1 |
| Herringbone groove mixer | Stroock et al. (2002) *Science* 295:647–651 |

---

## Limitations

- Channel models assume fully-developed laminar (Stokes) flow; valid for Re ≪ 1.
- Rectangular channel formula is accurate for h ≤ w; the relative error is
  < 0.5% for h/w ≤ 1.
- Network solver assumes incompressible Newtonian fluid (linear Q–ΔP relation).
- Cantilever model is 1-D Euler-Bernoulli; valid for L/t > 10.  Large
  deflections, damping, and electrostatic actuation are not modelled.
- Mixer geometry generators produce centreline/groove positions only; detailed
  3-D solid bodies require integration with `kerf-cad-core`.
