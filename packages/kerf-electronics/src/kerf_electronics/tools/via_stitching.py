import json
from kerf_electronics._compat import ToolSpec, ok_payload, err_payload, register

ADD_VIA_STITCHING_SPEC = ToolSpec(
    name="add_via_stitching",
    description="Add via stitching pattern to a copper pour or board outline. Supports grid, perimeter, and hex strategies.",
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {"type": "object", "description": "CircuitJSON board"},
            "pour_id_or_polygon": {
                "oneOf": [
                    {"type": "string", "description": "pour_id for existing copper_pour"},
                    {"type": "array", "description": "Polygon array of {x,y} points"}
                ]
            },
            "pitch_mm": {"type": "number", "description": "Spacing between vias in mm"},
            "net_id": {"type": "string", "description": "Net ID for the stitching vias"},
            "strategy": {"type": "string", "enum": ["grid", "perimeter", "hex"], "default": "grid"},
            "via_spec": {
                "type": "object",
                "properties": {
                    "diameter": {"type": "number"},
                    "drill": {"type": "number"}
                },
                "required": ["diameter", "drill"]
            },
            "edge_offset_mm": {"type": "number", "default": 0}
        },
        "required": ["circuit_json", "pour_id_or_polygon", "pitch_mm", "net_id", "via_spec"]
    }
)

APPLY_TEARDROPS_SPEC = ToolSpec(
    name="apply_teardrops",
    description="Apply teardrop fillets to all pad-via trace connections in the circuit.",
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {"type": "object", "description": "CircuitJSON board"},
            "radius_factor": {"type": "number", "default": 1.5}
        },
        "required": ["circuit_json"]
    }
)

REMOVE_VIA_STITCHING_SPEC = ToolSpec(
    name="remove_via_stitching",
    description="Remove via stitching from a copper pour by pour_id.",
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {"type": "object", "description": "CircuitJSON board"},
            "pour_id": {"type": "string", "description": "pour_id to remove stitching from"}
        },
        "required": ["circuit_json", "pour_id"]
    }
)


def _generate_stitching_pattern(polygon, pitch_mm, via_spec, edge_offset_mm=0):
    diameter = via_spec['diameter']
    drill = via_spec['drill']
    net_id = via_spec['net_id']
    radius = diameter / 2
    offset = edge_offset_mm + radius

    xs = [p['x'] for p in polygon]
    ys = [p['y'] for p in polygon]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    inner_min_x = min_x + offset
    inner_max_x = max_x - offset
    inner_min_y = min_y + offset
    inner_max_y = max_y - offset

    if inner_max_x <= inner_min_x or inner_max_y <= inner_min_y:
        return []

    cols = int((inner_max_x - inner_min_x) / pitch_mm) + 1
    rows = int((inner_max_y - inner_min_y) / pitch_mm) + 1

    vias = []
    for row in range(rows):
        for col in range(cols):
            x = inner_min_x + col * pitch_mm
            y = inner_min_y + row * pitch_mm
            if x <= max_x - radius and y <= max_y - radius:
                vias.append({'x': x, 'y': y, 'net_id': net_id, 'diameter': diameter, 'drill': drill})
    return vias


def _grid_stitching(polygon, pitch_mm, via_spec, edge_offset_mm=0):
    return _generate_stitching_pattern(polygon, pitch_mm, via_spec, edge_offset_mm)


