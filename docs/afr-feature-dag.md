# Automatic Feature Recognition and DAG

> Recognise machining features in an imported STEP body and build a parametric feature DAG — so imported parts can be edited like native Kerf models.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/afr/dag.py`
**Shipped**: Wave 9
**LLM tools**: `feature_afr_recognize`, `feature_afr_dag_build`, `feature_afr_to_feature_log`

---

## What it is

When engineers import a STEP file from CATIA, SolidWorks, or NX, the solid arrives as a "dumb" BRep — geometry with no parametric history. Automatic Feature Recognition (AFR) analyses the topological structure and local geometry of each face group to infer the original machining intent: pocket, boss, hole, slot, chamfer, fillet, groove.

The recognised features are assembled into a Directed Acyclic Graph (DAG) that encodes their construction dependency order — a pocket must precede the fillet on its edge, for example. The DAG is then serialised to a Kerf `.feature` log, enabling parametric re-editing of the depth, diameter, or position of any recognised feature.

## How to use it

### From chat (natural language)

> "Recognise the features in the imported housing STEP and show me the feature tree"

The LLM calls `feature_afr_recognize` then `feature_afr_dag_build`.

### From Python

```python
from kerf_cad_core.afr.dag import (
    AFRFeatureDAG, afr_to_dag,
    afr_dag_to_feature_log, emit_feature_log,
)

dag: AFRFeatureDAG = afr_to_dag(feature_topology)
print(f"Recognised {dag.node_count} features")

# Export to a parametric feature log
log = afr_dag_to_feature_log(dag, name="housing-v3")
emit_feature_log(log, path="housing-v3.feature")
```

### From an LLM tool spec

```json
{"tool": "feature_afr_dag_build", "body_id": "housing_step",
 "output_format": "feature_log"}
```

## How it works

AFR proceeds in three passes. First, face adjacency is computed — each face is connected to its neighbours via shared edges. Second, local topology patterns are matched against templates for known feature types (e.g. a cylindrical face surrounded by planar faces = blind hole; concave planar face with rectangular loop = pocket). Third, the dependency graph is constructed by identifying which features share faces with other features and applying a topological ordering (Kahn's algorithm) to produce a valid build sequence.

The `_feature_key_sets` function computes a canonical signature for each face cluster for DAG node construction.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `afr_to_dag(feature_topology)` | `AFRFeatureDAG` | Build DAG from recognised features |
| `afr_dag_to_feature_log(dag, name)` | `dict` | Serialise to feature log |
| `emit_feature_log(log, path)` | `None` | Write to disk |

`AFRFeatureDAG` attributes: `nodes`, `edges`, `node_count`, `topological_order()`.

## Example

```python
dag = afr_to_dag(recognised_topology)
for node in dag.topological_order():
    print(f"  {node.feature_type}: {node.params}")
```
Output: `pocket: depth=12mm`, `hole: dia=8mm`, `fillet: r=2mm`

## Honest caveats

AFR is heuristic-based and works best on prismatic machined parts. Organic and freeform surfaces are classified as `unknown`. Concave features nested within other features (pocket-in-pocket) may have incorrect dependency order. The emitted feature log is best-effort reconstruction, not a round-trip of the original parametric intent. Complex multi-body assemblies should be split into individual bodies first.

## References

- Sunil & Pande (2008). "Automatic recognition of features from freeform surface CAD models." *CAD* 40(5).
- Woo (2003). "Fast cell-based decomposition and its applications to solid modelling." *CAD* 35(11).
