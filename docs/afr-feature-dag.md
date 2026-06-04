# Automatic Feature Recognition and DAG

*Domain: Geometry kernel · Module: `packages/kerf-cad-core/src/kerf_cad_core/afr/dag.py` · Shipped: Wave 9*

## Overview

Recognises machining features (pockets, holes, bosses, slots, chamfers, fillets) in an imported BRep and builds a directed acyclic graph (DAG) of their construction order. The DAG is then emitted as a Kerf `.feature` file, enabling parametric editing of imported STEP parts. This closes the import-and-edit loop for parts from CATIA, SolidWorks, and Siemens NX.

## When to use

- Importing a STEP file and wanting to modify a feature without rebuilding from scratch.
- Generating a parametric history tree from an unparameterised solid.
- Inspecting the parent-child dependency order of machined features.

## API

```python
from kerf_cad_core.afr.dag import (
    AFRFeatureDAG,
    afr_to_dag,
    afr_dag_to_feature_log,
    emit_feature_log,
)

# Build a DAG from a recognised-feature topology dict
dag: AFRFeatureDAG = afr_to_dag(feature_topology)

# Export to a Kerf feature log (can be loaded back as parametric)
feature_log = afr_dag_to_feature_log(dag, name="imported-part")
emit_feature_log(feature_log, path="output.feature")
```

## LLM tools

`feature_afr_recognize`, `feature_afr_dag_build`, `feature_afr_to_feature_log`

## References

- Sunil & Pande, "Automatic recognition of features from freeform surface CAD models", *CAD* 40(5), 2008.
- Woo, "Fast cell-based decomposition and its applications to solid modelling", *CAD* 35(11), 2003.

## Honest caveats

Feature recognition is heuristic-based and works best on prismatic machined parts. Organic/freeform surfaces are classified as `unknown` features. Concave features nested inside other features (e.g. a pocket within a pocket) may not have their dependency order inferred correctly. The emitted feature log is a best-effort reconstruction, not a round-trip of the original parametric intent.
