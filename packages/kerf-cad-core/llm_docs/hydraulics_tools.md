# hydraulics_tools

*Module: `kerf_cad_core.civil.hydraulics_tools` · Domain: cad*

This module registers **2** LLM tool(s):

- [`hydraulics_pipe_network`](#hydraulics-pipe-network)
- [`hydraulics_manning`](#hydraulics-manning)

---

## `hydraulics_pipe_network`

Solve a steady-state pressurised pipe network using the Hardy-Cross iterative loop-correction method.

Nodes represent junctions / reservoirs.  Pipes connect nodes and carry flow from high head to low head.

Head-loss formulae available:
  'hazen-williams'  — hf = 10.67·L·Q^1.852 / (C^1.852·D^4.87)  (empirical)
  'darcy-weisbach'  — hf = f·(L/D)·V²/(2g); f by Colebrook-White iteration

At least one node must have 'head_fixed' set (reservoir / tank).

Output: {ok, converged, iterations, nodes, pipes, warnings}
  nodes[]: {node_id, elevation_m, head_m, pressure_head_m, pressure_kPa, demand_L_per_s, is_fixed_head}
  pipes[]: {pipe_id, start_node, end_node, flow_L_per_s, flow_m3_per_s, velocity_m_per_s, headloss_m, diameter_m, length_m}

Non-convergence is reported in 'warnings' (not raised); results are still returned as best-effort approximation.

Reference: Hardy-Cross (1936), Univ. Illinois Bull. 286; Hazen-Williams (1905); Colebrook-White (1939).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "nodes": {
      "type": "array",
      "description": "Network nodes as objects. Each node: {node_id: string, elevation: number [m], demand: number [L/s, default 0; positive=withdrawal, negative=supply], head_fixed: number [m, optional \u2014 reservoir/tank; omit for junction nodes]}. At least one node must have head_fixed.",
      "items": {
        "type": "object",
        "properties": {
          "node_id": {
            "type": "string"
          },
          "elevation": {
            "type": "number"
          },
          "demand": {
            "type": "number"
          },
          "head_fixed": {
            "type": "number"
          }
        },
        "required": [
          "node_id"
        ]
      }
    },
    "pipes": {
      "type": "array",
      "description": "Pipe segments as objects. Each pipe: {pipe_id: string, start_node: string, end_node: string, length: number [m], diameter: number [m], roughness: number [mm, default 0.1], hw_c: number [Hazen-Williams C, default 120]}.",
      "items": {
        "type": "object",
        "properties": {
          "pipe_id": {
            "type": "string"
          },
          "start_node": {
            "type": "string"
          },
          "end_node": {
            "type": "string"
          },
          "length": {
            "type": "number"
          },
          "diameter": {
            "type": "number"
          },
          "roughness": {
            "type": "number"
          },
          "hw_c": {
            "type": "number"
          }
        },
        "required": [
          "pipe_id",
          "start_node",
          "end_node",
          "length",
          "diameter"
        ]
      }
    },
    "head_loss_method": {
      "type": "string",
      "description": "Head-loss formula: 'hazen-williams' (default) or 'darcy-weisbach'. Use Hazen-Williams for water-supply networks; Darcy-Weisbach for general pressurised fluids."
    },
    "max_iterations": {
      "type": "integer",
      "description": "Hardy-Cross iteration cap (default 100)."
    },
    "tolerance_m": {
      "type": "number",
      "description": "Convergence criterion: max |loop \u0394Q| < tolerance_m (default 1e-4 m). Tighten for higher precision; loosen for speed."
    }
  },
  "required": [
    "nodes",
    "pipes"
  ]
}
```

---

## `hydraulics_manning`

Compute normal depth and hydraulic properties for a rectangular open channel or gravity sewer using Manning's equation.

Manning's equation (SI):  Q = (1/n) · A · R^(2/3) · S^(1/2)
  A = width × depth  (m²)
  R = A / (width + 2·depth)  (hydraulic radius, m)
  S = longitudinal slope (m/m)
  n = Manning's roughness coefficient

Normal depth is solved by bisection.

Output: {ok, normal_depth_m, velocity_m_per_s, flow_area_m2, wetted_perimeter_m, hydraulic_radius_m, froude_number, flow_regime, channel_full}.

flow_regime: 'subcritical' (Fr < 1), 'critical' (Fr ≈ 1), 'supercritical' (Fr > 1), or 'channel_full' (flow exceeds capacity).

Typical Manning's n values: 0.010 smooth PVC, 0.013 concrete, 0.015 brick sewer, 0.025 earth canal, 0.035 vegetated channel.

Reference: Manning (1891); Chow (1959) 'Open-Channel Hydraulics'.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "flow_m3s": {
      "type": "number",
      "description": "Design flow rate (m\u00b3/s), > 0."
    },
    "width_m": {
      "type": "number",
      "description": "Channel bottom width (m), > 0."
    },
    "slope": {
      "type": "number",
      "description": "Longitudinal slope (m/m), > 0. E.g. 0.001 for a 1 in 1000 grade."
    },
    "manning_n": {
      "type": "number",
      "description": "Manning's roughness coefficient (dimensionless), > 0. Typical: 0.010 PVC, 0.013 concrete, 0.025 earth."
    },
    "max_depth_m": {
      "type": "number",
      "description": "Upper depth bound for bisection search (m, default 10.0). If the normal depth exceeds this, channel_full=true is reported."
    }
  },
  "required": [
    "flow_m3s",
    "width_m",
    "slope",
    "manning_n"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