def _perimeter_stitching(polygon, pitch_mm, via_spec, edge_offset_mm=0):
    diameter = via_spec['diameter']
    drill = via_spec['drill']
    net_id = via_spec['net_id']
    radius = diameter / 2
    offset = edge_offset_mm + radius

    xs = [p['x'] for p in polygon]
    ys = [p['y'] for p in polygon]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    left_edge = min_x + offset
    right_edge = max_x - offset
    bottom_edge = min_y + offset
    top_edge = max_y - offset

    width = right_edge - left_edge
    height = top_edge - bottom_edge

    if width <= 0 or height <= 0:
        return []

    vias = []

    num_right = int(height / pitch_mm) + 1
    for i in range(num_right):
        y = bottom_edge + i * pitch_mm
        if y <= top_edge:
            vias.append({'x': right_edge, 'y': y, 'net_id': net_id, 'diameter': diameter, 'drill': drill})

    num_left = int(height / pitch_mm) + 1
    for i in range(num_left):
        y = bottom_edge + i * pitch_mm
        if y <= top_edge:
            vias.append({'x': left_edge, 'y': y, 'net_id': net_id, 'diameter': diameter, 'drill': drill})

    num_top = int(width / pitch_mm) + 1
    for i in range(1, num_top):
        x = left_edge + i * pitch_mm
        if x < right_edge:
            vias.append({'x': x, 'y': top_edge, 'net_id': net_id, 'diameter': diameter, 'drill': drill})

    num_bottom = int(width / pitch_mm) + 1
    for i in range(1, num_bottom):
        x = left_edge + i * pitch_mm
        if x < right_edge:
            vias.append({'x': x, 'y': bottom_edge, 'net_id': net_id, 'diameter': diameter, 'drill': drill})

    return vias


def _hex_stitching(polygon, pitch_mm, via_spec, edge_offset_mm=0):
    diameter = via_spec['diameter']
    drill = via_spec['drill']
    net_id = via_spec['net_id']
    radius = diameter / 2
    offset = edge_offset_mm + radius

    xs = [p['x'] for p in polygon]
    ys = [p['y'] for p in polygon]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    inner_min_x = min_x + offset
    inner_max_x = max_x - offset
    inner_min_y = min_y + offset
    inner_max_y = max_y - offset

    if inner_max_x <= inner_min_x or inner_max_y <= inner_min_y:
        return []

    row_pitch = pitch_mm * (3 ** 0.5) / 2
    col_pitch = pitch_mm

    width = inner_max_x - inner_min_x
    height = inner_max_y - inner_min_y

    cols = int(width / col_pitch) + 2
    rows = int(height / row_pitch) + 2

    vias = []
    for row in range(rows):
        row_offset = (row % 2) * (col_pitch / 2)
        y = inner_min_y + row * row_pitch
        start_col = 1 if row % 2 else 0
        for col in range(start_col, cols):
            x = inner_min_x + col * col_pitch + row_offset
            if min_x + radius <= x <= max_x - radius and min_y + radius <= y <= max_y - radius:
                vias.append({'x': x, 'y': y, 'net_id': net_id, 'diameter': diameter, 'drill': drill})
    return vias


def _teardrop_for_pad_via(pad_or_via, trace, radius_factor=1.5):
    px = pad_or_via['x']
    py = pad_or_via['y']
    pad_radius = (pad_or_via.get('width') or pad_or_via.get('diameter') or 1) / 2
    trace_width = trace.get('width', 0.25)
    teardrop_radius = trace_width * radius_factor

    route = trace.get('route', [])
    if len(route) < 2:
        return None

    closest_idx = 0
    closest_dist = float('inf')
    for i, pt in enumerate(route):
        dx = pt['x'] - px
        dy = pt['y'] - py
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < closest_dist:
            closest_dist = dist
            closest_idx = i

    pt = route[closest_idx]
    dx = px - pt['x']
    dy = py - pt['y']
    dist = (dx * dx + dy * dy) ** 0.5

    if dist < 0.001:
        seg_idx = max(0, closest_idx - 1)
        seg_pt = route[seg_idx]
        seg_dx = pt['x'] - seg_pt['x']
        seg_dy = pt['y'] - seg_pt['y']
        seg_len = (seg_dx * seg_dx + seg_dy * seg_dy) ** 0.5
        if seg_len > 0.001:
            nx = -seg_dy / seg_len
            ny = seg_dx / seg_len
            base_x = pt['x'] + nx * trace_width / 2
            base_y = pt['y'] + ny * trace_width / 2
            tip_x = px - nx * teardrop_radius
            tip_y = py - ny * teardrop_radius
            return [
                {'x': base_x, 'y': base_y},
                {'x': px, 'y': py},
                {'x': pt['x'] - nx * trace_width / 2, 'y': pt['y'] - ny * trace_width / 2}
            ]
        return None

    nx = dx / dist
    ny = dy / dist
    base_x = pt['x'] + nx * trace_width / 2
    base_y = pt['y'] + ny * trace_width / 2
    tip_x = px - nx * teardrop_radius
    tip_y = py - ny * teardrop_radius

    return [
        {'x': base_x, 'y': base_y},
        {'x': tip_x, 'y': tip_y},
        {'x': pt['x'] - nx * trace_width / 2, 'y': pt['y'] - ny * trace_width / 2}
    ]


