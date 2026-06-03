"""
kerf_cad_core.visualscript — Visual scripting engine (Marionette / MatrixGold semantics).

Provides a DAG-based visual scripting backend analogous to:
  - Vectorworks Marionette (parametric node-based scripting for architectural design)
  - MatrixGold Visual Scripting (Vectorworks-style DAG for jewellery parametrics)
  - Dynamo BIM (Autodesk Revit node-based scripting)

The engine evaluates directed acyclic graphs of typed nodes, where each node
applies a transformation to its inputs to produce outputs that feed downstream
nodes.

Public API:

    from kerf_cad_core.visualscript import (
        MarionetteNode,
        MarionetteGraph,
        evaluate_marionette_graph,
        NODE_LIBRARY,
    )

References
----------
Vectorworks Marionette documentation (https://developer.vectorworks.net/marionette)
MatrixGold Visual Scripting guide (Gemvision 2022)
Aksamija, A. (2020). Parametric and Computational Design in Architectural Practice.
Woodbury, R. (2010). Elements of Parametric Design. Routledge.

Author: imranparuk
"""

from kerf_cad_core.visualscript.marionette import (
    MarionetteNode,
    MarionetteGraph,
    evaluate_marionette_graph,
    NODE_LIBRARY,
)

__all__ = [
    "MarionetteNode",
    "MarionetteGraph",
    "evaluate_marionette_graph",
    "NODE_LIBRARY",
]
