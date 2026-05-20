"""feature_io.py — append-only ``.feature`` log  ↔  in-proc FeatureDAG bridge.

GK-61: reads an existing append-only ``.feature`` JSON log into the in-process
feature DAG and regenerates the Body from it.

Format
------
An append-only ``.feature`` log is a JSON document:

    {
      "version": 1,
      "features": [
        { "id": "box-1", "op": "box",  "corner": [0,0,0], "dx": 10, "dy": 10, "dz": 5 },
        { "id": "bool-1", "op": "boolean", "kind": "union",
          "target_a_id": "box-1", "target_b_id": "cyl-1" },
        ...
      ]
    }

Supported ``op`` values
-----------------------
The ops below map to the built-in evaluators registered by
:func:`~kerf_cad_core.geom.history.evaluators.register_default_evaluators`:

===================  ================================  ==================================
``op``               Flat log fields                   Maps to DAG Feature kind
===================  ================================  ==================================
``box``              corner, dx, dy, dz, [tol]         ``"box"``
``cylinder``         axis_pt, axis_dir, radius,        ``"cylinder"``
                     height, [tol]
``sphere``           centre, radius, [tol]             ``"sphere"``
``boolean``          kind (union/difference/inter-     ``"boolean"``
                     section), target_a_id,
                     target_b_id, [tol]
``chamfer_edge``     target_id, edge_role, width,      ``"chamfer_edge"``
                     [tol]
``fillet_edge``      target_id, edge_role, radius,     ``"fillet_edge"``
                     [tol]
===================  ================================  ==================================

Unrecognised ``op`` values are *skipped* (logged with a warning) so that a
``.feature`` log containing cloud-worker ops (``sweep1``, ``network_srf``,
etc.) can still be partially loaded without raising.

Public API
----------
The only public names from this module that callers should depend on:

    load_feature_log(source)      -> FeatureDAG  (pre-populated, not evaluated)
    body_from_feature_log(source) -> Body         (fully evaluated)
    FeatureLogError               (exception)
    SUPPORTED_OPS                 (frozenset of op strings)

These four names are intentionally stable.  Everything else is private.

``source`` may be:

  * a ``str`` or ``bytes``  — the raw JSON text of the log
  * a ``dict``              — the already-parsed log document
  * a path-like object      — a file to open and parse
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, FrozenSet, List, Union

from kerf_cad_core.geom.brep import Body
from kerf_cad_core.geom.history.dag import FeatureDAG
from kerf_cad_core.geom.history.evaluators import register_default_evaluators
from kerf_cad_core.geom.history.feature import (
    Feature,
    FeatureRef,
    PersistentSelector,
)


# ---------------------------------------------------------------------------
# Supported ops — public sentinel
# ---------------------------------------------------------------------------

SUPPORTED_OPS: FrozenSet[str] = frozenset(
    ["box", "cylinder", "sphere", "boolean", "chamfer_edge", "fillet_edge"]
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FeatureLogError(ValueError):
    """Raised when a ``.feature`` log is malformed or cannot be loaded.

    Attributes
    ----------
    node_id : str | None
        The ``id`` of the offending feature node, if determinable.
    op : str | None
        The ``op`` field of the offending node, if present.
    """

    def __init__(
        self,
        message: str,
        *,
        node_id: "str | None" = None,
        op: "str | None" = None,
    ) -> None:
        self.node_id = node_id
        self.op = op
        detail = ""
        if node_id:
            detail += f" [node={node_id!r}]"
        if op:
            detail += f" [op={op!r}]"
        super().__init__(message + detail)


# ---------------------------------------------------------------------------
# Source normalisation
# ---------------------------------------------------------------------------

_Source = Union[str, bytes, dict, "os.PathLike[str]"]


def _parse_source(source: _Source) -> Dict[str, Any]:
    """Normalise the *source* argument into a parsed document dict.

    Detection priority:
      1. ``dict`` — returned as-is.
      2. ``bytes`` — decoded as UTF-8 then parsed as JSON.
      3. ``str`` — treated as raw JSON if it starts with ``{`` or ``[``
         (after stripping whitespace); otherwise treated as a file path.
      4. Any other path-like (``pathlib.Path``, etc.) — opened and parsed.
    """
    if isinstance(source, dict):
        return source
    if isinstance(source, bytes):
        try:
            return json.loads(source)
        except json.JSONDecodeError as exc:
            raise FeatureLogError(f"invalid JSON: {exc}") from exc
    if isinstance(source, str):
        stripped = source.lstrip()
        if stripped.startswith(("{", "[")):
            # Looks like JSON text.
            try:
                return json.loads(source)
            except json.JSONDecodeError as exc:
                raise FeatureLogError(f"invalid JSON: {exc}") from exc
        # Fall through: treat as a filesystem path string.
        path = source
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            raise FeatureLogError(f"cannot open file {path!r}: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FeatureLogError(f"invalid JSON in {path!r}: {exc}") from exc
    # Treat as a path-like (pathlib.Path or similar).
    path_str = os.fspath(source)  # type: ignore[arg-type]
    try:
        with open(path_str, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as exc:
        raise FeatureLogError(f"cannot open file {path_str!r}: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeatureLogError(f"invalid JSON in {path_str!r}: {exc}") from exc


# ---------------------------------------------------------------------------
# Per-op translators
# ---------------------------------------------------------------------------
#
# Each translator receives the *raw log node dict* and the *id→Feature map*
# accumulated so far.  It returns a Feature ready to be added to the DAG, or
# raises FeatureLogError.


def _require(node: Dict[str, Any], *keys: str) -> None:
    """Raise FeatureLogError if any of *keys* is absent from *node*."""
    nid = node.get("id")
    op = node.get("op")
    for k in keys:
        if k not in node:
            raise FeatureLogError(
                f"required field {k!r} missing", node_id=nid, op=op
            )


def _translate_box(node: Dict[str, Any]) -> Feature:
    _require(node, "corner", "dx", "dy", "dz")
    params: Dict[str, Any] = {
        "corner": tuple(float(v) for v in node["corner"]),
        "dx": float(node["dx"]),
        "dy": float(node["dy"]),
        "dz": float(node["dz"]),
        "tol": float(node.get("tol", 1e-7)),
    }
    return Feature(kind="box", params=params, id=node["id"])


def _translate_cylinder(node: Dict[str, Any]) -> Feature:
    _require(node, "axis_pt", "axis_dir", "radius", "height")
    params: Dict[str, Any] = {
        "axis_pt": tuple(float(v) for v in node["axis_pt"]),
        "axis_dir": tuple(float(v) for v in node["axis_dir"]),
        "radius": float(node["radius"]),
        "height": float(node["height"]),
        "tol": float(node.get("tol", 1e-7)),
    }
    return Feature(kind="cylinder", params=params, id=node["id"])


def _translate_sphere(node: Dict[str, Any]) -> Feature:
    _require(node, "centre", "radius")
    params: Dict[str, Any] = {
        "centre": tuple(float(v) for v in node["centre"]),
        "radius": float(node["radius"]),
        "tol": float(node.get("tol", 1e-7)),
    }
    return Feature(kind="sphere", params=params, id=node["id"])


def _translate_boolean(
    node: Dict[str, Any],
    seen_ids: Dict[str, Feature],
) -> Feature:
    _require(node, "kind", "target_a_id", "target_b_id")
    raw_kind = node["kind"]
    # Map from .feature log convention (cut/fuse/common + union/difference/intersection)
    _OP_MAP = {
        "union": "union",
        "fuse": "union",
        "difference": "difference",
        "cut": "difference",
        "intersection": "intersection",
        "common": "intersection",
    }
    op = _OP_MAP.get(raw_kind)
    if op is None:
        raise FeatureLogError(
            f"unknown boolean kind {raw_kind!r}; "
            f"expected one of {sorted(_OP_MAP)}",
            node_id=node.get("id"),
            op="boolean",
        )
    a_id = node["target_a_id"]
    b_id = node["target_b_id"]
    for ref_id, label in ((a_id, "target_a_id"), (b_id, "target_b_id")):
        if ref_id not in seen_ids:
            raise FeatureLogError(
                f"{label}={ref_id!r} references an unknown feature id "
                f"(not yet seen in the log)",
                node_id=node.get("id"),
                op="boolean",
            )
    inputs: Dict[str, Any] = {
        "a": FeatureRef(feature_id=a_id, output_name="body"),
        "b": FeatureRef(feature_id=b_id, output_name="body"),
    }
    params: Dict[str, Any] = {
        "op": op,
        "tol": float(node.get("tol", 1e-6)),
    }
    return Feature(kind="boolean", inputs=inputs, params=params, id=node["id"])


def _translate_chamfer_edge(
    node: Dict[str, Any],
    seen_ids: Dict[str, Feature],
) -> Feature:
    _require(node, "target_id", "edge_role", "width")
    target_id = node["target_id"]
    if target_id not in seen_ids:
        raise FeatureLogError(
            f"target_id={target_id!r} references an unknown feature id",
            node_id=node.get("id"),
            op="chamfer_edge",
        )
    inputs: Dict[str, Any] = {
        "body": FeatureRef(feature_id=target_id, output_name="body"),
        "edge": PersistentSelector(
            feature_id=target_id,
            entity_kind="edge",
            role=node["edge_role"],
        ),
    }
    params: Dict[str, Any] = {
        "width": float(node["width"]),
        "tol": float(node.get("tol", 1e-6)),
    }
    return Feature(
        kind="chamfer_edge", inputs=inputs, params=params, id=node["id"]
    )


def _translate_fillet_edge(
    node: Dict[str, Any],
    seen_ids: Dict[str, Feature],
) -> Feature:
    _require(node, "target_id", "edge_role", "radius")
    target_id = node["target_id"]
    if target_id not in seen_ids:
        raise FeatureLogError(
            f"target_id={target_id!r} references an unknown feature id",
            node_id=node.get("id"),
            op="fillet_edge",
        )
    inputs: Dict[str, Any] = {
        "body": FeatureRef(feature_id=target_id, output_name="body"),
        "edge": PersistentSelector(
            feature_id=target_id,
            entity_kind="edge",
            role=node["edge_role"],
        ),
    }
    params: Dict[str, Any] = {
        "radius": float(node["radius"]),
        "tol": float(node.get("tol", 1e-6)),
    }
    return Feature(
        kind="fillet_edge", inputs=inputs, params=params, id=node["id"]
    )


# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------


def load_feature_log(source: _Source) -> FeatureDAG:
    """Load an append-only ``.feature`` log into a fresh :class:`FeatureDAG`.

    Parameters
    ----------
    source:
        Raw JSON bytes/str, a pre-parsed dict, or a path-like to a
        ``.feature`` file.

    Returns
    -------
    FeatureDAG
        A fully wired DAG with the default evaluators registered.
        The DAG is **not evaluated** — call :meth:`FeatureDAG.regenerate`
        or :meth:`FeatureDAG.evaluate` yourself to produce Bodies.
        Use :func:`body_from_feature_log` for the common case of wanting
        the final Body immediately.

    Raises
    ------
    FeatureLogError
        If the log is malformed, a required field is missing, or a
        reference points at an unknown prior feature id.
    """
    doc = _parse_source(source)

    if not isinstance(doc, dict):
        raise FeatureLogError("top-level document must be a JSON object")

    features_raw: List[Any] = doc.get("features", [])
    if not isinstance(features_raw, list):
        raise FeatureLogError("'features' must be a JSON array")

    dag = FeatureDAG()
    register_default_evaluators(dag)

    # Maps feature id -> Feature for forward-reference checks.
    seen: Dict[str, Feature] = {}

    for raw_node in features_raw:
        if not isinstance(raw_node, dict):
            raise FeatureLogError(
                "each entry in 'features' must be a JSON object"
            )
        node_id = raw_node.get("id")
        op = raw_node.get("op")

        if not node_id or not isinstance(node_id, str):
            raise FeatureLogError(
                "feature node is missing a non-empty string 'id'",
                op=op,
            )
        if not op or not isinstance(op, str):
            raise FeatureLogError(
                "feature node is missing a non-empty string 'op'",
                node_id=node_id,
            )

        if op not in SUPPORTED_OPS:
            # Gracefully skip unsupported ops (cloud-side worker ops like
            # sweep1, network_srf, etc.) without raising.  Callers that want
            # stricter behaviour can inspect SUPPORTED_OPS themselves before
            # calling.
            import warnings
            warnings.warn(
                f"feature_io: skipping unsupported op {op!r} "
                f"(node={node_id!r}); only {sorted(SUPPORTED_OPS)} are "
                "supported by the in-proc evaluator set.",
                stacklevel=2,
            )
            continue

        feature: Feature
        if op == "box":
            feature = _translate_box(raw_node)
        elif op == "cylinder":
            feature = _translate_cylinder(raw_node)
        elif op == "sphere":
            feature = _translate_sphere(raw_node)
        elif op == "boolean":
            feature = _translate_boolean(raw_node, seen)
        elif op == "chamfer_edge":
            feature = _translate_chamfer_edge(raw_node, seen)
        elif op == "fillet_edge":
            feature = _translate_fillet_edge(raw_node, seen)
        else:
            # Should be unreachable given the SUPPORTED_OPS guard above.
            raise FeatureLogError(
                f"internal: unhandled op {op!r}", node_id=node_id, op=op
            )

        dag.add_feature(feature)
        seen[node_id] = feature

    return dag


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


def body_from_feature_log(source: _Source) -> Body:
    """Load a ``.feature`` log and return the Body produced by the *last*
    feature in the log.

    This is the "single-shot" API: parse the log, build the DAG, evaluate
    every feature in topological order, and return the Body produced by the
    tail feature (the one with no downstream dependencies in the log).

    Parameters
    ----------
    source:
        Raw JSON bytes/str, a pre-parsed dict, or a path-like to a
        ``.feature`` file.

    Returns
    -------
    Body
        The Body produced by the last feature.

    Raises
    ------
    FeatureLogError
        If the log is malformed or empty (no supported features).
    KeyError
        If no evaluator is registered for a feature kind (should not occur
        when the log contains only supported ops).
    """
    dag = load_feature_log(source)
    if len(dag) == 0:
        raise FeatureLogError(
            "no supported features found in the log; cannot produce a Body"
        )
    # Regenerate all features in topological order.
    dag.regenerate()
    # The "tip" is the last feature in topological order — the one that has
    # no downstream dependents within the log (it is the final result).
    order = dag.topological_order()
    tip_id = order[-1]
    return dag.evaluate(tip_id)


# ---------------------------------------------------------------------------
# DAG → .feature log round-trip (write direction)
# ---------------------------------------------------------------------------


def dag_to_feature_log(dag: FeatureDAG) -> Dict[str, Any]:
    """Serialise a :class:`FeatureDAG` as an append-only ``.feature`` log.

    This is the *inverse* of :func:`load_feature_log` for the subset of
    Feature kinds in :data:`SUPPORTED_OPS`.  The output is a plain dict
    suitable for ``json.dumps``.

    Only the built-in kinds (``box``, ``cylinder``, ``sphere``, ``boolean``,
    ``chamfer_edge``, ``fillet_edge``) are serialised; any other kind raises
    :class:`FeatureLogError`.
    """
    nodes: List[Dict[str, Any]] = []
    for fid in dag.feature_ids():
        feature = dag.get_feature(fid)
        node = _feature_to_log_node(feature)
        nodes.append(node)
    return {"version": 1, "features": nodes}


def _feature_to_log_node(feature: Feature) -> Dict[str, Any]:
    """Translate one Feature back to the flat log-node dict."""
    kind = feature.kind
    p = feature.params
    i = feature.inputs

    if kind == "box":
        return {
            "id": feature.id,
            "op": "box",
            "corner": list(p["corner"]),
            "dx": p["dx"],
            "dy": p["dy"],
            "dz": p["dz"],
            **({} if p.get("tol") == 1e-7 else {"tol": p["tol"]}),
        }
    if kind == "cylinder":
        return {
            "id": feature.id,
            "op": "cylinder",
            "axis_pt": list(p["axis_pt"]),
            "axis_dir": list(p["axis_dir"]),
            "radius": p["radius"],
            "height": p["height"],
            **({} if p.get("tol") == 1e-7 else {"tol": p["tol"]}),
        }
    if kind == "sphere":
        return {
            "id": feature.id,
            "op": "sphere",
            "centre": list(p["centre"]),
            "radius": p["radius"],
            **({} if p.get("tol") == 1e-7 else {"tol": p["tol"]}),
        }
    if kind == "boolean":
        a_ref = i["a"]
        b_ref = i["b"]
        return {
            "id": feature.id,
            "op": "boolean",
            "kind": p["op"],  # union / difference / intersection
            "target_a_id": a_ref.feature_id,
            "target_b_id": b_ref.feature_id,
            **({} if p.get("tol") == 1e-6 else {"tol": p["tol"]}),
        }
    if kind == "chamfer_edge":
        edge_sel = i["edge"]
        body_ref = i["body"]
        return {
            "id": feature.id,
            "op": "chamfer_edge",
            "target_id": body_ref.feature_id,
            "edge_role": edge_sel.role,
            "width": p["width"],
            **({} if p.get("tol") == 1e-6 else {"tol": p["tol"]}),
        }
    if kind == "fillet_edge":
        edge_sel = i["edge"]
        body_ref = i["body"]
        return {
            "id": feature.id,
            "op": "fillet_edge",
            "target_id": body_ref.feature_id,
            "edge_role": edge_sel.role,
            "radius": p["radius"],
            **({} if p.get("tol") == 1e-6 else {"tol": p["tol"]}),
        }
    raise FeatureLogError(
        f"cannot serialise feature with kind={kind!r}; "
        f"only {sorted(SUPPORTED_OPS)} are supported",
        node_id=feature.id,
        op=kind,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "SUPPORTED_OPS",
    "FeatureLogError",
    "load_feature_log",
    "body_from_feature_log",
    "dag_to_feature_log",
]