# ─── T-536: canonical flat Circuit-JSON pour lookup ────────────────────────────
#
# Kerf's canonical pour shape (see kicad_io.py, fab/gerber.py, fab/odbpp/writer.py)
# is a flat Circuit-JSON element — `pcb_copper_pour` (net-bound) or
# `pcb_ground_plane` (no-net) — identified by `pcb_copper_pour_id` /
# `pcb_ground_plane_id`, carrying `layer`/`polygon`/`clearance_mm`/etc. This
# module previously only understood a structurally different convention:
# `circuit_json['pcb_board']['copper_pour']`, a list keyed by `pour_id`. That
# nested-dict shape is preserved below as a **shim** for existing callers (its
# own registered ToolSpec + tests) but is no longer how pours are read
# elsewhere in the codebase; new callers should pass the flat array.

def _find_pour_polygon_flat(circuit_json: list, pour_id: str) -> list | None:
    """Resolve *pour_id* against `pcb_copper_pour_id` / `pcb_ground_plane_id`
    in a canonical flat Circuit-JSON array. Returns the polygon or None."""
    for el in circuit_json:
        if not isinstance(el, dict):
            continue
        t = el.get('type')
        if t == 'pcb_copper_pour' and el.get('pcb_copper_pour_id') == pour_id:
            return el.get('polygon', [])
        if t == 'pcb_ground_plane' and el.get('pcb_ground_plane_id') == pour_id:
            return el.get('polygon', [])
    return None


def _run_stitching_strategy(strategy, polygon, pitch_mm, via_spec_full, edge_offset_mm):
    """Shared strategy dispatch. Returns (vias, error_message_or_None)."""
    if strategy == 'grid':
        return _grid_stitching(polygon, pitch_mm, via_spec_full, edge_offset_mm), None
    elif strategy == 'perimeter':
        return _perimeter_stitching(polygon, pitch_mm, via_spec_full, edge_offset_mm), None
    elif strategy == 'hex':
        return _hex_stitching(polygon, pitch_mm, via_spec_full, edge_offset_mm), None
    return None, f"Unknown strategy: {strategy}"


