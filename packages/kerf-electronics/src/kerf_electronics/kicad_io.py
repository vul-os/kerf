"""kicad_io.py — bidirectional bridge between Circuit JSON and KiCad v6/v7 format.

Public API
----------
circuit_json_to_kicad_pcb(circuit_json) -> str
    Emit a KiCad v6/v7 .kicad_pcb s-expression string — the inverse of
    `kicad_pcb_to_circuit_json` (T-527). Covers everything the reader below
    recovers: footprints (position/rotation/`locked`/`attr` flags),
    nets/traces, `pcb_via` (one-way — see the caveat in the function's own
    docstring), zones (`pcb_copper_pour` / `pcb_ground_plane` / `pcb_keepout`,
    incl. thermal reliefs and per-restriction keepout flags), `pcb_text` ->
    `gr_text`, and — the load-bearing piece — every `kicad_passthrough` /
    zone-level `_kicad_passthrough` node the reader retained verbatim,
    re-emitted so a second read recovers it again. Verified against both
    this module's own reader (self round-trip) and the independent
    `kicad-to-circuit-json` oracle re-reading the *written* file — see
    `tests/test_t527_kicad_writer.py`.

circuit_json_to_kicad_sch(circuit_json) -> str
    Emit a KiCad v6 .kicad_sch s-expression string.

kicad_pcb_to_circuit_json(text) -> dict
    Parse a .kicad_pcb string and return a Circuit-JSON list.
    Round-trip guarantee: component refs, net names, and footprint names
    survive a circuit_json → kicad_pcb → circuit_json cycle.
    Additionally recovers (T-526): copper zones as `pcb_copper_pour` (net-bound)
    or `pcb_ground_plane` (no-net fill), zone-level keepouts as `pcb_keepout`
    with per-restriction-type flags, free-floating `gr_text` as `pcb_text`,
    the `locked` flag on footprints/zones, and KiCad footprint `attr` flags.
    Anything else at the top level that this reader does not model (groups,
    dimensions, vias, other graphic items) is retained verbatim in a single
    `kicad_passthrough` entry so a future writer can re-emit it rather than
    silently losing it.
    T-538: applies the KiCad (Y-down) -> Circuit JSON (Y-up) axis flip once,
    over every emitted geometry path (component positions, trace routes,
    zone/keepout polygons, free-floating text) — see
    `_flip_kicad_y_to_circuit_json_y` for the axis rationale.

Parsing is pure Python plus `sexpdata` (BSD-2), a solid, general-purpose
S-expression parser — see `_parse_sexpr` below for why it's used the way it
is (T-526b: the hand-rolled lexer that filled this role through T-525/T-526
is retired in favor of it; the semantic mapping above the parser is
untouched).
"""

from __future__ import annotations

import re
from typing import Any

import sexpdata


# ─── S-expression parsing (sexpdata, configured for byte-for-byte fidelity) ───
#
# T-526b retires the ~90-line hand-rolled tokenizer/recursive-descent parser
# that used to live here in favor of `sexpdata`. The syntax `sexpdata` solves
# (balanced parens, quoted-string escaping) is genuinely stable and solved;
# there's no reason to maintain a bespoke one.
#
# The catch: `sexpdata.loads` is a *Lisp* reader by default — it coerces
# numeric-looking bare atoms to Python `int`/`float` and wraps everything
# else in `Symbol`, which (deliberately, per its own docstring) never
# compares equal to a plain `str`. The semantic layer above this module
# (T-526's zone/keepout/footprint reader, frozen and untouched by this
# change) does direct string comparisons and `isinstance(x, str)` checks
# against parsed atoms everywhere (`child[0] == "net"`, `tag == "locked"`,
# `keepout_settings.get(key) == "not_allowed"`, …) and expects every atom —
# numbers included — as the literal source text, exactly like the old
# tokenizer produced. Numeric coercion would also be a genuine passthrough
# hazard: KiCad often writes trailing-zero-padded coordinates
# (`"20.000000"`), and `str(float("20.000000"))` is `"20.0"` — a normalized
# re-emission would silently corrupt a value nobody asked to change.
#
# `_KicadRawParser` below neutralizes all of that while keeping sexpdata's
# actual parsing engine: every bare atom is kept as literal source text
# (`Symbol`, which *is* a `str` subclass — `isinstance(x, str)` holds — just
# never `==` to a plain `str` literal, which is why every atom is converted
# back to plain `str` on the way out via `_to_plain_tree`), brackets are
# restricted to `(`/`)` only (sexpdata's default also treats `[`/`]` as a
# delimiter pair; KiCad's format never does), and line-comment scanning is
# disabled (KiCad s-expressions have no comment syntax; a stray `;` inside a
# bare atom must never truncate a node — verified: no fixture in this repo
# contains one, but production KiCad files are not guaranteed to avoid it
# either). Verified by direct tree comparison against the old parser's
# output on every real fixture in this test suite: byte-for-byte identical.
#
# One known, narrow divergence, left as-is rather than replicated: the old
# tokenizer's quoted-string unescaping dropped the backslash for *any*
# `\X` sequence, even ones it didn't recognize (`\g` → `g`). `sexpdata`
# implements the standard C-style escape set (`\n`, `\t`, `\r`, `\b`, `\f`,
# `\"`, `\\`) and leaves anything else — including the backslash itself —
# untouched (`\g` → `\g`). Real KiCad output (pcbnew/eeschema's own writer)
# only ever emits `\"` and `\\`, where both implementations agree; the
# divergence is unreachable from genuine KiCad output and no fixture in this
# repo exercises it (checked: zero backslashes in any `.kicad_*` fixture).
# Adopting sexpdata's behavior here rather than replicating the old
# blanket-drop is a deliberate small improvement, not a shortcut.

class _KicadRawParser(sexpdata.Parser):
    """`sexpdata.Parser`, reconfigured to match the retired hand-rolled
    tokenizer's exact semantics — see the module-level note above."""

    def __init__(self, string: str):
        super().__init__(string, line_comment="\x00")
        # KiCad only ever uses ( ) — not sexpdata's default [ ] pair.
        self.brackets = {"(": ")"}
        self.closing_brackets = {")"}
        self._atom_end_basic = (
            set(self.brackets) | self.closing_brackets | {'"'} | set(sexpdata.whitespace)
        )
        self._atom_end_basic_or_escape_regexp = "|".join(
            re.escape(c) for c in (self._atom_end_basic | {"\\"})
        )
        self.atom_end = {self.line_comment} | self._atom_end_basic
        self.atom_end_or_escape_re = re.compile(
            "{0}|{1}".format(self._atom_end_basic_or_escape_regexp, re.escape(self.line_comment))
        )

    def atom(self, token: str):
        # Never coerce to int/float/nil/true/false — keep literal text.
        return sexpdata.Symbol(token)


def _to_plain_tree(node: Any) -> Any:
    """Recursively strip sexpdata's `Symbol` wrapper back to plain `str`,
    so the tree this module hands to the (untouched) semantic layer is
    exactly the nested-list-of-`str` shape the old hand-rolled parser
    produced."""
    if isinstance(node, list):
        return [_to_plain_tree(c) for c in node]
    if isinstance(node, sexpdata.Symbol):
        return str(node)
    return node  # already plain str (a quoted string) — unchanged


def _close_unbalanced_parens(text: str) -> str:
    """Append any closing parens *text* is missing.

    The retired hand-rolled recursive-descent parser never validated that
    parens balanced — it just stopped consuming tokens when it ran out, so
    a truncated/malformed `.kicad_pcb` (a real scenario: a corrupt upload, a
    write cut short) came back as a best-effort partial tree rather than a
    raised exception (`kicad_pcb_to_circuit_json` documents this — see
    `test_malformed_input_safe` / `test_malformed_kicad_pcb_safe`).
    `sexpdata` is stricter and raises `ExpectClosingBracket` on the same
    input. This closes the gap the same way rather than papering over it
    with a broad `except`: pad the missing `)` so the parse succeeds, which
    reproduces the old parser's output exactly on both existing malformed-
    input tests (verified). Parens inside quoted strings are not counted.
    """
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" and i + 1 < n else 1
            i += 1
        elif c == "(":
            depth += 1
            i += 1
        elif c == ")":
            depth -= 1
            i += 1
        else:
            i += 1
    return text + ")" * depth if depth > 0 else text


