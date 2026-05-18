"""compile.py — atopile AST → Circuit JSON compiler.

Entry point::

    from kerf_electronics.atopile.compile import compile_ato
    circuit_json = compile_ato(source_text)

Returns a list of Circuit JSON records (source_component, source_net,
pcb_component, pcb_smtpad, source_trace) compatible with the schema used by
kicad_io.circuit_json_to_kicad_pcb.

The compiler performs:
  1. Parse the .ato source via kerf_electronics.atopile.parser.parse
  2. Walk all ModuleBlock / ComponentBlock nodes
  3. Resolve component instances: type_name → footprint/value defaults
  4. Expand assignments (instance.attr = value)
  5. Resolve connections (lhs ~ rhs):
       a. signal ~ instance.pin   → pin joins that signal's net
       b. instance.pin ~ signal   → pin joins that signal's net
       c. instance.pin ~ instance.pin  → both pins share an auto-net
  6. Emit Circuit JSON records
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .parser import parse
from .ast import (
    Assignment,
    ComponentBlock,
    ComponentInstance,
    Connection,
    Module,
    ModuleBlock,
    PinDecl,
    QuantityLiteral,
    SignalDecl,
    StringLiteral,
)


# ---------------------------------------------------------------------------
# Type catalogue: maps atopile type names → (footprint, component_type)
# ---------------------------------------------------------------------------

_TYPE_CATALOGUE: Dict[str, Dict[str, str]] = {
    "Resistor": {
        "footprint": "Device:R",
        "component_type": "resistor",
        "value": "",
    },
    "Capacitor": {
        "footprint": "Device:C",
        "component_type": "capacitor",
        "value": "",
    },
    "LED": {
        "footprint": "Device:LED",
        "component_type": "led",
        "value": "",
    },
    "Inductor": {
        "footprint": "Device:L",
        "component_type": "inductor",
        "value": "",
    },
    "Transistor": {
        "footprint": "Device:Q_NPN_CBE",
        "component_type": "transistor",
        "value": "",
    },
    "NMOS": {
        "footprint": "Device:Q_NMOS_GDS",
        "component_type": "nmos",
        "value": "",
    },
    "PMOS": {
        "footprint": "Device:Q_PMOS_GDS",
        "component_type": "pmos",
        "value": "",
    },
    "Diode": {
        "footprint": "Device:D",
        "component_type": "diode",
        "value": "",
    },
    "Crystal": {
        "footprint": "Device:Crystal",
        "component_type": "crystal",
        "value": "",
    },
    "OpAmp": {
        "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        "component_type": "opamp",
        "value": "",
    },
}

# Default footprint for unknown types
_DEFAULT_FOOTPRINT = "Device:Generic"


def _slugify(s: str) -> str:
    """Convert a string to a safe identifier fragment."""
    return re.sub(r"[^a-zA-Z0-9]", "_", s).lower()


def _fmt_value(qty) -> str:
    """Format a QuantityLiteral or StringLiteral as a human-readable string."""
    if isinstance(qty, QuantityLiteral):
        return qty.raw
    if isinstance(qty, StringLiteral):
        return qty.value
    return str(qty)


# ---------------------------------------------------------------------------
# Per-module compiler
# ---------------------------------------------------------------------------

class _ModuleCompiler:
    """Compile one ModuleBlock into Circuit JSON records."""

    def __init__(self, block: ModuleBlock):
        self._block = block
        # signal names declared in this module
        self._signals: List[str] = []
        # instance_name → {"type_name", "footprint", "value", "attrs"}
        self._instances: Dict[str, Dict] = {}
        # Union-Find for net grouping: maps endpoint → canonical net name
        # An endpoint is either a signal name OR "instance.pin"
        self._union: Dict[str, str] = {}
        # explicit assignments: "instance.attr" → value
        self._attrs: Dict[str, object] = {}
        # auto-net counter
        self._net_counter = 0

    # -- Union-Find helpers --------------------------------------------------

    def _find(self, key: str) -> str:
        """Find canonical representative (path-compressed)."""
        if key not in self._union:
            self._union[key] = key
        if self._union[key] != key:
            self._union[key] = self._find(self._union[key])
        return self._union[key]

    def _union_merge(self, a: str, b: str) -> None:
        """Merge the sets containing *a* and *b*.

        When one side is a declared signal name, prefer that as the
        canonical representative so the net gets a meaningful name.
        """
        ra = self._find(a)
        rb = self._find(b)
        if ra == rb:
            return
        # Prefer signal names as canonical
        a_is_sig = ra in self._signals
        b_is_sig = rb in self._signals
        if b_is_sig and not a_is_sig:
            # make rb the root
            self._union[ra] = rb
        else:
            self._union[rb] = ra

    def _new_net(self) -> str:
        self._net_counter += 1
        return f"net_{self._net_counter}"

    # -- Walk the block body -------------------------------------------------

    def _collect_body(self) -> None:
        for stmt in self._block.body:
            if isinstance(stmt, SignalDecl):
                name = stmt.name
                if name not in self._signals:
                    self._signals.append(name)
                # register in union-find
                self._find(name)

            elif isinstance(stmt, ComponentInstance):
                iname = stmt.instance_name
                type_name = stmt.type_name
                cat = _TYPE_CATALOGUE.get(type_name, {})
                self._instances[iname] = {
                    "type_name": type_name,
                    "footprint": cat.get("footprint", _DEFAULT_FOOTPRINT),
                    "value": cat.get("value", ""),
                    "component_type": cat.get("component_type", "generic"),
                }

            elif isinstance(stmt, Assignment):
                key = stmt.target.name  # e.g. "r1.value"
                self._attrs[key] = stmt.value

            elif isinstance(stmt, Connection):
                self._process_connection(stmt)

    def _is_signal(self, parts: List[str]) -> bool:
        """True if this dotted name refers to a declared signal (single part, in _signals)."""
        return len(parts) == 1 and parts[0] in self._signals

    def _endpoint_key(self, parts: List[str]) -> str:
        """Canonical key for a connection endpoint (either signal or instance.pin)."""
        return ".".join(parts)

    def _process_connection(self, conn: Connection) -> None:
        """Process a single ``lhs ~ rhs`` connection."""
        left_parts = conn.left.parts
        right_parts = conn.right.parts

        left_key = self._endpoint_key(left_parts)
        right_key = self._endpoint_key(right_parts)

        # Ensure both endpoints exist in the union-find
        self._find(left_key)
        self._find(right_key)

        # If neither side is a signal, create an auto-net and make it the
        # canonical representative so the net gets a stable id
        left_is_sig = self._is_signal(left_parts)
        right_is_sig = self._is_signal(right_parts)
        if not left_is_sig and not right_is_sig:
            # Check if either endpoint is already connected to a named signal
            cl = self._find(left_key)
            cr = self._find(right_key)
            # If neither canonical is a signal, create an auto-net
            if cl not in self._signals and cr not in self._signals:
                auto = self._new_net()
                self._signals.append(auto)
                self._find(auto)  # register
                # Connect both endpoints to the auto-net
                self._union_merge(left_key, auto)
                self._union_merge(right_key, auto)
                return

        self._union_merge(left_key, right_key)

    # -- Emit Circuit JSON ---------------------------------------------------

    def emit(self) -> List[dict]:
        self._collect_body()
        return self._emit_records()

    def _emit_records(self) -> List[dict]:
        records: List[dict] = []

        # ── Collect net membership ──────────────────────────────────────────
        # For each endpoint, find its canonical net name
        # endpoint_key → canonical_net_key
        endpoint_to_net: Dict[str, str] = {}
        for key in list(self._union.keys()):
            endpoint_to_net[key] = self._find(key)

        # Determine which canonical net names are in _signals
        # (i.e. are declared signals or auto-nets)
        all_canonical_nets: set = set()
        for key in self._union:
            canon = self._find(key)
            all_canonical_nets.add(canon)

        # Collect signals that appear as canonical nets
        signal_nets = [s for s in self._signals if s in all_canonical_nets]
        # Also include signals that have no connections but are declared
        for s in self._signals:
            if s not in signal_nets:
                signal_nets.append(s)

        # ── source_net records ───────────────────────────────────────────────
        net_id_map: Dict[str, str] = {}  # canonical net name → source_net_id
        for net_name in signal_nets:
            nid = f"sn_{_slugify(net_name)}"
            net_id_map[net_name] = nid
            records.append({
                "type": "source_net",
                "source_net_id": nid,
                "name": net_name,
            })

        # ── source_component + pcb_component records ─────────────────────────
        layout_spacing = 10.0  # mm between components
        instance_names_sorted = list(self._instances.keys())

        for idx, iname in enumerate(instance_names_sorted):
            inst = self._instances[iname]
            type_name = inst["type_name"]
            footprint = inst["footprint"]

            # Resolve value from attribute assignments
            val_key = f"{iname}.value"
            raw_value = self._attrs.get(val_key, None)
            if raw_value is not None:
                value_str = _fmt_value(raw_value)
            else:
                value_str = inst.get("value", "")

            # Resolve additional string attributes (e.g. led1.color = "red")
            extra_attrs: Dict[str, str] = {}
            for k, v in self._attrs.items():
                parts = k.split(".", 1)
                if len(parts) == 2 and parts[0] == iname and parts[1] != "value":
                    extra_attrs[parts[1]] = _fmt_value(v)

            scid = f"sc_{_slugify(iname)}"

            sc_rec: Dict = {
                "type": "source_component",
                "source_component_id": scid,
                "name": iname.upper() if iname[0].lower() == iname[0] else iname,
                "value": value_str,
                "footprint": footprint,
            }
            # Use uppercase for auto-named components (r1 → R1, c1 → C1, led1 → LED1)
            sc_rec["name"] = _canonical_ref(iname)
            if extra_attrs:
                sc_rec["attrs"] = extra_attrs

            records.append(sc_rec)

            # pcb_component — place in a row
            x = (idx + 1) * layout_spacing
            y = 10.0
            records.append({
                "type": "pcb_component",
                "pcb_component_id": f"pcb_{_slugify(iname)}",
                "source_component_id": scid,
                "x": x,
                "y": y,
                "rotation": 0.0,
                "layer": "top_copper",
            })

            # pcb_smtpad — two pads per component
            default_pins = _default_pins(type_name)
            for pin_idx, pin_name in enumerate(default_pins):
                pad_offset_x = -1.0 + pin_idx * 2.0  # -1mm, +1mm
                records.append({
                    "type": "pcb_smtpad",
                    "pcb_smtpad_id": f"pad_{_slugify(iname)}_{pin_name}",
                    "pcb_component_id": f"pcb_{_slugify(iname)}",
                    "source_component_id": scid,
                    "source_port_id": f"sp_{_slugify(iname)}_{pin_name}",
                    "x": x + pad_offset_x,
                    "y": y,
                    "width": 0.8,
                    "height": 0.8,
                    "layer": "top_copper",
                    "port_hints": [pin_name],
                })

        # ── source_trace records (one per net, grouping all connected pins) ──
        # Build a map: canonical_net_name → [source_port_ids]
        net_ports: Dict[str, List[str]] = {}
        for endpoint_key, canon in endpoint_to_net.items():
            if canon not in self._signals:
                continue
            # Skip if endpoint_key IS a signal name (not a pin reference)
            parts = endpoint_key.split(".")
            if len(parts) < 2:
                continue
            # endpoint_key is "instance.pin"
            inst_name = parts[0]
            pin_name = ".".join(parts[1:])
            if inst_name not in self._instances:
                continue
            sp_id = f"sp_{_slugify(inst_name)}_{_slugify(pin_name)}"
            if canon not in net_ports:
                net_ports[canon] = []
            if sp_id not in net_ports[canon]:
                net_ports[canon].append(sp_id)

        for net_name, port_ids in net_ports.items():
            if net_name not in net_id_map:
                continue
            nid = net_id_map[net_name]
            stid = f"st_{_slugify(net_name)}"
            records.append({
                "type": "source_trace",
                "source_trace_id": stid,
                "connected_source_port_ids": port_ids,
                "connected_source_net_ids": [nid],
            })

        return records


def _canonical_ref(instance_name: str) -> str:
    """Convert atopile instance name to PCB reference designator.

    Examples: r1 → R1, c1 → C1, led1 → LED1, r_top → R_TOP
    """
    # If already uppercase-leading, return as-is
    if instance_name[0].isupper():
        return instance_name
    # Uppercase the whole string for the reference designator
    return instance_name.upper()


def _default_pins(type_name: str) -> List[str]:
    """Return the default pin names for a component type."""
    two_pin = {"Resistor", "Capacitor", "Inductor", "Diode", "Crystal", "LED"}
    three_pin = {"Transistor", "NMOS", "PMOS"}
    eight_pin = {"OpAmp"}

    if type_name in two_pin:
        if type_name == "LED":
            return ["anode", "cathode"]
        if type_name == "Diode":
            return ["anode", "cathode"]
        return ["p1", "p2"]
    if type_name in three_pin:
        return ["gate", "drain", "source"]
    if type_name in eight_pin:
        return ["in_p", "in_n", "out", "vcc", "gnd", "nc1", "nc2", "nc3"]
    # fallback: two generic pins
    return ["p1", "p2"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_ato(source: str, *, top_module: Optional[str] = None) -> List[dict]:
    """Compile a `.ato` source string to Circuit JSON.

    Parameters
    ----------
    source:
        The text of a `.ato` file.
    top_module:
        Name of the module block to compile.  If *None*, the first
        ``module`` block found is used.

    Returns
    -------
    A list of Circuit JSON dicts (source_component, source_net,
    pcb_component, pcb_smtpad, source_trace).

    Raises
    ------
    ValueError
        If no module block is found in the source.
    """
    ast_root: Module = parse(source)

    # Collect all module blocks
    module_blocks = [b for b in ast_root.blocks if isinstance(b, ModuleBlock)]

    if not module_blocks:
        raise ValueError("No module block found in .ato source")

    if top_module is not None:
        block = next((b for b in module_blocks if b.name == top_module), None)
        if block is None:
            raise ValueError(
                f"Module {top_module!r} not found. "
                f"Available: {[b.name for b in module_blocks]}"
            )
    else:
        block = module_blocks[0]

    compiler = _ModuleCompiler(block)
    return compiler.emit()