def _add_via_stitching_flat(circuit_json, pour_or_poly, pitch_mm, net_id,
                             strategy, via_spec, edge_offset_mm):
    """Canonical-shape (T-536) implementation: operates on the flat
    Circuit-JSON array, resolving pours by `pcb_copper_pour_id` /
    `pcb_ground_plane_id` and emitting stitching vias as ordinary `pcb_via`
    elements plus one `pcb_via_stitching` metadata element (so
    remove_via_stitching can undo the operation without a nested board dict).
    """
    import copy
    circuit_json = copy.deepcopy(circuit_json)

    if isinstance(pour_or_poly, str):
        polygon = _find_pour_polygon_flat(circuit_json, pour_or_poly)
        if polygon is None:
            return err_payload(f"Copper pour {pour_or_poly} not found", "NOT_FOUND")
    else:
        polygon = pour_or_poly

    via_spec_full = {
        'diameter': via_spec.get('diameter', 0.8),
        'drill': via_spec.get('drill', 0.4),
        'net_id': net_id
    }

    vias, err = _run_stitching_strategy(strategy, polygon, pitch_mm, via_spec_full, edge_offset_mm)
    if err:
        return err_payload(err, "BAD_ARGS")

    pour_id = pour_or_poly if isinstance(pour_or_poly, str) else None
    existing_groups = sum(
        1 for e in circuit_json
        if isinstance(e, dict) and e.get('type') == 'pcb_via_stitching'
    )
    stitch_id = f"via_stitching_{pour_id or 'polygon'}_{existing_groups}"

    via_ids = []
    for i, v in enumerate(vias):
        via_el_id = f"{stitch_id}_via{i}"
        via_ids.append(via_el_id)
        circuit_json.append({
            'type': 'pcb_via',
            'pcb_via_id': via_el_id,
            'x': v['x'],
            'y': v['y'],
            'outer_diameter': v['diameter'],
            'drill_diameter': v['drill'],
            'net_id': v['net_id'],
            'from_layer': 'top_copper',
            'to_layer': 'bottom_copper',
            'pour_id': pour_id,
        })

    circuit_json.append({
        'type': 'pcb_via_stitching',
        'pcb_via_stitching_id': stitch_id,
        'pour_id': pour_id,
        'strategy': strategy,
        'pitch_mm': pitch_mm,
        'via_ids': via_ids,
    })

    return ok_payload({'circuit_json': circuit_json})


@register(ADD_VIA_STITCHING_SPEC, write=True)
async def add_via_stitching(ctx, args):
    try:
        a = json.loads(args)
    except Exception:
        return err_payload("Invalid JSON", "PARSE_ERROR")

    circuit = a.get('circuit_json')
    pour_or_poly = a.get('pour_id_or_polygon')
    pitch_mm = a.get('pitch_mm')
    net_id = a.get('net_id')
    strategy = a.get('strategy', 'grid')
    via_spec = a.get('via_spec')
    edge_offset_mm = a.get('edge_offset_mm', 0)

    if not circuit or not pour_or_poly or not pitch_mm or not net_id or not via_spec:
        return err_payload("Missing required fields", "BAD_ARGS")

    # T-536: canonical flat Circuit-JSON array.
    if isinstance(circuit, list):
        return _add_via_stitching_flat(circuit, pour_or_poly, pitch_mm, net_id,
                                        strategy, via_spec, edge_offset_mm)

    # ── Shim: legacy `{'pcb_board': {'copper_pour': [...]}}` shape ──────────
    # Kept for existing callers of this tool; not the canonical pour shape
    # used elsewhere (kicad_io.py, fab/gerber.py, fab/odbpp/writer.py). See
    # T-536 in tasks.md — deferred work: retire once callers move to the
    # flat array.
    board = circuit.get('pcb_board') or circuit.get('board')
    if not board:
        return err_payload("No pcb_board found", "BAD_ARGS")

    if isinstance(pour_or_poly, str):
        pour_id = pour_or_poly
        copper_pours = board.get('copper_pour', [])
        found = None
        for p in copper_pours:
            if p.get('pour_id') == pour_id:
                found = p
                break
        if not found:
            return err_payload(f"Copper pour {pour_id} not found", "NOT_FOUND")
        polygon = found.get('polygon', [])
    else:
        polygon = pour_or_poly

    via_spec_full = {
        'diameter': via_spec.get('diameter', 0.8),
        'drill': via_spec.get('drill', 0.4),
        'net_id': net_id
    }

    vias, err = _run_stitching_strategy(strategy, polygon, pitch_mm, via_spec_full, edge_offset_mm)
    if err:
        return err_payload(err, "BAD_ARGS")

    if 'via_stitching' not in board:
        board['via_stitching'] = []

    stitching_entry = {
        'pour_id': pour_or_poly if isinstance(pour_or_poly, str) else 'polygon',
        'vias': vias,
        'strategy': strategy,
        'pitch_mm': pitch_mm
    }
    board['via_stitching'].append(stitching_entry)

    return ok_payload({'circuit_json': circuit})


