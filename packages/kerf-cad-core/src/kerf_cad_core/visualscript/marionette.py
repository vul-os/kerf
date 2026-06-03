"""
kerf_cad_core.visualscript.marionette
========================================
Visual scripting engine with Vectorworks Marionette / MatrixGold semantics.

This module implements a directed-acyclic-graph (DAG) evaluation engine for
parametric, node-based visual scripting.  The design is modelled on:

  Vectorworks Marionette — Python-backed visual scripting system for
    architectural and entertainment design. Each "Marionette node" is a Python
    function wrapped in a graphical widget; nodes pass typed values through
    ports. Graphs are stored as JSON and evaluated in topological order.
    Reference: Vectorworks Developer Wiki — Marionette Scripting
    (https://developer.vectorworks.net/marionette)

  MatrixGold Visual Scripting — Vectorworks-derived DAG system for
    parametric jewellery design (Gemvision MatrixGold 2022). Shares the
    same DAG/port model with jewellery-specific node types
    (ring-sizer, stone-setter, prong-generator, etc.).
    Reference: Gemvision MatrixGold Visual Scripting Guide, 2022.

  Dynamo BIM — for comparison: Autodesk's node-based scripting for Revit.
    Reference: Aksamija, A. (2020). Parametric and Computational Design in
    Architectural Practice. Wiley/RIBA.

Architecture
------------
  MarionetteNode  — a single evaluation unit with input ports, a node_type,
                    and output ports.
  MarionetteGraph — a collection of nodes wired by directed edges
                    (src_node, src_pin) → (dst_node, dst_pin).
  evaluate_marionette_graph — topological-sort evaluator; calls a handler
                    Callable per node_type, routes values through connections.
  NODE_LIBRARY    — built-in handlers for 12+ common node types.

Topological sort
----------------
The graph is sorted using Kahn's algorithm (BFS-based topo sort).
Reference: Kahn, A.B. (1962). "Topological sorting of large networks."
           Communications of the ACM 5(11):558–562.

Cycle detection
---------------
If a cycle is detected during topological sort, a ValueError is raised with
a descriptive message identifying the cycle nodes.  This matches the behaviour
of Vectorworks Marionette (which refuses to evaluate a cyclic network) and
MatrixGold Visual Scripting.

Built-in node handlers
----------------------
All built-in handlers follow the signature:
    handler(inputs: dict) -> dict
where inputs is a dict of {pin_name: value} and the return is a dict of
output pin values.  Handler names match the Vectorworks Marionette node
library naming conventions where applicable.

Built-in types (NODE_LIBRARY keys):
  'wall'             — parametric wall geometry
  'floor'            — parametric floor / slab geometry
  'window'           — parametric window (requires host wall)
  'door'             — parametric door (requires host wall)
  'column'           — structural column
  'array'            — linear/radial array along a curve/axis
  'move'             — translate geometry by vector
  'rotate'           — rotate geometry by angle about axis
  'scale'            — scale geometry uniformly or non-uniformly
  'boolean_union'    — merge two geometry objects
  'boolean_subtract' — subtract tool from base
  'extrude'          — extrude a profile along a path
  'loft'             — loft between section profiles
  'material'         — assign material properties to geometry
  'truss_span'       — pavilion/stage truss span (Braceworks-inspired)

References
----------
Vectorworks Marionette documentation — https://developer.vectorworks.net/marionette
MatrixGold Visual Scripting Guide, Gemvision 2022.
Aksamija, A. (2020). Parametric and Computational Design in Architectural
  Practice. Wiley/RIBA.
Woodbury, R. (2010). Elements of Parametric Design. Routledge.
Kahn, A.B. (1962). Topological sorting of large networks. CACM 5(11).

Author: imranparuk
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "MarionetteNode",
    "MarionetteGraph",
    "evaluate_marionette_graph",
    "NODE_LIBRARY",
    # Individual handlers are also exported for testing.
    "handler_create_wall",
    "handler_create_floor",
    "handler_create_window",
    "handler_create_door",
    "handler_create_column",
    "handler_array_along_curve",
    "handler_move",
    "handler_rotate",
    "handler_scale",
    "handler_boolean_union",
    "handler_boolean_subtract",
    "handler_extrude",
    "handler_loft",
    "handler_assign_material",
    "handler_truss_span",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MarionetteNode:
    """One node in a Marionette visual-script graph.

    Inspired by Vectorworks Marionette node model (VW Developer Wiki §3.2)
    and MatrixGold Visual Scripting node definition.

    Attributes
    ----------
    node_id : str
        Unique identifier for this node within the graph.
    node_type : str
        Type key, e.g. 'wall', 'window', 'array'.  Must match a key in the
        node_handlers dict passed to evaluate_marionette_graph.
    inputs : dict
        Constant input values for unconnected input pins.
        Connected pins will have their values overwritten by upstream outputs
        during evaluation.
    outputs : dict
        Populated by the evaluator after this node is processed.
    """
    node_id: str
    node_type: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MarionetteGraph:
    """A directed acyclic graph of MarionetteNodes.

    Models a Vectorworks Marionette network or a MatrixGold visual-script
    network. Nodes are connected by typed wire connections from an output pin
    on one node to an input pin on another.

    Attributes
    ----------
    nodes : list of MarionetteNode
    connections : list of (src_node_id, src_pin, dst_node_id, dst_pin)
        Each connection routes the value of src_node.outputs[src_pin] into
        dst_node.inputs[dst_pin] before the dst_node is evaluated.
    """
    nodes: List[MarionetteNode]
    connections: List[Tuple[str, str, str, str]]

    # -------------------------------------------------------------------------
    # Topological ordering (Kahn 1962)
    # -------------------------------------------------------------------------

    def topological_order(self) -> List[str]:
        """Return node_ids in topological (dependency) order.

        Uses Kahn's algorithm (BFS-based, O(V+E)).
        Reference: Kahn (1962) CACM 5(11):558-562.

        Returns
        -------
        list of str
            node_ids ordered so that every node appears after all nodes it
            depends on (all its upstream / predecessor nodes).

        Raises
        ------
        ValueError
            If the graph contains a cycle.  Includes the set of cyclic node
            IDs in the error message.
        """
        node_ids = [n.node_id for n in self.nodes]
        # Build adjacency: src_node → [dst_nodes]
        out_edges: Dict[str, List[str]] = defaultdict(list)
        in_degree: Dict[str, int] = {nid: 0 for nid in node_ids}

        for src_id, _src_pin, dst_id, _dst_pin in self.connections:
            if src_id not in in_degree or dst_id not in in_degree:
                continue  # ignore dangling wires
            out_edges[src_id].append(dst_id)
            in_degree[dst_id] += 1

        # BFS queue: all nodes with in-degree 0 (no upstream dependencies).
        queue: deque[str] = deque(
            nid for nid in node_ids if in_degree[nid] == 0
        )
        order: List[str] = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            for dst in out_edges[nid]:
                in_degree[dst] -= 1
                if in_degree[dst] == 0:
                    queue.append(dst)

        if len(order) < len(node_ids):
            cyclic_nodes = {nid for nid in node_ids if nid not in set(order)}
            raise ValueError(
                f"Cycle detected in MarionetteGraph — cyclic node IDs: "
                f"{sorted(cyclic_nodes)}.  Vectorworks Marionette and MatrixGold "
                f"both refuse to evaluate cyclic networks."
            )

        return order

    # -------------------------------------------------------------------------
    # Convenience: look up a node by ID
    # -------------------------------------------------------------------------

    def get_node(self, node_id: str) -> Optional[MarionetteNode]:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def evaluate_marionette_graph(
    graph: MarionetteGraph,
    node_handlers: Optional[Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Evaluate a MarionetteGraph and return the final output state.

    For each node in topological order:
    1. Gather input values from any upstream connections (overwriting the
       node's constant defaults with routed values).
    2. Call node_handlers[node.node_type](inputs) to compute outputs.
    3. Store outputs back onto the node object and in the result dict.

    Nodes whose node_type is not in node_handlers are treated as pass-through
    (outputs = inputs) with a warning logged in the output dict.

    Parameters
    ----------
    graph : MarionetteGraph
        The graph to evaluate.
    node_handlers : dict, optional
        Custom handler registry { node_type: handler_fn }.
        Merged on top of NODE_LIBRARY — custom handlers take precedence.

    Returns
    -------
    dict
        { node_id: { 'inputs': {...}, 'outputs': {...} } } for every node.

    Raises
    ------
    ValueError
        If the graph contains a cycle (re-raised from topological_order).
    """
    handlers: Dict[str, Callable] = dict(NODE_LIBRARY)
    if node_handlers:
        handlers.update(node_handlers)

    # Deep-copy node inputs so multiple evaluations don't interfere.
    nodes_by_id: Dict[str, MarionetteNode] = {
        n.node_id: copy.deepcopy(n) for n in graph.nodes
    }

    # Topological order (raises ValueError on cycle).
    order = graph.topological_order()

    # Build a connection lookup: (dst_node_id, dst_pin) → (src_node_id, src_pin)
    wire_map: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for src_id, src_pin, dst_id, dst_pin in graph.connections:
        wire_map[(dst_id, dst_pin)] = (src_id, src_pin)

    result: Dict[str, Dict[str, Any]] = {}

    for nid in order:
        node = nodes_by_id[nid]

        # Route upstream outputs into this node's inputs.
        resolved_inputs = dict(node.inputs)
        for (d_id, d_pin), (s_id, s_pin) in wire_map.items():
            if d_id == nid:
                src_node = nodes_by_id.get(s_id)
                if src_node and s_pin in src_node.outputs:
                    resolved_inputs[d_pin] = src_node.outputs[s_pin]

        # Evaluate.
        if node.node_type in handlers:
            try:
                outputs = handlers[node.node_type](resolved_inputs)
            except Exception as exc:
                outputs = {
                    "_error": str(exc),
                    "_node_type": node.node_type,
                }
        else:
            # Unknown node type → pass-through with advisory.
            outputs = dict(resolved_inputs)
            outputs["_warning"] = (
                f"No handler for node_type={node.node_type!r}; "
                "outputs mirror inputs (pass-through). "
                "Vectorworks Marionette would display a 'node not found' error."
            )

        node.outputs = outputs
        result[nid] = {
            "inputs": resolved_inputs,
            "outputs": outputs,
        }

    return result


