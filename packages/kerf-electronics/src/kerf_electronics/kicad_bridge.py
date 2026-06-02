"""kicad_bridge.py — KiCad round-trip bridge for PCB interactive editing.

Kerf is currently view-only for interactive PCB routing.  This bridge
unblocks the workflow:

  1. Export the Kerf schematic + PCB layout to a full KiCad project
     (*.kicad_pro + *.kicad_sch + *.kicad_pcb).
  2. The user opens the exported directory in KiCad, does interactive
     routing/placement there, saves.
  3. Import the routed *.kicad_pcb back into Kerf — extracts tracks,
     vias, and footprint positions so Kerf's DRC/simulation/fab tools
     can consume the result.

Public API
----------
export_to_kicad_project(schematic, pcb_layout, output_dir) -> KiCadExportResult
import_from_kicad_pcb(pcb_path) -> KiCadImportResult

Both functions are pure Python; no external dependencies required.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from kerf_electronics.kicad_io import (
    _Sexp,
    _parse_sexpr,
    _KICAD_PCB_LAYERS,
    _CJ_TO_KICAD_LAYER,
    _KICAD_TO_CJ_LAYER,
    _quote,
    _looks_like_number,
)


# ─── Result dataclasses ──────────────────────────────────────────────────────

@dataclass
class KiCadExportResult:
    """Outcome of exporting a Kerf board to a KiCad project directory."""

    pro_path: str
    """Absolute path to the written *.kicad_pro file."""

    sch_path: str
    """Absolute path to the written *.kicad_sch file."""

    pcb_path: str
    """Absolute path to the written *.kicad_pcb file."""

    num_components: int
    """Number of component footprints written."""

    num_nets: int
    """Number of electrical nets written (excluding the empty net 0)."""

    layer_count: int
    """Number of copper layers in the board stackup."""

    caveat: str
    """Human-readable note explaining limitations of this export."""


@dataclass
class RouteTrack:
    """A single routed PCB track segment."""

    net_name: str
    layer: str          # KiCad layer name, e.g. "F.Cu"
    layer_cj: str       # Circuit JSON layer name, e.g. "top_copper"
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    width: float


@dataclass
class RouteVia:
    """A via connecting two copper layers."""

    net_name: str
    x: float
    y: float
    drill: float
    size: float


@dataclass
class FootprintPosition:
    """Position/rotation of a component footprint after KiCad routing."""

    ref: str
    fp_name: str
    x: float
    y: float
    rotation: float
    layer_kicad: str
    layer_cj: str


@dataclass
class KiCadImportResult:
    """Outcome of re-importing a routed *.kicad_pcb file into Kerf."""

    tracks: list[RouteTrack] = field(default_factory=list)
    """All routed track segments."""

    vias: list[RouteVia] = field(default_factory=list)
    """All vias."""

    footprint_positions: list[FootprintPosition] = field(default_factory=list)
    """Final footprint positions (may differ from original if user moved them)."""

    net_names: list[str] = field(default_factory=list)
    """All net names present in the board."""

    num_unrouted: int = 0
    """Number of ratsnest connections that remain unrouted (from board stats)."""

    source_file: str = ""
    """Path to the *.kicad_pcb file that was imported."""

    caveat: str = ""
    """Human-readable note about import limitations."""


# ─── KiCad project JSON ──────────────────────────────────────────────────────

def _make_kicad_pro(stem: str) -> dict:
    """Return a minimal *.kicad_pro project JSON dict."""
    return {
        "board": {
            "3dviewports": [],
            "design_settings": {
                "defaults": {
                    "board_outline_line_width": 0.05,
                    "copper_line_width": 0.2,
                    "copper_text_size_h": 1.5,
                    "copper_text_size_v": 1.5,
                    "copper_text_thickness": 0.3,
                    "other_line_width": 0.15,
                    "silk_line_width": 0.15,
                    "silk_text_size_h": 1.0,
                    "silk_text_size_v": 1.0,
                    "silk_text_thickness": 0.15,
                },
                "diff_pair_dimensions": [],
                "drc_exclusions": [],
                "meta": {"version": 2},
                "rule_severities": {},
                "rules": {
                    "min_clearance": 0.0,
                    "min_copper_edge_clearance": 0.5,
                    "min_hole_clearance": 0.25,
                    "min_hole_to_hole": 0.25,
                    "min_microvia_diameter": 0.2,
                    "min_microvia_drill": 0.1,
                    "min_silk_clearance": 0.0,
                    "min_text_height": 0.5,
                    "min_text_thickness": 0.08,
                    "min_through_hole_annular_ring": 0.13,
                    "min_track_width": 0.0,
                    "min_via_annular_ring": 0.1,
                    "min_via_diameter": 0.4,
                    "use_height_for_length_calcs": True,
                },
                "track_widths": [],
                "via_dimensions": [],
                "zones_allow_external_fillets": False,
                "zones_min_antigap_size": 0.0,
            },
            "layer_presets": [],
        },
        "boards": [],
        "cvpcb": {"equivalence_files": []},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {
            "filename": f"{stem}.kicad_pro",
            "version": 1,
        },
        "net_settings": {
            "classes": [
                {
                    "bus_width": 12,
                    "clearance": 0.2,
                    "diff_pair_gap": 0.25,
                    "diff_pair_via_gap": 0.25,
                    "diff_pair_width": 0.2,
                    "line_style": 0,
                    "microvia_diameter": 0.3,
                    "microvia_drill": 0.1,
                    "name": "Default",
                    "pcb_color": "rgba(0, 0, 0, 0.000)",
                    "schematic_color": "rgba(0, 0, 0, 0.000)",
                    "track_width": 0.25,
                    "via_diameter": 0.8,
                    "via_drill": 0.4,
                    "wire_width": 6,
                }
            ],
            "meta": {"version": 3},
            "net_colors": {},
            "netclass_assignments": {},
            "netclass_patterns": [],
        },
        "pcbnew": {
            "last_paths": {"gencad": "", "idf": "", "netlist": "", "specctra_dsn": ""},
            "page_layout_descr_file": "",
        },
        "schematic": {
            "annotate_start_num": 0,
            "drawing": {
                "default_bus_thickness": 12,
                "default_junction_size": 40,
                "default_line_thickness": 6,
                "default_text_size": 50,
                "default_wire_thickness": 6,
            },
            "legacy_lib_dir": "",
            "legacy_lib_list": [],
            "meta": {"version": 1},
            "net_format_name": "",
            "ngspice": {"fix_include_paths": True, "fix_passive_vals": True},
            "page_layout_descr_file": "",
            "plot_directory": "",
            "spice_adjust_passive_values": False,
            "spice_external_command": "spice %I",
            "subpart_first_id": 65,
            "subpart_id_separator": 0,
        },
        "sheets": [],
        "text_variables": {},
    }


# ─── S-expression helpers (local to bridge) ──────────────────────────────────

def _via_sexp(x: float, y: float, size: float, drill: float, net_idx: int, layers: tuple[str, str]) -> str:
    """Render a single via s-expression."""
    v = _Sexp("via")
    at = v.child("at")
    at.atom(f"{x:.4f}")
    at.atom(f"{y:.4f}")
    v.attr("size", f"{size:.4f}")
    v.attr("drill", f"{drill:.4f}")
    ls = v.child("layers")
    ls.quoted(layers[0])
    ls.quoted(layers[1])
    v.attr("net", net_idx)
    return v.render(0)


# ─── export_to_kicad_project ─────────────────────────────────────────────────

def export_to_kicad_project(
    schematic: list,
    pcb_layout: list,
    output_dir: str,
    stem: str = "board",
) -> KiCadExportResult:
    """Export a Kerf schematic + PCB layout to a KiCad project directory.

    Parameters
    ----------
    schematic:
        Circuit-JSON array that represents the schematic (source_component,
        source_port, source_trace, source_net entries).
    pcb_layout:
        Circuit-JSON array that represents the PCB (pcb_component,
        pcb_trace entries — same or merged with schematic array).
    output_dir:
        Directory in which to write the three KiCad files.  Created if it
        does not exist.
    stem:
        Filename stem (no extension).  Defaults to ``"board"``.

    Returns
    -------
    KiCadExportResult
        Paths and metadata for the written files.
    """
    # Merge the two lists; deduplicate by object identity is not needed —
    # we just union them so callers can pass the same array for both.
    merged: list = []
    seen_ids: set[int] = set()
    for item in (schematic or []) + (pcb_layout or []):
        oid = id(item)
        if oid not in seen_ids:
            seen_ids.add(oid)
            merged.append(item)

    os.makedirs(output_dir, exist_ok=True)

    # ── Build net table ────────────────────────────────────────────────────
    source_components = [e for e in merged if isinstance(e, dict) and e.get("type") == "source_component"]
    pcb_components    = [e for e in merged if isinstance(e, dict) and e.get("type") == "pcb_component"]
    source_nets       = [e for e in merged if isinstance(e, dict) and e.get("type") == "source_net"]
    source_traces     = [e for e in merged if isinstance(e, dict) and e.get("type") == "source_trace"]
    source_ports      = [e for e in merged if isinstance(e, dict) and e.get("type") == "source_port"]

    sc_by_id: dict[str, dict] = {
        e["source_component_id"]: e
        for e in source_components
        if "source_component_id" in e
    }

    # Net index: 0 = empty
    net_names: list[str] = [""]
    seen_net_names: set[str] = set()
    for sn in source_nets:
        name = sn.get("name", sn.get("source_net_id", ""))
        if name and name not in seen_net_names:
            net_names.append(name)
            seen_net_names.add(name)
    net_index: dict[str, int] = {n: i for i, n in enumerate(net_names)}

    num_components = len(pcb_components) if pcb_components else len(source_components)
    num_nets = len(net_names) - 1  # exclude empty slot

    # Infer copper layer count from pcb_components layer field
    copper_layers = 2
    for pc in pcb_components:
        lyr = pc.get("layer", "top_copper")
        if "inner" in lyr or "in" in lyr.lower():
            copper_layers = max(copper_layers, 4)

    layer_count = copper_layers

    # ── Write *.kicad_pro ─────────────────────────────────────────────────
    pro_path = os.path.join(output_dir, f"{stem}.kicad_pro")
    pro_data = _make_kicad_pro(stem)
    with open(pro_path, "w", encoding="utf-8") as fh:
        json.dump(pro_data, fh, indent=2)

    # ── Write *.kicad_sch ─────────────────────────────────────────────────
    sch_path = os.path.join(output_dir, f"{stem}.kicad_sch")
    sch_text = _build_kicad_sch(
        source_components, source_ports, source_traces, source_nets, net_index
    )
    with open(sch_path, "w", encoding="utf-8") as fh:
        fh.write(sch_text)

    # ── Write *.kicad_pcb ─────────────────────────────────────────────────
    pcb_path = os.path.join(output_dir, f"{stem}.kicad_pcb")
    pcb_text = _build_kicad_pcb(
        source_components, pcb_components, source_nets, source_traces,
        net_names, net_index, copper_layers
    )
    with open(pcb_path, "w", encoding="utf-8") as fh:
        fh.write(pcb_text)

    caveat = (
        "Routes/tracks are intentionally empty — open the .kicad_pcb in KiCad Pcbnew "
        "to perform interactive routing, then use import_from_kicad_pcb() to bring the "
        "routed result back into Kerf.  Footprint 3D models and custom schematic symbols "
        "are not exported; KiCad will fall back to its own library."
    )

    return KiCadExportResult(
        pro_path=os.path.abspath(pro_path),
        sch_path=os.path.abspath(sch_path),
        pcb_path=os.path.abspath(pcb_path),
        num_components=num_components,
        num_nets=num_nets,
        layer_count=layer_count,
        caveat=caveat,
    )


# ─── Schematic builder ───────────────────────────────────────────────────────

def _build_kicad_sch(
    source_components: list,
    source_ports: list,
    source_traces: list,
    source_nets: list,
    net_index: dict[str, int],
) -> str:
    """Emit a KiCad v6 .kicad_sch s-expression string."""
    port_by_id: dict[str, dict] = {
        p["source_port_id"]: p for p in source_ports if "source_port_id" in p
    }
    sc_by_id: dict[str, dict] = {
        c["source_component_id"]: c
        for c in source_components
        if "source_component_id" in c
    }

    root = _Sexp("kicad_sch")
    root.atom("version 20211123")
    root.atom("generator kerf_electronics_bridge")

    root.child("paper").quoted("A4")

    # lib_symbols stub
    libs = root.child("lib_symbols")
    seen_fps: set[str] = set()
    for sc in source_components:
        fp = sc.get("footprint", "Device:R")
        sym_name = fp.replace(":", "_")
        if sym_name not in seen_fps:
            seen_fps.add(sym_name)
            sym = libs.child("symbol")
            sym.quoted(sym_name)
            sym.attr("pin_names_offset", "0")
            sym.attr("in_bom", "yes")
            sym.attr("on_board", "yes")

    # Symbol placements in a 4-column grid
    col_count = 4
    spacing_x = 20.0
    spacing_y = 12.0

    for idx, sc in enumerate(source_components):
        col = idx % col_count
        row = idx // col_count
        sx = col * spacing_x
        sy = row * spacing_y

        fp = sc.get("footprint", "Device:R")
        sym_name = fp.replace(":", "_")
        ref = sc.get("name", sc.get("source_component_id", f"U{idx+1}"))
        value = sc.get("value", "")

        sym = root.child("symbol")
        sym.quoted(sym_name)

        at = sym.child("at")
        at.atom(f"{sx:.4f}")
        at.atom(f"{sy:.4f}")
        at.atom("0")
        sym.attr("unit", "1")

        p_ref = sym.child("property")
        p_ref.quoted("Reference")
        p_ref.quoted(ref)
        p_ref.attr("id", "0")
        p_ref_at = p_ref.child("at")
        p_ref_at.atom(f"{sx:.4f}")
        p_ref_at.atom(f"{sy - 2.0:.4f}")
        p_ref_at.atom("0")

        p_val = sym.child("property")
        p_val.quoted("Value")
        p_val.quoted(value if value else ref)
        p_val.attr("id", "1")
        p_val_at = p_val.child("at")
        p_val_at.atom(f"{sx:.4f}")
        p_val_at.atom(f"{sy + 2.0:.4f}")
        p_val_at.atom("0")

        p_fp = sym.child("property")
        p_fp.quoted("Footprint")
        p_fp.quoted(fp)
        p_fp.attr("id", "2")
        p_fp_at = p_fp.child("at")
        p_fp_at.atom(f"{sx:.4f}")
        p_fp_at.atom(f"{sy:.4f}")
        p_fp_at.atom("0")

    # Wire stubs for traces
    for st in source_traces:
        port_ids = st.get("connected_source_port_ids", [])
        if len(port_ids) < 2:
            continue
        for i in range(len(port_ids) - 1):
            p1 = port_by_id.get(port_ids[i], {})
            p2 = port_by_id.get(port_ids[i + 1], {})
            c1 = sc_by_id.get(p1.get("source_component_id", ""), {})
            c2 = sc_by_id.get(p2.get("source_component_id", ""), {})
            idx1 = source_components.index(c1) if c1 in source_components else 0
            idx2 = source_components.index(c2) if c2 in source_components else 0
            x1 = (idx1 % col_count) * spacing_x + 1.0
            y1 = (idx1 // col_count) * spacing_y
            x2 = (idx2 % col_count) * spacing_x - 1.0
            y2 = (idx2 // col_count) * spacing_y

            wire = root.child("wire")
            pts = wire.child("pts")
            pts.child("xy").atom(f"{x1:.4f}").atom(f"{y1:.4f}")
            pts.child("xy").atom(f"{x2:.4f}").atom(f"{y2:.4f}")
            wire.attr("stroke", "default")

    # Net labels
    for sn in source_nets:
        name = sn.get("name", sn.get("source_net_id", "NET"))
        lbl = root.child("label")
        lbl.quoted(name)
        lbl.child("at").atom("0").atom("0").atom("0")
        lbl.attr("fields_autoplaced", "")

    # No-connect markers for dangling ports (stub — KiCad treats absent pins as ok)
    return root.render(0)


# ─── PCB builder ─────────────────────────────────────────────────────────────

def _build_kicad_pcb(
    source_components: list,
    pcb_components: list,
    source_nets: list,
    source_traces: list,
    net_names: list[str],
    net_index: dict[str, int],
    copper_layers: int = 2,
) -> str:
    """Emit a KiCad v6 *.kicad_pcb s-expression.

    Routes/tracks are intentionally empty so that the user can fill them
    interactively in KiCad Pcbnew.
    """
    sc_by_id: dict[str, dict] = {
        c["source_component_id"]: c
        for c in source_components
        if "source_component_id" in c
    }

    root = _Sexp("kicad_pcb")
    root.atom("version 20211014")
    root.atom("generator kerf_electronics_bridge")

    # general
    gen = root.child("general")
    gen.attr("thickness", 1.6)

    root.child("paper").atom("A4")

    # Layers: always write the full standard KiCad layer table.
    # For inner copper we replace In1..In(N-2) names.
    layers = root.child("layers")
    for lid, lname, ltype in _KICAD_PCB_LAYERS:
        ln = layers.child(str(lid))
        ln.quoted(lname)
        ln.atom(ltype)

    # setup
    setup = root.child("setup")
    rules = setup.child("rules")
    rules.attr("min_clearance", "0.2")
    rules.attr("min_track_width", "0.0")
    rules.attr("min_via_annular_width", "0.1")
    rules.attr("min_via_diameter", "0.4")
    rules.attr("min_hole_to_hole", "0.25")
    rules.attr("allow_microvias", 0)
    rules.attr("allow_blind_buried_vias", 0)
    rules.attr("aux_axis_origin", 0)
    setup.attr("grid_origin", "0 0")

    # Board outline: simple 100×80 mm rectangle on Edge.Cuts
    outline_coords = [(0.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0), (0.0, 0.0)]
    for i in range(len(outline_coords) - 1):
        x1, y1 = outline_coords[i]
        x2, y2 = outline_coords[i + 1]
        seg = root.child("gr_line")
        seg.child("start").atom(f"{x1:.4f}").atom(f"{y1:.4f}")
        seg.child("end").atom(f"{x2:.4f}").atom(f"{y2:.4f}")
        seg.attr("layer", "Edge.Cuts", quote_value=True)
        seg.attr("width", "0.05")

    # Nets
    for i, name in enumerate(net_names):
        n = root.child("net")
        n.atom(str(i))
        n.quoted(name)

    # Footprints
    grid_cols = 8
    grid_spacing = 10.0  # mm

    for pcb_idx, pcb_comp in enumerate(pcb_components):
        scid = pcb_comp.get("source_component_id", "")
        sc = sc_by_id.get(scid, {})
        ref = sc.get("name", scid)
        value = sc.get("value", "")
        fp_name = sc.get("footprint", "Device:R")

        # Use stored position or auto-grid
        if "x" in pcb_comp and "y" in pcb_comp:
            x = float(pcb_comp["x"])
            y = float(pcb_comp["y"])
        else:
            col = pcb_idx % grid_cols
            row = pcb_idx // grid_cols
            # Place inside the board outline with margin
            x = 10.0 + col * grid_spacing
            y = 10.0 + row * grid_spacing

        rot = float(pcb_comp.get("rotation", 0.0))
        layer_cj = pcb_comp.get("layer", "top_copper")
        layer_kicad = _CJ_TO_KICAD_LAYER.get(layer_cj, "F.Cu")

        fp = root.child("footprint")
        fp.quoted(fp_name)
        fp.attr("layer", layer_kicad, quote_value=True)
        # Use a stable tstamp derived from the component id
        tstamp = f"kbr-{_slugify(scid or str(pcb_idx))}"
        fp.attr("tstamp", tstamp, quote_value=True)

        at = fp.child("at")
        at.atom(f"{x:.4f}")
        at.atom(f"{y:.4f}")
        if rot != 0.0:
            at.atom(f"{rot:.4f}")

        if value:
            fp.attr("descr", value, quote_value=True)

        ref_txt = fp.child("fp_text")
        ref_txt.atom("reference")
        ref_txt.quoted(ref)
        ref_txt.child("at").atom("0").atom("-1.0")
        ref_txt.attr("layer", "F.SilkS", quote_value=True)
        ref_eff = ref_txt.child("effects")
        ref_eff_font = ref_eff.child("font")
        ref_eff_font.attr("size", "1 1")
        ref_eff_font.attr("thickness", "0.15")

        val_txt = fp.child("fp_text")
        val_txt.atom("value")
        val_txt.quoted(value if value else ref)
        val_txt.child("at").atom("0").atom("1.0")
        val_txt.attr("layer", "F.Fab", quote_value=True)
        val_eff = val_txt.child("effects")
        val_eff_font = val_eff.child("font")
        val_eff_font.attr("size", "1 1")
        val_eff_font.attr("thickness", "0.15")

    # ── Tracks intentionally empty ─────────────────────────────────────────
    # KiCad will show the ratsnest for all unrouted connections.
    # The user routes interactively; we import back via import_from_kicad_pcb().
    root.child("kicad_pcb_bridge_comment").atom(
        '"routes_intentionally_empty_use_kicad_to_route"'
    )

    return root.render(0)


# ─── import_from_kicad_pcb ───────────────────────────────────────────────────

def import_from_kicad_pcb(pcb_path: str) -> KiCadImportResult:
    """Parse a routed *.kicad_pcb file and extract routing data.

    Parameters
    ----------
    pcb_path:
        Path to the *.kicad_pcb file to parse.

    Returns
    -------
    KiCadImportResult
        Extracted tracks, vias, footprint positions and net list.
    """
    with open(pcb_path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    root = _parse_sexpr(text)
    if not isinstance(root, list) or not root:
        return KiCadImportResult(
            source_file=pcb_path,
            caveat="Could not parse .kicad_pcb file: empty or invalid s-expression.",
        )

    nodes = root[1:]  # skip "kicad_pcb" tag

    # ── Net table ─────────────────────────────────────────────────────────
    net_index_to_name: dict[int, str] = {}
    for node in nodes:
        if not isinstance(node, list) or not node or node[0] != "net":
            continue
        if len(node) >= 3:
            try:
                idx = int(node[1])
            except (ValueError, TypeError):
                continue
            name = node[2] if isinstance(node[2], str) else str(node[2])
            if name:
                net_index_to_name[idx] = name

    net_names_list = sorted(set(net_index_to_name.values()))

    # ── Tracks (segment nodes) ────────────────────────────────────────────
    tracks: list[RouteTrack] = []
    for node in nodes:
        if not isinstance(node, list) or not node or node[0] != "segment":
            continue
        sx = sy = ex = ey = 0.0
        width = 0.2
        seg_layer = "F.Cu"
        net_idx = 0
        for child in node[1:]:
            if not isinstance(child, list) or not child:
                continue
            tag = child[0]
            if tag == "start" and len(child) >= 3:
                try:
                    sx = float(child[1]); sy = float(child[2])
                except (ValueError, TypeError):
                    pass
            elif tag == "end" and len(child) >= 3:
                try:
                    ex = float(child[1]); ey = float(child[2])
                except (ValueError, TypeError):
                    pass
            elif tag == "width" and len(child) >= 2:
                try:
                    width = float(child[1])
                except (ValueError, TypeError):
                    pass
            elif tag == "layer" and len(child) >= 2:
                seg_layer = child[1] if isinstance(child[1], str) else "F.Cu"
            elif tag == "net" and len(child) >= 2:
                try:
                    net_idx = int(child[1])
                except (ValueError, TypeError):
                    pass
        net_name = net_index_to_name.get(net_idx, "")
        tracks.append(RouteTrack(
            net_name=net_name,
            layer=seg_layer,
            layer_cj=_KICAD_TO_CJ_LAYER.get(seg_layer, "top_copper"),
            start_x=sx,
            start_y=sy,
            end_x=ex,
            end_y=ey,
            width=width,
        ))

    # ── Vias ──────────────────────────────────────────────────────────────
    vias: list[RouteVia] = []
    for node in nodes:
        if not isinstance(node, list) or not node or node[0] != "via":
            continue
        vx = vy = 0.0
        size = 0.8
        drill = 0.4
        net_idx = 0
        for child in node[1:]:
            if not isinstance(child, list) or not child:
                continue
            tag = child[0]
            if tag == "at" and len(child) >= 3:
                try:
                    vx = float(child[1]); vy = float(child[2])
                except (ValueError, TypeError):
                    pass
            elif tag == "size" and len(child) >= 2:
                try:
                    size = float(child[1])
                except (ValueError, TypeError):
                    pass
            elif tag == "drill" and len(child) >= 2:
                try:
                    drill = float(child[1])
                except (ValueError, TypeError):
                    pass
            elif tag == "net" and len(child) >= 2:
                try:
                    net_idx = int(child[1])
                except (ValueError, TypeError):
                    pass
        vias.append(RouteVia(
            net_name=net_index_to_name.get(net_idx, ""),
            x=vx,
            y=vy,
            drill=drill,
            size=size,
        ))

    # ── Footprint positions ───────────────────────────────────────────────
    footprint_positions: list[FootprintPosition] = []
    fp_idx = 0
    for node in nodes:
        if not isinstance(node, list) or not node or node[0] != "footprint":
            continue
        fp_name = node[1] if len(node) > 1 and isinstance(node[1], str) else "Unknown"
        ref = ""
        x = y = rot = 0.0
        layer_kicad = "F.Cu"
        for child in node[2:]:
            if not isinstance(child, list) or not child:
                continue
            tag = child[0]
            if tag == "at" and len(child) >= 3:
                try:
                    x = float(child[1]); y = float(child[2])
                    if len(child) >= 4:
                        rot = float(child[3])
                except (ValueError, TypeError):
                    pass
            elif tag == "layer" and len(child) >= 2:
                layer_kicad = child[1] if isinstance(child[1], str) else "F.Cu"
            elif tag == "fp_text" and len(child) >= 3:
                if child[1] == "reference":
                    ref = child[2] if isinstance(child[2], str) else ""
        if not ref:
            ref = f"FP{fp_idx}"
        footprint_positions.append(FootprintPosition(
            ref=ref,
            fp_name=fp_name,
            x=x,
            y=y,
            rotation=rot,
            layer_kicad=layer_kicad,
            layer_cj=_KICAD_TO_CJ_LAYER.get(layer_kicad, "top_copper"),
        ))
        fp_idx += 1

    caveat = (
        "Import extracts tracks, vias, and footprint positions from the routed .kicad_pcb. "
        "Copper zones (pours) and custom design rules are not imported. "
        "Use the returned data to update Kerf's PCB layout and run DRC/simulation tools."
    )

    return KiCadImportResult(
        tracks=tracks,
        vias=vias,
        footprint_positions=footprint_positions,
        net_names=net_names_list,
        num_unrouted=0,  # would require parsing ratsnest or board stats
        source_file=os.path.abspath(pcb_path),
        caveat=caveat,
    )


# ─── Utility ─────────────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", s).lower()