@register(APPLY_TEARDROPS_SPEC, write=True)
async def apply_teardrops(ctx, args):
    try:
        a = json.loads(args)
    except Exception:
        return err_payload("Invalid JSON", "PARSE_ERROR")

    circuit = a.get('circuit_json')
    radius_factor = a.get('radius_factor', 1.5)

    if not circuit:
        return err_payload("Missing circuit_json", "BAD_ARGS")

    import copy
    circuit = copy.deepcopy(circuit)
    board = circuit.get('pcb_board') or circuit.get('board')
    if not board:
        return err_payload("No pcb_board found", "BAD_ARGS")

    if 'teardrops' not in board:
        board['teardrops'] = []

    traces = [t for t in board.get('pcb_trace', []) if t.get('route') and len(t['route']) >= 2]
    pads = board.get('pcb_pad', [])
    vias = board.get('pcb_via', [])

    for pad in pads:
        for trace in traces:
            if trace.get('net_id') == pad.get('net_id'):
                path = _teardrop_for_pad_via(pad, trace, radius_factor)
                if path and len(path) >= 2:
                    board['teardrops'].append({
                        'pad_id_or_via_id': pad.get('pcb_pad_id'),
                        'trace_id': trace.get('pcb_trace_id'),
                        'radius_factor': radius_factor,
                        'path': path
                    })

    for via in vias:
        for trace in traces:
            if trace.get('net_id') == via.get('net_id'):
                path = _teardrop_for_pad_via(via, trace, radius_factor)
                if path and len(path) >= 2:
                    board['teardrops'].append({
                        'pad_id_or_via_id': via.get('pcb_via_id'),
                        'trace_id': trace.get('pcb_trace_id'),
                        'radius_factor': radius_factor,
                        'path': path
                    })

    return ok_payload({'circuit_json': circuit})


@register(REMOVE_VIA_STITCHING_SPEC, write=True)
async def remove_via_stitching(ctx, args):
    try:
        a = json.loads(args)
    except Exception:
        return err_payload("Invalid JSON", "PARSE_ERROR")

    circuit = a.get('circuit_json')
    pour_id = a.get('pour_id')

    if not circuit or not pour_id:
        return err_payload("Missing required fields", "BAD_ARGS")

    import copy
    circuit = copy.deepcopy(circuit)

    # T-536: canonical flat Circuit-JSON array — undo via `pcb_via_stitching`
    # metadata elements rather than a nested board dict.
    if isinstance(circuit, list):
        remove_ids = set()
        for e in circuit:
            if isinstance(e, dict) and e.get('type') == 'pcb_via_stitching' and e.get('pour_id') == pour_id:
                remove_ids.update(e.get('via_ids', []))
        circuit = [
            e for e in circuit
            if not (isinstance(e, dict) and e.get('type') == 'pcb_via' and e.get('pcb_via_id') in remove_ids)
            and not (isinstance(e, dict) and e.get('type') == 'pcb_via_stitching' and e.get('pour_id') == pour_id)
        ]
        return ok_payload({'circuit_json': circuit})

    # ── Shim: legacy `{'pcb_board': {'via_stitching': [...]}}` shape (T-536) ──
    board = circuit.get('pcb_board') or circuit.get('board')
    if not board:
        return err_payload("No pcb_board found", "BAD_ARGS")

    if 'via_stitching' in board:
        board['via_stitching'] = [vs for vs in board['via_stitching'] if vs.get('pour_id') != pour_id]

    return ok_payload({'circuit_json': circuit})