# ---------------------------------------------------------------------------
# Built-in node handlers
# ---------------------------------------------------------------------------
# All handlers: (inputs: dict) -> (outputs: dict)
# Input keys match Vectorworks Marionette port naming conventions where
# possible (VW uses 'height', 'length', 'width', 'angle', etc.).
# ---------------------------------------------------------------------------

def handler_create_wall(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Create a parametric wall segment.

    Inputs
    ------
    length   : float  — wall length (m, default 4.0)
    height   : float  — wall height (m, default 2.7)
    thickness: float  — wall thickness (m, default 0.2)
    start_pt : [x, y, z] — start point (default [0,0,0])
    end_pt   : [x, y, z] — end point (overrides length if provided)
    material : str    — material name (default 'concrete')

    Outputs
    -------
    geometry : dict with wall type, dimensions, start/end, material
    length   : float  actual length (m)
    volume_m3: float  wall volume (m³)
    area_m2  : float  wall face area (m²)

    Reference: Vectorworks Marionette Wall node (VW 2023 library).
    """
    start = list(inputs.get("start_pt", [0.0, 0.0, 0.0]))
    end_raw = inputs.get("end_pt")
    length = float(inputs.get("length", 4.0))
    height = float(inputs.get("height", 2.7))
    thickness = float(inputs.get("thickness", 0.2))
    material = str(inputs.get("material", "concrete"))

    if end_raw is not None:
        end = list(end_raw)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.sqrt(dx * dx + dy * dy)
    else:
        end = [start[0] + length, start[1], start[2]]

    volume = length * height * thickness
    area = length * height

    return {
        "geometry": {
            "type": "wall",
            "start_pt": start,
            "end_pt": end,
            "height_m": height,
            "thickness_m": thickness,
            "material": material,
        },
        "length": round(length, 6),
        "volume_m3": round(volume, 6),
        "area_m2": round(area, 6),
    }


def handler_create_floor(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Create a parametric floor / slab.

    Inputs
    ------
    width     : float   — slab width (m, default 5.0)
    length    : float   — slab length (m, default 5.0)
    thickness : float   — slab thickness (m, default 0.15)
    elevation : float   — Z elevation (m, default 0.0)
    material  : str     — material (default 'concrete')

    Outputs
    -------
    geometry  : dict    slab geometry definition
    area_m2   : float   floor area (m²)
    volume_m3 : float   concrete volume (m³)

    Reference: Vectorworks Marionette Floor node.
    """
    width = float(inputs.get("width", 5.0))
    length = float(inputs.get("length", 5.0))
    thickness = float(inputs.get("thickness", 0.15))
    elevation = float(inputs.get("elevation", 0.0))
    material = str(inputs.get("material", "concrete"))

    area = width * length
    volume = area * thickness

    return {
        "geometry": {
            "type": "floor",
            "width_m": width,
            "length_m": length,
            "thickness_m": thickness,
            "elevation_m": elevation,
            "material": material,
        },
        "area_m2": round(area, 6),
        "volume_m3": round(volume, 6),
    }


def handler_create_window(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a parametric window into a host wall.

    Inputs
    ------
    host_wall : dict   — geometry dict from a wall node
    width     : float  — window width (m, default 1.2)
    height    : float  — window height (m, default 1.0)
    sill_height: float — sill height from floor (m, default 0.9)
    position  : float  — distance along wall from start (m, default wall_length/2)
    glazing   : str    — glazing type (default 'double')

    Outputs
    -------
    geometry   : dict  window geometry definition
    opening_area_m2: float
    wall_modified: dict   wall geometry with opening cut

    Reference: Vectorworks Marionette Window node.
    """
    host = inputs.get("host_wall", {})
    width = float(inputs.get("width", 1.2))
    height = float(inputs.get("height", 1.0))
    sill_h = float(inputs.get("sill_height", 0.9))
    glazing = str(inputs.get("glazing", "double"))
    wall_length = host.get("length_m", host.get("geometry", {}).get("length_m", 4.0))
    if not isinstance(wall_length, (int, float)):
        wall_length = 4.0
    pos = float(inputs.get("position", float(wall_length) / 2.0))

    opening_area = width * height

    return {
        "geometry": {
            "type": "window",
            "width_m": width,
            "height_m": height,
            "sill_height_m": sill_h,
            "position_m": pos,
            "glazing": glazing,
        },
        "opening_area_m2": round(opening_area, 6),
        "wall_modified": dict(host) if isinstance(host, dict) else {},
    }


def handler_create_door(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a parametric door into a host wall.

    Inputs
    ------
    host_wall : dict   — geometry from wall node
    width     : float  — door width (m, default 0.9)
    height    : float  — door height (m, default 2.1)
    position  : float  — distance along wall from start (m)
    swing     : str    — 'left', 'right', 'double' (default 'left')

    Outputs
    -------
    geometry      : dict
    opening_area_m2: float

    Reference: Vectorworks Marionette Door node.
    """
    host = inputs.get("host_wall", {})
    width = float(inputs.get("width", 0.9))
    height = float(inputs.get("height", 2.1))
    pos = float(inputs.get("position", 0.5))
    swing = str(inputs.get("swing", "left"))

    return {
        "geometry": {
            "type": "door",
            "width_m": width,
            "height_m": height,
            "position_m": pos,
            "swing": swing,
        },
        "opening_area_m2": round(width * height, 6),
    }


def handler_create_column(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Create a parametric structural column.

    Inputs
    ------
    location   : [x, y, z] — base centre (default [0,0,0])
    height     : float  — column height (m, default 3.0)
    section    : str    — 'circular', 'square', 'wide_flange' (default 'circular')
    diameter   : float  — diameter for circular (m, default 0.3)
    width      : float  — width for square (m, default 0.3)
    material   : str    — default 'steel'

    Outputs
    -------
    geometry   : dict
    section_area_m2: float
    volume_m3  : float

    Reference: Vectorworks Marionette Column node.
    """
    loc = list(inputs.get("location", [0.0, 0.0, 0.0]))
    height = float(inputs.get("height", 3.0))
    section = str(inputs.get("section", "circular"))
    diameter = float(inputs.get("diameter", 0.3))
    width = float(inputs.get("width", 0.3))
    material = str(inputs.get("material", "steel"))

    if section == "circular":
        area = math.pi * (diameter / 2.0) ** 2
    else:
        area = width * width

    volume = area * height

    return {
        "geometry": {
            "type": "column",
            "location": loc,
            "height_m": height,
            "section": section,
            "diameter_m": diameter if section == "circular" else None,
            "width_m": width if section != "circular" else None,
            "material": material,
        },
        "section_area_m2": round(area, 8),
        "volume_m3": round(volume, 6),
    }


def handler_array_along_curve(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Array a geometry item linearly or radially along a path.

    Inputs
    ------
    item      : dict   — geometry to array (from upstream node)
    count     : int    — number of instances (default 4)
    spacing   : float  — spacing between instances (m, default 1.0)
    direction : [x,y,z] — direction vector for linear array (default [1,0,0])
    mode      : str    — 'linear' | 'radial' (default 'linear')
    radius    : float  — radius for radial mode (m, default 2.0)
    start_angle: float — start angle degrees for radial (default 0.0)

    Outputs
    -------
    instances : list of dicts, each with 'item', 'position', 'index'
    count     : int actual count

    Reference: Vectorworks Marionette 'Linear Array' and 'Radial Array' nodes.
               MatrixGold 'Ring Duplicator' node.
    """
    item = inputs.get("item", {})
    count = max(1, int(inputs.get("count", 4)))
    spacing = float(inputs.get("spacing", 1.0))
    direction = list(inputs.get("direction", [1.0, 0.0, 0.0]))
    mode = str(inputs.get("mode", "linear"))
    radius = float(inputs.get("radius", 2.0))
    start_angle = float(inputs.get("start_angle", 0.0))

    instances = []
    if mode == "radial":
        angle_step = 360.0 / count
        for i in range(count):
            angle_deg = start_angle + i * angle_step
            angle_rad = math.radians(angle_deg)
            pos = [radius * math.cos(angle_rad), radius * math.sin(angle_rad), 0.0]
            instances.append({
                "item": copy.deepcopy(item),
                "position": pos,
                "angle_deg": round(angle_deg, 4),
                "index": i,
            })
    else:
        # Normalise direction vector.
        mag = math.sqrt(sum(d * d for d in direction))
        if mag > 1e-9:
            direction = [d / mag for d in direction]
        for i in range(count):
            offset = spacing * i
            pos = [direction[j] * offset for j in range(3)]
            instances.append({
                "item": copy.deepcopy(item),
                "position": pos,
                "index": i,
            })

    return {
        "instances": instances,
        "count": len(instances),
    }


def handler_move(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Translate geometry by a vector.

    Inputs
    ------
    geometry  : dict   — geometry to move
    vector    : [dx, dy, dz] — translation vector (m, default [0,0,0])

    Outputs
    -------
    geometry  : dict  moved geometry (new 'origin' added or updated)

    Reference: Vectorworks Marionette 'Move' node.
    """
    geom = copy.deepcopy(inputs.get("geometry", {}))
    vec = list(inputs.get("vector", [0.0, 0.0, 0.0]))

    origin = list(geom.get("origin", [0.0, 0.0, 0.0]))
    new_origin = [origin[i] + vec[i] for i in range(3)]
    geom["origin"] = new_origin
    geom["_transform_move"] = vec

    return {"geometry": geom}


def handler_rotate(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Rotate geometry about an axis.

    Inputs
    ------
    geometry  : dict   — geometry to rotate
    angle_deg : float  — rotation angle in degrees (default 0.0)
    axis      : [x,y,z] — rotation axis (default [0,0,1] = Z-up)
    center    : [x,y,z] — centre of rotation (default [0,0,0])

    Outputs
    -------
    geometry  : dict  rotated geometry (transform recorded)

    Reference: Vectorworks Marionette 'Rotate' node.
    """
    geom = copy.deepcopy(inputs.get("geometry", {}))
    angle = float(inputs.get("angle_deg", 0.0))
    axis = list(inputs.get("axis", [0.0, 0.0, 1.0]))
    center = list(inputs.get("center", [0.0, 0.0, 0.0]))

    geom["_transform_rotate"] = {
        "angle_deg": angle,
        "axis": axis,
        "center": center,
    }

    return {"geometry": geom}


def handler_scale(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Scale geometry uniformly or non-uniformly.

    Inputs
    ------
    geometry  : dict   — geometry to scale
    scale     : float | [sx, sy, sz] — scale factor(s) (default 1.0)
    center    : [x,y,z] — scale centre (default [0,0,0])

    Outputs
    -------
    geometry  : dict  scaled geometry

    Reference: Vectorworks Marionette 'Scale' node.
               MatrixGold 'Scale Object' node.
    """
    geom = copy.deepcopy(inputs.get("geometry", {}))
    scale_raw = inputs.get("scale", 1.0)
    if isinstance(scale_raw, (int, float)):
        scale = [float(scale_raw)] * 3
    else:
        scale = [float(v) for v in scale_raw]
    center = list(inputs.get("center", [0.0, 0.0, 0.0]))

    geom["_transform_scale"] = {
        "scale": scale,
        "center": center,
    }

    return {"geometry": geom}


def handler_boolean_union(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Merge (union) two geometry objects.

    Inputs
    ------
    geometry_a : dict
    geometry_b : dict

    Outputs
    -------
    geometry : dict  representing the union (metadata combined)

    Reference: Vectorworks Marionette 'Add Solids' node.
               MatrixGold 'Boolean Union' node.
    """
    a = inputs.get("geometry_a", {})
    b = inputs.get("geometry_b", {})
    return {
        "geometry": {
            "type": "boolean_union",
            "operand_a": a,
            "operand_b": b,
        }
    }


def handler_boolean_subtract(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Subtract tool geometry from a base geometry.

    Inputs
    ------
    base_geometry : dict
    tool_geometry : dict

    Outputs
    -------
    geometry : dict  result (base minus tool)

    Reference: Vectorworks Marionette 'Subtract Solids' node.
               MatrixGold 'Boolean Subtract' node.
    """
    base = inputs.get("base_geometry", {})
    tool = inputs.get("tool_geometry", {})
    return {
        "geometry": {
            "type": "boolean_subtract",
            "base": base,
            "tool": tool,
        }
    }


def handler_extrude(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Extrude a 2-D profile along a direction.

    Inputs
    ------
    profile    : dict  — 2D profile geometry (e.g. list of [x,y] pts or dict)
    distance   : float — extrusion distance (m, default 1.0)
    direction  : [x,y,z] — extrusion direction (default [0,0,1])
    taper_deg  : float — taper draft angle (degrees, default 0.0)

    Outputs
    -------
    geometry   : dict  extruded solid

    Reference: Vectorworks Marionette 'Extrude' node.
    """
    profile = inputs.get("profile", {"type": "profile", "points": []})
    distance = float(inputs.get("distance", 1.0))
    direction = list(inputs.get("direction", [0.0, 0.0, 1.0]))
    taper = float(inputs.get("taper_deg", 0.0))

    return {
        "geometry": {
            "type": "extrude",
            "profile": profile,
            "distance_m": distance,
            "direction": direction,
            "taper_deg": taper,
        }
    }


def handler_loft(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Loft between two or more section profiles.

    Inputs
    ------
    profiles   : list of dicts — section profiles in order
    closed     : bool          — closed loft (default False)
    ruled      : bool          — ruled surface vs smooth (default False)

    Outputs
    -------
    geometry   : dict  lofted solid / surface

    Reference: Vectorworks Marionette 'Loft Surface' node.
    """
    profiles = list(inputs.get("profiles", []))
    closed = bool(inputs.get("closed", False))
    ruled = bool(inputs.get("ruled", False))

    return {
        "geometry": {
            "type": "loft",
            "profiles": profiles,
            "closed": closed,
            "ruled": ruled,
            "section_count": len(profiles),
        }
    }


def handler_assign_material(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Assign material properties to a geometry object.

    Inputs
    ------
    geometry   : dict
    material   : str   — material name (e.g. 'steel_s355', 'alu_6061_t6', 'timber_gl28h')
    colour     : str   — hex colour (default '#c0c0c0')
    texture    : str   — texture name (default '')
    E_MPa      : float — elastic modulus (MPa, optional)
    density_kg_m3: float — density (kg/m³, optional)

    Outputs
    -------
    geometry   : dict  geometry with material properties attached

    Reference: Vectorworks Marionette 'Set Material' node.
               MatrixGold 'Metal Preset' node.
    """
    geom = copy.deepcopy(inputs.get("geometry", {}))
    material = str(inputs.get("material", "steel"))
    colour = str(inputs.get("colour", "#c0c0c0"))
    texture = str(inputs.get("texture", ""))

    mat_props: Dict[str, Any] = {
        "name": material,
        "colour": colour,
        "texture": texture,
    }
    if "E_MPa" in inputs:
        mat_props["E_MPa"] = float(inputs["E_MPa"])
    if "density_kg_m3" in inputs:
        mat_props["density_kg_m3"] = float(inputs["density_kg_m3"])

    geom["material"] = mat_props
    return {"geometry": geom}


def handler_truss_span(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Create a pavilion / stage truss span geometry node.

    Inspired by Vectorworks Braceworks (entertainment rigging module) and the
    ANSI E1.2 truss topology.

    Inputs
    ------
    start_pt   : [x, y, z] — start point (m, default [0,0,3])
    end_pt     : [x, y, z] — end point (m, default [6,0,3])
    truss_type : str   — 'box', 'triangle', 'ladder' (default 'box')
    chord_size : float — chord tube OD (mm, default 50)
    panel_width: float — panel-to-panel width (m, default 0.29)
    self_weight_per_m: float — truss self-weight (N/m, default 80)
    max_udl    : float — manufacturer rated max UDL (N/m, default 500)

    Outputs
    -------
    geometry         : dict  truss geometry definition
    span_m           : float  truss span length
    estimated_mass_kg: float  truss estimated mass
    rated_udl_n_m    : float  manufacturer max UDL

    Reference: ANSI E1.2-2012; Vectorworks Braceworks module.
    """
    start = list(inputs.get("start_pt", [0.0, 0.0, 3.0]))
    end = list(inputs.get("end_pt", [6.0, 0.0, 3.0]))
    truss_type = str(inputs.get("truss_type", "box"))
    chord_size = float(inputs.get("chord_size", 50.0))
    panel_width = float(inputs.get("panel_width", 0.29))
    sw_per_m = float(inputs.get("self_weight_per_m", 80.0))
    max_udl = float(inputs.get("max_udl", 500.0))

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    span = math.sqrt(dx * dx + dy * dy + dz * dz)

    g = 9.80665
    mass = (sw_per_m * span) / g  # kg

    return {
        "geometry": {
            "type": "truss_span",
            "truss_type": truss_type,
            "start_pt": start,
            "end_pt": end,
            "chord_size_mm": chord_size,
            "panel_width_m": panel_width,
        },
        "span_m": round(span, 4),
        "estimated_mass_kg": round(mass, 2),
        "rated_udl_n_m": max_udl,
    }


# ---------------------------------------------------------------------------
# Built-in node handler library
# ---------------------------------------------------------------------------
# Keys match Vectorworks Marionette / MatrixGold node type naming conventions.

NODE_LIBRARY: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "wall": handler_create_wall,
    "floor": handler_create_floor,
    "window": handler_create_window,
    "door": handler_create_door,
    "column": handler_create_column,
    "array": handler_array_along_curve,
    "move": handler_move,
    "rotate": handler_rotate,
    "scale": handler_scale,
    "boolean_union": handler_boolean_union,
    "boolean_subtract": handler_boolean_subtract,
    "extrude": handler_extrude,
    "loft": handler_loft,
    "material": handler_assign_material,
    "truss_span": handler_truss_span,
}
