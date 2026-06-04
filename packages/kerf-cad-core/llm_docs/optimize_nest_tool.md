# manufacturing_optimize_nest

*Module: `kerf_cad_core.nesting.optimize_nest_tool` · Domain: cad*

## Description

NFP + Genetic-Algorithm nesting optimizer for sheet metal / CNC work. Given a sheet (width × height) and a list of arbitrary-polygon parts with quantities, packs as many parts as possible into the sheet using: (1) No-Fit Polygon (NFP) true-shape feasibility (Minkowski-sum, Sergyán 2009); (2) bottom-left-fill heuristic (Burke 2006); (3) Genetic Algorithm over placement sequence + rotation (Kovacs 2002), 50 generations, population 40 by default. 
HONEST FLAGS:   - GA is stochastic; pass seed for reproducibility.   - Curved edges (arcs, splines) must be pre-approximated as polylines.   - Concave NFPs use convex-hull over-approximation (no false overlaps).   - runtime_budget_ms can cap execution for large inputs. 
Returns: {ok, placements:[{name,rotation,x,y,vertices}], utilization, utilization_pct, placed_count, total_count, runtime_ms, generations_run, seed, errors:[]}.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "sheet": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "minItems": 2,
      "maxItems": 2,
      "description": "Sheet [width, height] in mm."
    },
    "parts": {
      "type": "array",
      "description": "Parts to nest. Each: {name (str), vertices ([[x,y],...] >= 3 pts), qty (int, default 1)}. Curved edges must be pre-approximated as polylines.",
      "items": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "vertices": {
            "type": "array",
            "items": {
              "type": "array",
              "items": {
                "type": "number"
              },
              "minItems": 2,
              "maxItems": 2
            },
            "minItems": 3
          },
          "qty": {
            "type": "integer",
            "minimum": 1
          }
        },
        "required": [
          "name",
          "vertices"
        ]
      }
    },
    "options": {
      "type": "object",
      "description": "GA/placement parameters: generations (int, default 50), population_size (int, default 40), rotation_step (degrees: 4\u2192{0,90,180,270}, 12\u2192{0,30,...,330}), grid_step (float mm, default 5.0), seed (int \u2014 reproducibility; HONEST: stochastic), runtime_budget_ms (float, 0=no limit), crossover_rate (float, default 0.85), mutation_rate (float, default 0.15).",
      "properties": {
        "generations": {
          "type": "integer",
          "minimum": 1
        },
        "population_size": {
          "type": "integer",
          "minimum": 2
        },
        "rotation_step": {
          "type": "integer",
          "minimum": 1
        },
        "grid_step": {
          "type": "number",
          "minimum": 0.1
        },
        "seed": {
          "type": "integer"
        },
        "runtime_budget_ms": {
          "type": "number",
          "minimum": 0
        },
        "crossover_rate": {
          "type": "number"
        },
        "mutation_rate": {
          "type": "number"
        }
      }
    }
  },
  "required": [
    "sheet",
    "parts"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="manufacturing_optimize_nest",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
