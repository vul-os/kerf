"""kerf_cad_core.geom.history — parametric history / feature DAG (GK-58..GK-72).

This subpackage layers a **feature DAG** on top of the existing Body-emitting
geometry verbs (``brep_build.box_to_body``, ``cylinder_to_body``,
``sphere_to_body``, ``boolean.body_union/difference/intersection``,
``chamfer.chamfer_edge``, ``fillet_solid.fillet_solid_edge``) WITHOUT modifying
those modules. It is the architectural keystone that makes the kernel
*parametric* rather than a one-shot script:

  * **Feature** — an immutable record of an op with named scalar params and
    named upstream refs.
  * **PersistentSelector** — a face/edge reference whose identity survives
    regeneration of the producing feature because it is resolved through a
    *role* tag (e.g. ``face:+Y`` on a box) rather than a raw object pointer.
  * **FeatureDAG** — owns the topology of features, performs topological-sort
    evaluation, caches per-feature outputs, invalidates only the
    downstream-of-changed subtree on edits, and dispatches each feature to a
    registered evaluator.
  * **Evaluators** — small adapters that translate a Feature's
    ``inputs/params`` into a call to one of the existing Body-emitting verbs
    and produce a ``NamingTable`` mapping role-strings to live Face/Edge
    objects in the produced ``Body``.

Public API:
"""

from __future__ import annotations

from kerf_cad_core.geom.history.feature import (
    Feature,
    FeatureRef,
    MissingReferenceError,
    PersistentSelector,
)
from kerf_cad_core.geom.history.persistent_naming import (
    NamingTable,
    PersistentId,
    entity_fingerprint,
    make_persistent_id,
)
from kerf_cad_core.geom.history.dag import (
    DAGCycleError,
    EvaluationCache,
    FeatureDAG,
)
from kerf_cad_core.geom.history.evaluators import (
    BooleanFeature,
    BoxFeature,
    ChamferEdgeFeature,
    CylinderFeature,
    FilletEdgeFeature,
    SphereFeature,
    register_default_evaluators,
)

__all__ = [
    # feature
    "Feature",
    "FeatureRef",
    "PersistentSelector",
    "MissingReferenceError",
    # naming
    "NamingTable",
    "PersistentId",
    "entity_fingerprint",
    "make_persistent_id",
    # DAG
    "FeatureDAG",
    "EvaluationCache",
    "DAGCycleError",
    # evaluators
    "BoxFeature",
    "CylinderFeature",
    "SphereFeature",
    "BooleanFeature",
    "ChamferEdgeFeature",
    "FilletEdgeFeature",
    "register_default_evaluators",
]