def _parse_sexpr(text: str) -> Any:
    """Parse a complete s-expression string. Returns the root node.

    Same contract as the retired hand-rolled parser: a nested list of plain
    `str` (or a bare `str` at the top level, or `[]` for empty input) — see
    the module-level note above for why sexpdata needs help to produce
    exactly this shape, and `_close_unbalanced_parens` for why truncated
    input doesn't raise.
    """
    top_level = _KicadRawParser(_close_unbalanced_parens(text)).parse()
    if not top_level:
        return []
    return _to_plain_tree(top_level[0])


# ─── Pure-Python S-expression emitter ─────────────────────────────────────────

def _quote(s: str) -> str:
    """Wrap *s* in double quotes, escaping internal backslash and quote chars."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class _Sexp:
    """Lightweight s-expression builder.

    Usage::

        s = _Sexp("kicad_pcb")
        s.attr("version", 20211014)
        with s.child("general") as g:
            g.attr("thickness", 1.6)
        print(s.render())
    """

    def __init__(self, tag: str, indent: int = 0):
        self._tag = tag
        self._indent = indent
        self._children: list[str | _Sexp] = []

    # ── fluent helpers ─────────────────────────────────────────────────────────

    def atom(self, value: str | int | float) -> "_Sexp":
        """Append a bare atom (unquoted) child."""
        self._children.append(str(value))
        return self

    def quoted(self, value: str) -> "_Sexp":
        """Append a quoted string atom."""
        self._children.append(_quote(value))
        return self

    def attr(self, key: str, value: str | int | float, quote_value: bool = False) -> "_Sexp":
        """Append  (key value)  inline."""
        if quote_value or isinstance(value, str) and not _looks_like_number(value):
            self._children.append(f"({key} {_quote(str(value))})")
        else:
            self._children.append(f"({key} {value})")
        return self

    def child(self, tag: str) -> "_Sexp":
        """Create and register a child _Sexp node; return it."""
        c = _Sexp(tag, self._indent + 2)
        self._children.append(c)
        return c

    # ── rendering ──────────────────────────────────────────────────────────────

    def render(self, indent: int | None = None) -> str:
        ind = self._indent if indent is None else indent
        prefix = " " * ind

        # Decide whether to render inline or multiline.
        # Inline when all children are atoms (no nested _Sexp).
        all_atoms = all(isinstance(c, str) for c in self._children)
        if all_atoms:
            inner = " ".join(self._children)
            if inner:
                return f"{prefix}({self._tag} {inner})"
            return f"{prefix}({self._tag})"

        # Multiline
        lines = [f"{prefix}({self._tag}"]
        for c in self._children:
            if isinstance(c, str):
                lines.append(f"{prefix}  {c}")
            else:
                lines.append(c.render(ind + 2))
        lines.append(f"{prefix})")
        return "\n".join(lines)


def _looks_like_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# ─── T-527: Circuit JSON (Y-up) → KiCad (Y-down) axis flip ────────────────────
#
# The exact inverse of `_flip_kicad_y_to_circuit_json_y` (see its docstring,
# far below, for the fixed-origin rationale settled by T-538/T-539): KiCad's
# `.kicad_pcb` is Y-down, Circuit JSON is Y-up, and the chosen convention is a
# fixed origin at y=0 — `kicad_y = -cj_y`, x untouched. Applied pointwise at
# each geometry-emitting site in the writer below (footprint `at`, segment/
# via endpoints, zone/keepout polygon vertices, `gr_text` `at`) rather than a
# whole-list pre-pass, since the writer builds its output incrementally
# per-element rather than transforming an already-complete list.
def _kicad_y(cj_y: Any) -> float:
    """`kicad_y = -cj_y` — the write-side half of the fixed-origin Y flip."""
    return -float(cj_y or 0.0)


# ─── T-527: raw-node re-emission (passthrough) ────────────────────────────────
#
# `kicad_pcb_to_circuit_json` retains every s-expression node it does not
# semantically model — either at the top level (`kicad_passthrough`) or
# nested inside a zone (`_kicad_passthrough`, e.g. `hatch`, `filled_polygon`)
# — as a plain Python nested list of `str` (see `_parse_sexpr`'s contract).
# The writer's job for those nodes is simply to print that same tree back out
# as text; `_render_raw_node` is the inverse of `_parse_sexpr`.
#
# One real limitation, inherent to the shape `_to_plain_tree` produces (see
# the module docstring above `_KicadRawParser`): whether a given atom was
# originally a *bare* symbol or a *quoted* string is not preserved — both
# collapse to plain `str`. So this renderer quotes an atom only when
# re-parsing would otherwise break (it contains whitespace, a paren, or a
# quote character, or is empty) rather than replicating the source file's
# original quoting choice byte-for-byte. That is sufficient for round-trip
# *value* equality (parsing the re-emitted text yields the same strings back
# out — the guarantee this module's tests hold it to) but not for
# byte-identical re-emission of already-bare-vs-quoted atoms that didn't need
# quoting either way (e.g. a bare UUID stays bare either way; a tag name
# stays bare). Documented here rather than silently assumed.

def _raw_atom_needs_quoting(s: str) -> bool:
    if s == "":
        return True
    return any(c.isspace() or c in "()\"" for c in s)


def _render_raw_atom(a: str) -> str:
    return _quote(a) if _raw_atom_needs_quoting(a) else a


def _render_raw_node(node: Any) -> str:
    """Render one passthrough node (a `_parse_sexpr`-shaped nested list of
    `str`, or a bare `str`) back into KiCad s-expression text."""
    if isinstance(node, list):
        if not node:
            return "()"
        parts = [_render_raw_node(child) for child in node]
        return "(" + " ".join(parts) + ")"
    return _render_raw_atom(str(node))


# ─── Circuit-JSON helpers ──────────────────────────────────────────────────────

def _by_type(circuit_json: list, *types: str) -> list[dict]:
    """Return all entries whose 'type' is in *types*."""
    type_set = set(types)
    return [e for e in (circuit_json or []) if isinstance(e, dict) and e.get("type") in type_set]


def _index_by(items: list[dict], key: str) -> dict[str, dict]:
    return {item[key]: item for item in items if key in item}


def _find_child(node: list, tag: str) -> list | None:
    """Return the first child of *node* (an s-expr list) whose tag matches, or None."""
    for child in node[1:]:
        if isinstance(child, list) and child and child[0] == tag:
            return child
    return None


def _parse_pts(pts_node: list) -> list[dict]:
    """Parse a KiCad `(pts (xy x y) (xy x y) ...)` node into [{x, y}, ...].

    KiCad v7 zone outlines can also carry `(arc (start ..)(mid ..)(end ..))`
    segments inside `pts`; those are approximated by their endpoint rather
    than tessellated, since Kerf's polygon shapes are straight-edge only.
    """
    points: list[dict] = []
    if not isinstance(pts_node, list):
        return points
    for child in pts_node[1:]:
        if not isinstance(child, list) or not child:
            continue
        if child[0] == "xy" and len(child) >= 3:
            try:
                points.append({"x": float(child[1]), "y": float(child[2])})
            except (ValueError, TypeError):
                continue
        elif child[0] == "arc":
            end = _find_child(child, "end")
            if end and len(end) >= 3:
                try:
                    points.append({"x": float(end[1]), "y": float(end[2])})
                except (ValueError, TypeError):
                    continue
    return points


# KiCad layer name mapping (Circuit JSON layer → KiCad canonical name)
_CJ_TO_KICAD_LAYER: dict[str, str] = {
    "top_copper":    "F.Cu",
    "bottom_copper": "B.Cu",
    "inner_1":       "In1.Cu",
    "inner_2":       "In2.Cu",
    "top_silkscreen": "F.SilkS",
    "bottom_silkscreen": "B.SilkS",
    "top_mask":      "F.Mask",
    "bottom_mask":   "B.Mask",
    "edge_cuts":     "Edge.Cuts",
}

_KICAD_TO_CJ_LAYER: dict[str, str] = {v: k for k, v in _CJ_TO_KICAD_LAYER.items()}

_KICAD_PCB_LAYERS = [
    (0,  "F.Cu",       "signal"),
    (1,  "In1.Cu",     "signal"),
    (2,  "In2.Cu",     "signal"),
    (31, "B.Cu",       "signal"),
    (32, "B.Adhes",    "user"),
    (33, "F.Adhes",    "user"),
    (34, "B.Paste",    "user"),
    (35, "F.Paste",    "user"),
    (36, "B.SilkS",    "user"),
    (37, "F.SilkS",    "user"),
    (38, "B.Mask",     "user"),
    (39, "F.Mask",     "user"),
    (40, "Dwgs.User",  "user"),
    (41, "Cmts.User",  "user"),
    (42, "Eco1.User",  "user"),
    (43, "Eco2.User",  "user"),
    (44, "Edge.Cuts",  "user"),
    (45, "Margin",     "user"),
    (46, "B.CrtYd",    "user"),
    (47, "F.CrtYd",    "user"),
    (48, "B.Fab",      "user"),
    (49, "F.Fab",      "user"),
]

# Top-level `.kicad_pcb` node tags with dedicated semantic handling in
# kicad_pcb_to_circuit_json, and ones that are purely structural/boilerplate
# (re-derived on write, not meaningfully "lost" on read). Anything else is
# swept into the `kicad_passthrough` bag — see below.
_KICAD_HANDLED_TOP_TAGS = {"net", "footprint", "segment", "zone", "gr_text"}
_KICAD_IGNORED_TOP_TAGS = {"version", "generator", "general", "paper", "layers", "setup", "host"}


# ─── circuit_json_to_kicad_pcb ─────────────────────────────────────────────────

def circuit_json_to_kicad_pcb(circuit_json: list) -> str:
    """Convert Circuit JSON to a KiCad v6/v7 .kicad_pcb s-expression string —
    the inverse of `kicad_pcb_to_circuit_json` (T-527).

    Covers, matching what the reader (T-526, frozen) recovers:
    - Standard layer table + setup block (structural boilerplate — the
      reader never models the original layer/setup content either, see
      `_KICAD_IGNORED_TOP_TAGS`, so re-deriving it here loses nothing)
    - Net declarations (net 0 = empty, then one per source_net / source_trace)
    - Footprints: position, rotation (T-538/T-539 Y-flip applied), `locked`,
      `kicad_footprint_attributes` (`attr` flags), ref/value text
    - PCB trace segments, net-indexed
    - `pcb_via` → `(via ...)` nodes (see the caveat below — this is a
      one-way convenience, not a round-trip-stable construct)
    - Zones: `pcb_copper_pour` / `pcb_ground_plane` / `pcb_keepout`, incl.
      thermal reliefs and per-restriction keepout flags
    - `pcb_text` → `gr_text`
    - `kicad_passthrough` / a zone's own `_kicad_passthrough` — every node
      the reader retained verbatim is re-emitted verbatim (see
      `_render_raw_node`), which is what makes read→write→read round-trip
      for constructs this module does not semantically model.

    **Known, honest limitations (not fixed here — the reader is frozen):**
    - Footprint internals the reader never captures at all — pads,
      silkscreen graphics, 3D model references — have no Circuit-JSON home
      and cannot be reconstructed. A written footprint contains only what
      `kicad_pcb_to_circuit_json` recovers: ref/value text, `at`, `layer`,
      `locked`, `attr`.
    - `pcb_via` is a one-way write: `kicad_pcb_to_circuit_json` does not
      model `(via ...)` as a first-class type (it falls into the top-level
      `kicad_passthrough` bag like any other unmodelled node), so a via
      written from a `pcb_via` Circuit JSON entry re-reads as inert
      passthrough content, not as `pcb_via` again. Provided anyway because
      it produces a well-formed, kicad-cli-openable board; just don't rely
      on it for `pcb_via` round-trip identity.
    - Multiple distinct `pcb_trace` entries that happen to share the same
      (net, layer, width) are merged into one on read (a pre-existing
      reader behavior, not introduced here) — writing them as separate
      segment runs does not undo that merge on the next read.
    """
    cj = circuit_json or []

    source_components = _by_type(cj, "source_component")
    pcb_components    = _by_type(cj, "pcb_component")
    source_nets       = _by_type(cj, "source_net")
    source_traces     = _by_type(cj, "source_trace")
    pcb_traces        = _by_type(cj, "pcb_trace")
    pcb_vias          = _by_type(cj, "pcb_via")
    pcb_zones         = _by_type(cj, "pcb_copper_pour", "pcb_ground_plane", "pcb_keepout")
    pcb_texts         = _by_type(cj, "pcb_text")
    passthrough_bags  = _by_type(cj, "kicad_passthrough")

    # Build component lookup: source_component_id → source_component
    sc_by_id = _index_by(source_components, "source_component_id")

    # ── Net table ─────────────────────────────────────────────────────────────
    # Collect unique net names.  Empty net is always index 0.
    net_names: list[str] = [""]   # index 0 = unconnected
    seen_nets: set[str] = set()
    for sn in source_nets:
        name = sn.get("name", sn["source_net_id"])
        if name not in seen_nets:
            net_names.append(name)
            seen_nets.add(name)
    # also harvest net names from traces that have no source_net entry
    for st in source_traces:
        for nid in st.get("connected_source_net_ids", []):
            # look up net name
            sn = next((n for n in source_nets if n.get("source_net_id") == nid), None)
            name = sn["name"] if sn and "name" in sn else nid
            if name not in seen_nets:
                net_names.append(name)
                seen_nets.add(name)
    net_index: dict[str, int] = {n: i for i, n in enumerate(net_names)}

    # ── Root node ─────────────────────────────────────────────────────────────
    root = _Sexp("kicad_pcb")
    # T-527: `version`/`generator` must be their own `(tag value)` nodes, not
    # one bare unparenthesized atom string — the old form parsed fine under
    # this module's own lenient reader (bare top-level atoms are simply
    # skipped, see `_KICAD_IGNORED_TOP_TAGS`'s `isinstance(node, list)`
    # guard) but is not valid KiCad grammar and made the independent oracle
    # (`kicadts`, via `kicad-to-circuit-json`) hard-fail with "unsupported
    # primitive child: version" on a written file. Fixed here so the writer's
    # output is actually oracle-parseable, which the round-trip DoD requires.
    root.child("version").atom("20211014")
    root.child("generator").quoted("kerf_electronics")

    # general
    gen = root.child("general")
    gen.attr("thickness", 1.6)

    # paper
    root.child("paper").quoted("A4")

    # layers
    layers = root.child("layers")
    for lid, lname, ltype in _KICAD_PCB_LAYERS:
        ln = layers.child(str(lid))
        ln.quoted(lname)
        ln.atom(ltype)

    # setup: kept minimal and flat (`grid_origin` only), not the old nested
    # `(rules ...)` wrapper T-527 removed — `setup` is purely structural
    # boilerplate to this module's own reader (`_KICAD_IGNORED_TOP_TAGS`,
    # never modelled either way) but the old `(rules ...)` form is not valid
    # KiCad grammar either: the independent oracle (`kicadts`) hard-fails
    # with `Class "rules" not registered` on it, since real `.kicad_pcb`
    # files place these settings as flat `setup` children, not nested under
    # a `rules` node. Matches the minimal, oracle-parseable form this
    # module's own hand-authored fixtures already use (see
    # `tests/fixtures/zones_keepout_board.kicad_pcb`).
    setup = root.child("setup")
    setup.child("grid_origin").atom("0").atom("0")

    # nets
    for i, name in enumerate(net_names):
        n = root.child("net")
        n.atom(str(i))
        n.quoted(name)

    # footprints
    for pcb_comp in pcb_components:
        scid = pcb_comp.get("source_component_id", "")
        sc = sc_by_id.get(scid, {})
        ref   = sc.get("name", scid)
        value = sc.get("value", "")
        fp_name = sc.get("footprint", "Device:R")
        x = float(pcb_comp.get("x", 0.0))
        y_kicad = _kicad_y(pcb_comp.get("y", 0.0))
        rot = float(pcb_comp.get("rotation", 0.0))
        layer_cj = pcb_comp.get("layer", "top_copper")
        layer_kicad = _CJ_TO_KICAD_LAYER.get(layer_cj, "F.Cu")

        fp = root.child("footprint")
        fp.quoted(fp_name)
        fp.attr("layer", layer_kicad, quote_value=True)
        if pcb_comp.get("locked"):
            fp.child("locked")
        # tstamp: preserve the CJ id verbatim so a re-read recovers the same
        # `pcb_component_id` (kicad_pcb_to_circuit_json uses `tstamp` as the
        # id whenever present) — a stable fallback otherwise.
        tstamp = pcb_comp.get("pcb_component_id") or f"fp_{scid}"
        fp.attr("tstamp", tstamp, quote_value=True)

        fp_attrs = pcb_comp.get("kicad_footprint_attributes")
        if fp_attrs is not None:
            attr_node = fp.child("attr")
            for flag in (
                "smd", "through_hole", "exclude_from_pos_files",
                "exclude_from_bom", "allow_missing_courtyard", "board_only",
            ):
                if fp_attrs.get(flag):
                    attr_node.atom(flag)

        # at
        at = fp.child("at")
        at.atom(f"{x:.4f}")
        at.atom(f"{y_kicad:.4f}")
        if rot != 0.0:
            at.atom(f"{rot:.4f}")

        # description / tags from value
        if value:
            fp.attr("descr", value, quote_value=True)

        # reference text
        ref_txt = fp.child("fp_text")
        ref_txt.atom("reference")
        ref_txt.quoted(ref)
        ref_at = ref_txt.child("at")
        ref_at.atom("0")
        ref_at.atom("-1.0")
        ref_txt.attr("layer", "F.SilkS", quote_value=True)
        ref_eff = ref_txt.child("effects")
        ref_eff_font = ref_eff.child("font")
        ref_eff_font.attr("size", "1 1")
        ref_eff_font.attr("thickness", "0.15")

        # value text
        val_txt = fp.child("fp_text")
        val_txt.atom("value")
        val_txt.quoted(value if value else ref)
        val_at = val_txt.child("at")
        val_at.atom("0")
        val_at.atom("1.0")
        val_txt.attr("layer", "F.Fab", quote_value=True)
        val_eff = val_txt.child("effects")
        val_eff_font = val_eff.child("font")
        val_eff_font.attr("size", "1 1")
        val_eff_font.attr("thickness", "0.15")

    # segments (pcb_trace)
    for pt in pcb_traces:
        route = pt.get("route", [])
        width = float(pt.get("width", 0.2))
        layer_cj = pt.get("layer", "top_copper")
        layer_kicad = _CJ_TO_KICAD_LAYER.get(layer_cj, "F.Cu")

        # Determine net index from associated source_trace
        trace_net_index = 0
        st_id = pt.get("source_trace_id")
        if st_id:
            st = next((t for t in source_traces if t.get("source_trace_id") == st_id), None)
            if st:
                for nid in st.get("connected_source_net_ids", []):
                    sn = next((n for n in source_nets if n.get("source_net_id") == nid), None)
                    name = sn["name"] if sn and "name" in sn else nid
                    trace_net_index = net_index.get(name, 0)
                    break

        for i in range(len(route) - 1):
            p1 = route[i]
            p2 = route[i + 1]
            seg = root.child("segment")
            s = seg.child("start")
            s.atom(f"{float(p1['x']):.4f}")
            s.atom(f"{_kicad_y(p1['y']):.4f}")
            e = seg.child("end")
            e.atom(f"{float(p2['x']):.4f}")
            e.atom(f"{_kicad_y(p2['y']):.4f}")
            seg.attr("width", f"{width:.4f}")
            seg.attr("layer", layer_kicad, quote_value=True)
            seg.attr("net", trace_net_index)

    # ── vias (pcb_via → `(via ...)`) ─────────────────────────────────────────
    # See the module-level caveat above: this is a one-way convenience, not
    # a round-trip-stable construct — kicad_pcb_to_circuit_json never reads
    # `via` back as `pcb_via`.
    for via in pcb_vias:
        vx = float(via.get("x", 0.0))
        vy_kicad = _kicad_y(via.get("y", 0.0))
        size = float(via.get("outer_diameter", via.get("diameter", 0.8)))
        drill = float(via.get("drill_diameter", via.get("drill", 0.4)))
        via_net_name = via.get("net_id") or via.get("net_name") or ""
        via_net_index = net_index.get(via_net_name, 0)
        from_layer_kicad = _CJ_TO_KICAD_LAYER.get(via.get("from_layer", "top_copper"), "F.Cu")
        to_layer_kicad = _CJ_TO_KICAD_LAYER.get(via.get("to_layer", "bottom_copper"), "B.Cu")

        v = root.child("via")
        v_at = v.child("at")
        v_at.atom(f"{vx:.4f}")
        v_at.atom(f"{vy_kicad:.4f}")
        v.attr("size", f"{size:.4f}")
        v.attr("drill", f"{drill:.4f}")
        v_layers = v.child("layers")
        v_layers.quoted(from_layer_kicad)
        v_layers.quoted(to_layer_kicad)
        v.attr("net", via_net_index)

    # ── zones: pcb_copper_pour / pcb_ground_plane / pcb_keepout (T-527) ─────
    for zone_entry in pcb_zones:
        _write_zone_node(root, zone_entry)

    # ── free-floating board text (pcb_text → gr_text) ───────────────────────
    for text_idx, txt in enumerate(pcb_texts):
        text_val = txt.get("text", "")
        tx = float(txt.get("x", 0.0))
        ty_kicad = _kicad_y(txt.get("y", 0.0))
        layer_cj = txt.get("layer")
        layer_kicad = _CJ_TO_KICAD_LAYER.get(layer_cj, layer_cj) if layer_cj else "Cmts.User"
        if layer_kicad is None:
            layer_kicad = "Cmts.User"

        gt = root.child("gr_text")
        gt.quoted(text_val)
        gt_at = gt.child("at")
        gt_at.atom(f"{tx:.4f}")
        gt_at.atom(f"{ty_kicad:.4f}")
        gt_at.atom("0")
        gt.attr("layer", layer_kicad, quote_value=True)
        # kicad_pcb_to_circuit_json never reads a gr_text's own tstamp (its
        # `pcb_text_id` is always a fresh `text_{index}`, independent of any
        # tstamp in the source), so any stable value round-trips identically
        # here — but the KiCad grammar (and the oracle's stricter parser)
        # requires *some* tstamp/uuid child to be present.
        gt.attr("tstamp", txt.get("pcb_text_id") or f"text_{text_idx}", quote_value=True)
        if txt.get("locked"):
            gt.child("locked")
        gt_eff = gt.child("effects")
        gt_font = gt_eff.child("font")
        gt_font.attr("size", "1.5 1.5")
        gt_font.attr("thickness", "0.3")

    # ── passthrough: every top-level node the reader could not model,
    # re-emitted verbatim so it survives the round trip (T-527's whole
    # point — see the module docstring's passthrough section) ─────────────
    for bag in passthrough_bags:
        for raw_node in bag.get("kicad_nodes", []):
            root.atom(_render_raw_node(raw_node))

    return root.render(0)


# ─── T-527: zone/keepout writer — the inverse of `_parse_zone_node` ───────────

def _write_zone_node(root: "_Sexp", entry: dict) -> None:
    """Emit one `(zone ...)` node from a `pcb_copper_pour` / `pcb_ground_plane`
    / `pcb_keepout` Circuit-JSON dict — the exact inverse of
    `_parse_zone_node`. Any `_kicad_passthrough` children recorded on read
    (`hatch`, `filled_polygon`, `name`, ...) are re-emitted verbatim, in
    their originally-recorded relative order — that is what
    `_parse_zone_node` needs to recover an identical `_kicad_passthrough`
    list on the next read; *where* they sit relative to the modelled fields
    below does not matter, since each zone's passthrough list is rebuilt
    fresh from that zone's own children in file order.
    """
    etype = entry.get("type")
    zone = root.child("zone")

    if etype == "pcb_keepout":
        zone.attr("net", 0)
        zone.attr("net_name", "", quote_value=True)
    else:
        net_index_val = entry.get("net_index", 0)
        net_name = entry.get("net_id", "") if etype == "pcb_copper_pour" else ""
        zone.attr("net", net_index_val)
        zone.attr("net_name", net_name, quote_value=True)

    layer_cj = entry.get("layer")
    layer_kicad = _CJ_TO_KICAD_LAYER.get(layer_cj, layer_cj) if layer_cj else "F.Cu"
    if layer_kicad is None:
        layer_kicad = "F.Cu"
    zone.attr("layer", layer_kicad, quote_value=True)

    id_key = {
        "pcb_copper_pour": "pcb_copper_pour_id",
        "pcb_ground_plane": "pcb_ground_plane_id",
        "pcb_keepout": "pcb_keepout_id",
    }.get(etype, "")
    zone_id = entry.get(id_key) if id_key else None
    if zone_id:
        zone.attr("tstamp", zone_id, quote_value=True)

    if entry.get("locked"):
        zone.child("locked")

    for raw_child in entry.get("_kicad_passthrough", []):
        zone.atom(_render_raw_node(raw_child))

    if etype == "pcb_keepout":
        ko = zone.child("keepout")
        ko.child("tracks").atom("not_allowed" if entry.get("no_tracks") else "allowed")
        ko.child("vias").atom("not_allowed" if entry.get("no_vias") else "allowed")
        ko.child("pads").atom("not_allowed" if entry.get("no_pads") else "allowed")
        ko.child("copperpour").atom("not_allowed" if entry.get("no_copperpour") else "allowed")
        ko.child("footprints").atom("not_allowed" if entry.get("no_footprints") else "allowed")
        zone.child("fill").atom("no")
    else:
        if "priority" in entry:
            zone.attr("priority", entry["priority"])
        if "clearance_mm" in entry:
            cp = zone.child("connect_pads")
            cp.attr("clearance", entry["clearance_mm"])
        if "min_thickness_mm" in entry:
            zone.attr("min_thickness", entry["min_thickness_mm"])
        thermal = entry.get("thermal_relief") or {}
        fill = zone.child("fill")
        fill.atom("yes")
        if "gap" in thermal:
            fill.attr("thermal_gap", thermal["gap"])
        if "spoke_width" in thermal:
            fill.attr("thermal_bridge_width", thermal["spoke_width"])

    poly = zone.child("polygon")
    pts = poly.child("pts")
    for pt in entry.get("polygon", []):
        xy = pts.child("xy")
        xy.atom(f"{float(pt.get('x', 0.0)):.4f}")
        xy.atom(f"{_kicad_y(pt.get('y', 0.0)):.4f}")


# ─── circuit_json_to_kicad_sch ─────────────────────────────────────────────────

def circuit_json_to_kicad_sch(circuit_json: list) -> str:
    """Convert Circuit JSON to a KiCad v6 .kicad_sch s-expression string.

    Covers:
    - Standard schematic header (version, uuid)
    - lib_symbols section (one symbol per unique footprint)
    - symbol instances (one per source_component) with ref/value properties
    - Wire segments from source_traces
    - net_labels for source_nets
    """
    cj = circuit_json or []

    source_components = _by_type(cj, "source_component")
    source_ports      = _by_type(cj, "source_port")
    source_traces     = _by_type(cj, "source_trace")
    source_nets       = _by_type(cj, "source_net")

    sc_by_id = _index_by(source_components, "source_component_id")
    port_by_id = _index_by(source_ports, "source_port_id")

    # Net lookup: net_id → net_name
    net_by_id: dict[str, str] = {}
    for sn in source_nets:
        net_by_id[sn["source_net_id"]] = sn.get("name", sn["source_net_id"])

    root = _Sexp("kicad_sch")
    root.atom("version 20211123")
    root.atom("generator kerf_electronics")

    # Paper
    root.child("paper").quoted("A4")

    # lib_symbols — minimal stub entries
    libs = root.child("lib_symbols")
    seen_fps: set[str] = set()
    for sc in source_components:
        fp = sc.get("footprint", "Device:R")
        lib_sym_name = fp.replace(":", "_")
        if lib_sym_name not in seen_fps:
            seen_fps.add(lib_sym_name)
            sym = libs.child("symbol")
            sym.quoted(lib_sym_name)
            sym.attr("pin_names_offset", "0")
            sym.attr("in_bom", "yes")
            sym.attr("on_board", "yes")

    # Place symbols in a grid (4 columns, auto-increment y)
    col_count = 4
    spacing_x = 15.0
    spacing_y = 10.0

    for idx, sc in enumerate(source_components):
        col = idx % col_count
        row = idx // col_count
        sx = col * spacing_x
        sy = row * spacing_y

        fp = sc.get("footprint", "Device:R")
        lib_sym_name = fp.replace(":", "_")
        ref = sc.get("name", sc["source_component_id"])
        value = sc.get("value", "")

        sym = root.child("symbol")
        sym.quoted(lib_sym_name)

        at = sym.child("at")
        at.atom(f"{sx:.4f}")
        at.atom(f"{sy:.4f}")
        at.atom("0")

        sym.attr("unit", "1")

        # Reference property
        p_ref = sym.child("property")
        p_ref.quoted("Reference")
        p_ref.quoted(ref)
        p_ref.attr("id", "0")
        p_ref_at = p_ref.child("at")
        p_ref_at.atom(f"{sx:.4f}")
        p_ref_at.atom(f"{sy - 1.5:.4f}")
        p_ref_at.atom("0")

        # Value property
        p_val = sym.child("property")
        p_val.quoted("Value")
        p_val.quoted(value if value else ref)
        p_val.attr("id", "1")
        p_val_at = p_val.child("at")
        p_val_at.atom(f"{sx:.4f}")
        p_val_at.atom(f"{sy + 1.5:.4f}")
        p_val_at.atom("0")

        # Footprint property
        p_fp = sym.child("property")
        p_fp.quoted("Footprint")
        p_fp.quoted(fp)
        p_fp.attr("id", "2")
        p_fp_at = p_fp.child("at")
        p_fp_at.atom(f"{sx:.4f}")
        p_fp_at.atom(f"{sy:.4f}")
        p_fp_at.atom("0")

    # Wire stubs for traces (minimal — one wire per connected pair of ports)
    for st in source_traces:
        port_ids = st.get("connected_source_port_ids", [])
        if len(port_ids) < 2:
            continue
        # Simple: connect consecutive port pairs with wire stubs
        for i in range(len(port_ids) - 1):
            p1_id = port_ids[i]
            p2_id = port_ids[i + 1]
            p1 = port_by_id.get(p1_id, {})
            p2 = port_by_id.get(p2_id, {})
            # derive schematic positions from component positions
            c1 = sc_by_id.get(p1.get("source_component_id", ""), {})
            c2 = sc_by_id.get(p2.get("source_component_id", ""), {})
            idx1 = source_components.index(c1) if c1 in source_components else 0
            idx2 = source_components.index(c2) if c2 in source_components else 0
            x1 = (idx1 % col_count) * spacing_x + 0.5
            y1 = (idx1 // col_count) * spacing_y
            x2 = (idx2 % col_count) * spacing_x - 0.5
            y2 = (idx2 // col_count) * spacing_y

            wire = root.child("wire")
            pts = wire.child("pts")
            xy1 = pts.child("xy")
            xy1.atom(f"{x1:.4f}")
            xy1.atom(f"{y1:.4f}")
            xy2 = pts.child("xy")
            xy2.atom(f"{x2:.4f}")
            xy2.atom(f"{y2:.4f}")
            wire.attr("stroke", "default")

    # net_labels for source_nets
    for sn in source_nets:
        name = sn.get("name", sn["source_net_id"])
        lbl = root.child("label")
        lbl.quoted(name)
        lbl.child("at").atom("0").atom("0").atom("0")
        lbl.attr("fields_autoplaced", "")

    return root.render(0)


# ─── zone / keepout parsing (T-526) ────────────────────────────────────────────
#
# KiCad's `(zone ...)` node covers three Circuit-JSON-shaped concepts depending
# on its contents:
#   - a `(keepout ...)` child  -> `pcb_keepout` (rule area, no copper poured)
#   - a net-bound zone         -> `pcb_copper_pour` (Kerf's existing shape,
#                                  consumed by tools/pour.py, fab/gerber.py,
#                                  fab/odbpp/writer.py, src/lib/copperPour.js)
#   - a no-net catch-all zone  -> `pcb_ground_plane` (net index 0 / empty
#                                  net_name — KiCad's own signal for a
#                                  fill-everywhere plane rather than a
#                                  specific-net pour)
#
# Anything inside the zone this reader does not model (e.g. `filled_polygon`
# regions computed by KiCad's fill engine, `hatch`, `name`) is preserved
# verbatim under `_kicad_passthrough` on the emitted dict rather than dropped.

def _parse_zone_node(node: list, pour_idx: int, keepout_idx: int) -> dict:
    """Parse one `(zone ...)` s-expr node into a Circuit-JSON dict.

    Returns a `pcb_keepout`, `pcb_copper_pour`, or `pcb_ground_plane` dict.
    *pour_idx*/*keepout_idx* are only used to synthesize a stable id when the
    zone carries no `tstamp`/`uuid`.
    """
    net_idx = 0
    net_name = ""
    layer_kicad: str | None = None
    priority: int | None = None
    clearance_mm: float | None = None
    min_thickness_mm: float | None = None
    thermal_gap: float | None = None
    thermal_bridge_width: float | None = None
    locked = False
    keepout_settings: dict[str, str] | None = None
    outline_pts: list[dict] = []
    tstamp = ""
    passthrough: list = []

    for child in node[1:]:
        if not isinstance(child, list) or not child:
            if child == "locked":
                locked = True
            continue
        tag = child[0]

        if tag == "net" and len(child) >= 2:
            try:
                net_idx = int(child[1])
            except (ValueError, TypeError):
                pass
        elif tag == "net_name" and len(child) >= 2:
            net_name = child[1] if isinstance(child[1], str) else ""
        elif tag in ("layer", "layers") and len(child) >= 2:
            # `layers` (KiCad 7 multi-layer zone) — take the first; the rest
            # is preserved via passthrough below since we only model one.
            layer_kicad = child[1] if isinstance(child[1], str) else None
            if tag == "layers" and len(child) > 2:
                passthrough.append(child)
        elif tag == "priority" and len(child) >= 2:
            try:
                priority = int(child[1])
            except (ValueError, TypeError):
                pass
        elif tag == "locked":
            locked = True
        elif tag in ("tstamp", "uuid") and len(child) >= 2:
            tstamp = child[1] if isinstance(child[1], str) else ""
        elif tag == "connect_pads":
            clr = _find_child(child, "clearance")
            if clr and len(clr) >= 2:
                try:
                    clearance_mm = float(clr[1])
                except (ValueError, TypeError):
                    pass
        elif tag == "min_thickness" and len(child) >= 2:
            try:
                min_thickness_mm = float(child[1])
            except (ValueError, TypeError):
                pass
        elif tag == "keepout":
            keepout_settings = {}
            for ko_child in child[1:]:
                if isinstance(ko_child, list) and len(ko_child) >= 2:
                    keepout_settings[ko_child[0]] = ko_child[1]
        elif tag == "fill":
            for f_child in child[1:]:
                if not isinstance(f_child, list) or not f_child:
                    continue
                if f_child[0] == "thermal_gap" and len(f_child) >= 2:
                    try:
                        thermal_gap = float(f_child[1])
                    except (ValueError, TypeError):
                        pass
                elif f_child[0] == "thermal_bridge_width" and len(f_child) >= 2:
                    try:
                        thermal_bridge_width = float(f_child[1])
                    except (ValueError, TypeError):
                        pass
                else:
                    passthrough.append(f_child)
        elif tag == "polygon":
            pts_node = _find_child(child, "pts")
            if pts_node:
                outline_pts = _parse_pts(pts_node)
        else:
            # filled_polygon (computed fill regions), hatch, name, etc. — keep
            # verbatim rather than silently dropping.
            passthrough.append(child)

    layer_cj = _KICAD_TO_CJ_LAYER.get(layer_kicad, layer_kicad) if layer_kicad else None

    if keepout_settings is not None:
        def _not_allowed(key: str) -> bool:
            return keepout_settings.get(key) == "not_allowed"

        result: dict[str, Any] = {
            "type": "pcb_keepout",
            "pcb_keepout_id": tstamp or f"keepout_{keepout_idx}",
            "layer": layer_cj,
            "polygon": outline_pts,
            "shape": "polygon",
            "no_routing": _not_allowed("tracks"),
            "no_components": _not_allowed("footprints"),
            "no_tracks": _not_allowed("tracks"),
            "no_vias": _not_allowed("vias"),
            "no_pads": _not_allowed("pads"),
            "no_copperpour": _not_allowed("copperpour"),
            "no_footprints": _not_allowed("footprints"),
        }
    elif net_name:
        result = {
            "type": "pcb_copper_pour",
            "pcb_copper_pour_id": tstamp or f"pour_{pour_idx}",
            "layer": layer_cj,
            "net_id": net_name,
            "net_index": net_idx,
            "polygon": outline_pts,
        }
    else:
        result = {
            "type": "pcb_ground_plane",
            "pcb_ground_plane_id": tstamp or f"gndplane_{pour_idx}",
            "layer": layer_cj,
            "polygon": outline_pts,
        }

    if keepout_settings is None:
        # Fill settings only apply to copper pours / ground planes, not
        # keepouts (which never fill).
        if priority is not None:
            result["priority"] = priority
        if clearance_mm is not None:
            result["clearance_mm"] = clearance_mm
        if min_thickness_mm is not None:
            result["min_thickness_mm"] = min_thickness_mm
        thermal_relief: dict[str, float] = {}
        if thermal_gap is not None:
            thermal_relief["gap"] = thermal_gap
        if thermal_bridge_width is not None:
            thermal_relief["spoke_width"] = thermal_bridge_width
        if thermal_relief:
            result["thermal_relief"] = thermal_relief

    if locked:
        result["locked"] = True
    if passthrough:
        result["_kicad_passthrough"] = passthrough

    return result


def _parse_footprint_attr(child: list) -> dict[str, bool]:
    """Parse a footprint `(attr smd exclude_from_pos_files ...)` node.

    KiCad encodes the mount type (`smd` / `through_hole` / `virtual`) and up
    to five independent boolean flags as sibling bare atoms of one `attr`
    node. Circuit JSON's `KicadFootprintAttributes` models four of the six
    flags; `board_only` and `allow_missing_courtyard` are carried too since
    they cost nothing extra as plain dict keys, but are beyond that type's
    declared schema.
    """
    flags = {str(a) for a in child[1:] if not isinstance(a, list)}
    return {
        "smd": "smd" in flags,
        "through_hole": "through_hole" in flags,
        "exclude_from_pos_files": "exclude_from_pos_files" in flags,
        "exclude_from_bom": "exclude_from_bom" in flags,
        "allow_missing_courtyard": "allow_missing_courtyard" in flags,
        "board_only": "board_only" in flags,
    }


# ─── T-538: KiCad Y-down → Circuit JSON Y-up axis flip ────────────────────────
#
# KiCad's `.kicad_pcb` coordinates are Y-down (Y increases toward the bottom
# of the sheet); Circuit JSON's are Y-up. Before this fix, this reader passed
# KiCad's raw Y straight through for every geometry path (component
# positions, trace routes, zone/keepout polygons, free-floating text) — a
# whole-file vertical mirror, found by the T-526b conformance oracle (see
# tasks.md T-538 and the (now-corrected) test that used to be named
# test_component_position_agrees_modulo_y_axis_convention in
# test_kicad_oracle.py).
#
# Mirror axis chosen: a FIXED origin at y=0 — `cj_y = -kicad_y`, x unchanged.
# Not the board's Y extent, not the KiCad page height. Evidence for each:
#
# - Page height: ruled out directly. This module's own writer only ever
#   stores KiCad's page *size* as an opaque template name (`root.child
#   ("paper").atom("A4")`, see circuit_json_to_kicad_pcb above) — never a
#   height in mm participating in geometry. KiCad's own `.kicad_pcb` Y
#   values are absolute-mm in the board's world coordinate system,
#   independent of which paper size is selected for printing; there is no
#   "page height" quantity in the geometry at all to flip about.
#
# - Board's Y extent (bounding-box center of the Edge.Cuts outline): this is
#   what the independent oracle, kicad-to-circuit-json, actually implements
#   — verified by reading its source directly (not just its .d.ts comment):
#   `node_modules/kicad-to-circuit-json/dist/index.js`,
#   `InitializePcbContextStage.step()`:
#     `const center = this.calculateBoardCenter();`
#     `this.ctx.k2cMatPcb = compose(scale(1, -1), translate(-center.x, -center.y));`
#   `calculateBoardCenter()` walks the `Edge.Cuts` graphic lines/arcs/
#   circles/curves and returns the midpoint of their bounding box — falling
#   back to `{x: 0, y: 0}` when the board has *no* Edge.Cuts geometry at all.
#   That fallback is exactly this repo's own conformance fixture
#   (`tests/fixtures/zones_keepout_board.kicad_pcb` has no `Edge.Cuts` node
#   whatsoever — grep it) — which is why the oracle test's own finding
#   ("x, y -> x, -y with no additional offset") looked like a pure origin
#   flip: it wasn't evidence of an origin-based convention, it was the
#   oracle degenerating to one because this fixture has no board outline.
#   Rejected as the general rule for two reasons: (1) it recenters *x* too
#   (`translate(-center.x, ...)`), which is a second, independent
#   translation unrelated to the Y-down/Y-up question this task is scoped
#   to fixing; (2) Kerf's own KiCad fixtures are hand-authored, not pcbnew
#   exports (`docs/ecad-gap-analysis.md`), and are not guaranteed to carry
#   an Edge.Cuts outline — building the axis out of geometry that may not
#   exist makes the transform silently degrade to something else (or a
#   no-op offset) depending on data that has nothing to do with the
#   Y-convention bug being fixed here.
#
# - Fixed origin (chosen): `cj_y = -kicad_y` is well-defined for every board
#   regardless of whether it has an Edge.Cuts outline, touches only the axis
#   this bug is actually about (Y direction, not X placement), and is the
#   simplest transform that is correct wherever the oracle's board-center
#   correction is a no-op (as it is on every fixture in this repo). It also
#   composes correctly with `circuit_json_to_kicad_pcb` above, which writes
#   positions verbatim with no offset — a future writer built with the flip
#   in mind (T-527) has a stable, geometry-independent rule to invert.
#
# T-539 CONFIRMATION: the paragraph above was reasoned from a fixture
# (zones_keepout_board.kicad_pcb) that has no Edge.Cuts outline at all, so it
# could not actually distinguish fixed-origin from board-centered — both
# formulas degenerate to the same thing when `center == {0, 0}`. T-539 built
# a second fixture with a genuine, off-origin outline
# (tests/fixtures/board_with_outline.kicad_pcb, bbox (50,50)-(150,120),
# center (100, 85)) specifically to make them disagree, then settled which
# one Circuit JSON actually means from evidence, not from this reasoning
# alone:
#   - `node_modules/circuit-json/dist/index.d.mts`'s `pcb_board` zod schema
#     declares `center` as a *required* field of every board — the format
#     lets a board sit anywhere, `center` is descriptive, not a mandate that
#     contents get recentered around it.
#   - `node_modules/@tscircuit/core/dist/index.js`, `Board._getBoardCalcVariables`
#     / `getResolvedPcbPositionProp`: when tscircuit itself authors a board,
#     `center` is *derived* from the board's own position props or from its
#     components' bounding box — never the reverse. Nothing recenters a
#     component's already-placed coordinates once the board's extent is known.
#   - A real tscircuit-authored fixture,
#     `node_modules/@tscircuit/schematic-corpus/dist/designs/design036/circuit.json`,
#     has `pcb_board.center == {x: 2.415, y: 0}` yet one of its
#     `pcb_component` entries sits at literal `x: 0` — nowhere near the
#     board's own center, confirming component coordinates are absolute in a
#     single shared frame, not relative to the board's bounding box.
# Verdict: fixed origin is correct. `kicad-to-circuit-json`'s Edge.Cuts-bbox
# recentering is that project's own import-time convenience, not something
# Circuit JSON as a format requires. No change made to this function; see
# `TestKicadOracleOutlineConvention` in test_kicad_oracle.py for the fixture
# that proves the divergence and pins this conclusion.
#
# Deliberately NOT touched: `rotation` on `pcb_component`. A mirror transform
# does, in general, invert the sense of a rotation angle (kicad-to-circuit-
# json's own source negates it: `dist/index.js`, `processFootprint`,
# `rotation: -rotation, // Negate rotation due to Y-axis flip in coordinate
# transform`) — but this reader never derives any geometry from that angle
# (no pads, no rotated courtyard/body shapes are emitted here), so there is
# no place in this module where getting its sign wrong would be observable,
# and negating it would be a second, untested behavioral change beyond the
# geometry paths tasks.md's T-538 entry and the oracle actually exercise.
# Flagged here rather than silently decided either way; revisit when this
# reader grows footprint-body geometry that actually uses `rotation`.
#
# Deliberately NOT touched: `kicad_passthrough` / `_kicad_passthrough`
# payloads (unmodeled top-level nodes like `group`, vias, dimensions, and a
# zone's own leftover children like `filled_polygon`). Those are raw KiCad
# source s-expr fragments, never translated into Circuit JSON's coordinate
# space to begin with (that's the whole point of passthrough — round-trip
# fidelity for a future writer, not semantic modeling) — the Y-up/Y-down
# question doesn't apply to data that was never converted.

def _flip_kicad_y_to_circuit_json_y(cj: list[dict]) -> None:
    """Mirror every KiCad Y-down coordinate this reader emits to Circuit
    JSON's Y-up convention, in place, over the whole output list.

    Applied once, here, after every element has been parsed — not at each
    individual coordinate assignment scattered through the parsing loops
    above — so there is exactly one place in this module where the flip
    could be wrong, not one per element type. See the module-level note
    above for why `-y` (a fixed origin) rather than a board- or page-relative
    axis.

    Covers every geometry-bearing shape this reader produces:
    - top-level `y` (pcb_component, pcb_text/gr_text)
    - `polygon` point lists (pcb_keepout, pcb_copper_pour, pcb_ground_plane)
    - `route` point lists (pcb_trace)
    """
    for entry in cj:
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("y"), (int, float)):
            entry["y"] = -entry["y"]
        for list_key in ("polygon", "route"):
            points = entry.get(list_key)
            if isinstance(points, list):
                for pt in points:
                    if isinstance(pt, dict) and isinstance(pt.get("y"), (int, float)):
                        pt["y"] = -pt["y"]


# ─── kicad_pcb_to_circuit_json ─────────────────────────────────────────────────

def kicad_pcb_to_circuit_json(text: str) -> list:
    """Parse a KiCad v6/v7 .kicad_pcb string and return a Circuit-JSON list.

    Recovers:
    - source_component entries for each footprint (ref → name)
    - pcb_component entries with position/rotation/layer
    - source_net entries from the net table
    - pcb_trace entries from segment nodes
    """
    root = _parse_sexpr(text)
    if not isinstance(root, list) or not root:
        return []

    # root[0] should be the tag "kicad_pcb"
    nodes = root[1:]  # skip tag

    cj: list[dict] = []

    # ── Net table ─────────────────────────────────────────────────────────────
    net_index_to_name: dict[int, str] = {}
    net_name_to_id: dict[str, str] = {}

    for node in nodes:
        if not isinstance(node, list) or not node or node[0] != "net":
            continue
        # (net <index> <name>)
        if len(node) >= 3:
            try:
                idx = int(node[1])
            except (ValueError, TypeError):
                continue
            name = node[2] if isinstance(node[2], str) else str(node[2])
            if name:  # skip empty-net slot 0
                net_index_to_name[idx] = name
                nid = f"sn_{_slugify(name)}"
                net_name_to_id[name] = nid
                cj.append({
                    "type": "source_net",
                    "source_net_id": nid,
                    "name": name,
                })

    # ── Footprints ────────────────────────────────────────────────────────────
    sc_seen: set[str] = set()
    pcb_comp_index = 0

    for node in nodes:
        if not isinstance(node, list) or not node or node[0] != "footprint":
            continue

        # footprint name is node[1]
        fp_name = node[1] if len(node) > 1 and isinstance(node[1], str) else "Unknown"

        ref = ""
        value = ""
        x = 0.0
        y = 0.0
        rot = 0.0
        layer_kicad = "F.Cu"
        tstamp = ""
        locked = False
        fp_attrs: dict[str, bool] | None = None

        for child in node[2:]:
            if not isinstance(child, list) or not child:
                if child == "locked":
                    locked = True
                continue
            tag = child[0]

            if tag == "at" and len(child) >= 3:
                try:
                    x = float(child[1])
                    y = float(child[2])
                    if len(child) >= 4:
                        rot = float(child[3])
                except (ValueError, TypeError):
                    pass

            elif tag == "layer" and len(child) >= 2:
                layer_kicad = child[1] if isinstance(child[1], str) else "F.Cu"

            elif tag == "tstamp" and len(child) >= 2:
                tstamp = child[1] if isinstance(child[1], str) else ""

            elif tag == "locked":
                locked = True

            elif tag == "attr":
                fp_attrs = _parse_footprint_attr(child)

            elif tag == "fp_text" and len(child) >= 3:
                kind = child[1]
                val  = child[2] if isinstance(child[2], str) else ""
                if kind == "reference":
                    ref = val
                elif kind == "value":
                    value = val

        if not ref:
            ref = f"FP{pcb_comp_index}"

        scid = f"sc_{_slugify(ref)}"
        # emit source_component once per unique ref
        if scid not in sc_seen:
            sc_seen.add(scid)
            cj.append({
                "type": "source_component",
                "source_component_id": scid,
                "name": ref,
                "value": value,
                "footprint": fp_name,
            })

        layer_cj = _KICAD_TO_CJ_LAYER.get(layer_kicad, "top_copper")
        pcb_cid = tstamp if tstamp else f"pcb_{_slugify(ref)}_{pcb_comp_index}"
        pcb_comp: dict[str, Any] = {
            "type": "pcb_component",
            "pcb_component_id": pcb_cid,
            "source_component_id": scid,
            "x": x,
            "y": y,
            "rotation": rot,
            "layer": layer_cj,
        }
        if locked:
            pcb_comp["locked"] = True
        if fp_attrs is not None:
            pcb_comp["kicad_footprint_attributes"] = fp_attrs
        cj.append(pcb_comp)
        pcb_comp_index += 1

    # ── Segments ──────────────────────────────────────────────────────────────
    seg_index = 0
    # Group segments by net to create pcb_trace entries
    net_segments: dict[str, list[dict]] = {}

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
        key = f"{net_name}|{seg_layer}|{width}"
        if key not in net_segments:
            net_segments[key] = []
        net_segments[key].append({
            "start": {"x": sx, "y": sy},
            "end": {"x": ex, "y": ey},
            "layer": _KICAD_TO_CJ_LAYER.get(seg_layer, "top_copper"),
            "width": width,
            "net_name": net_name,
        })
        seg_index += 1

    for key, segs in net_segments.items():
        net_name = segs[0]["net_name"]
        layer_cj = segs[0]["layer"]
        width    = segs[0]["width"]
        stid = f"st_{_slugify(net_name)}_{_slugify(key[:20])}" if net_name else f"st_{seg_index}"

        # Build route: chain endpoints
        route = []
        for seg in segs:
            route.append(seg["start"])
            route.append(seg["end"])

        net_ids = []
        if net_name and net_name in net_name_to_id:
            net_ids = [net_name_to_id[net_name]]

        cj.append({
            "type": "pcb_trace",
            "pcb_trace_id": f"pcbt_{_slugify(key[:20])}",
            "source_trace_id": stid,
            "route": route,
            "width": width,
            "layer": layer_cj,
        })
        if net_ids:
            cj.append({
                "type": "source_trace",
                "source_trace_id": stid,
                "connected_source_port_ids": [],
                "connected_source_net_ids": net_ids,
            })

    # ── Zones: copper pours, ground planes, keepouts ─────────────────────────
    pour_idx = 0
    keepout_idx = 0
    for node in nodes:
        if not isinstance(node, list) or not node or node[0] != "zone":
            continue
        zone_cj = _parse_zone_node(node, pour_idx, keepout_idx)
        if zone_cj["type"] == "pcb_keepout":
            keepout_idx += 1
        else:
            pour_idx += 1
        cj.append(zone_cj)

    # ── Free-floating board text (gr_text) ───────────────────────────────────
    text_idx = 0
    for node in nodes:
        if not isinstance(node, list) or not node or node[0] != "gr_text":
            continue
        text = node[1] if len(node) > 1 and isinstance(node[1], str) else ""
        gx = gy = 0.0
        layer_kicad = "Cmts.User"
        locked = False
        for child in node[2:]:
            if not isinstance(child, list) or not child:
                if child == "locked":
                    locked = True
                continue
            tag = child[0]
            if tag == "at" and len(child) >= 3:
                try:
                    gx = float(child[1])
                    gy = float(child[2])
                except (ValueError, TypeError):
                    pass
            elif tag == "layer" and len(child) >= 2:
                layer_kicad = child[1] if isinstance(child[1], str) else "Cmts.User"
            elif tag == "locked":
                locked = True

        gr_text_entry: dict[str, Any] = {
            "type": "pcb_text",
            "pcb_text_id": f"text_{text_idx}",
            "text": text,
            "x": gx,
            "y": gy,
            "layer": _KICAD_TO_CJ_LAYER.get(layer_kicad, layer_kicad),
        }
        if locked:
            gr_text_entry["locked"] = True
        cj.append(gr_text_entry)
        text_idx += 1

    # ── Passthrough: anything else at the top level, preserved verbatim ─────
    # (groups, dimensions, vias, other graphic items, stackup, etc.) so a
    # future writer can re-emit them rather than silently losing them. See
    # docs/ecad-gap-analysis.md rows 12/13/15 — groups in particular have no
    # faithful Circuit-JSON-shaped home today (row 12: "don't overload
    # pcb_group", which models a different, autoplacement-only concept), so
    # they are deliberately *not* given a first-class type here.
    passthrough_nodes = [
        node for node in nodes
        if isinstance(node, list) and node
        and node[0] not in _KICAD_HANDLED_TOP_TAGS
        and node[0] not in _KICAD_IGNORED_TOP_TAGS
    ]
    if passthrough_nodes:
        cj.append({
            "type": "kicad_passthrough",
            "kicad_nodes": passthrough_nodes,
        })

    # T-538: apply the KiCad Y-down -> Circuit JSON Y-up flip, once, at the
    # boundary, over every geometry-bearing element just built above. See
    # `_flip_kicad_y_to_circuit_json_y`'s docstring for the axis rationale.
    _flip_kicad_y_to_circuit_json_y(cj)

    return cj


# ─── Utility ───────────────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    """Convert a string to a safe identifier fragment (lowercase, underscores)."""
    return re.sub(r"[^a-zA-Z0-9]", "_", s).lower()
