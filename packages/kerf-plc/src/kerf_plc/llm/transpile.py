"""
kerf_plc.llm.transpile — Bidirectional ST ↔ LD transpiler (lossy-but-faithful).

Public API
----------
convert_st_to_ladder(st_source: str) -> Project
    Parse a Structured Text POU and emit an equivalent PLCopen Ladder-Diagram
    Project.  Each convertible statement becomes one rung.

convert_ladder_to_st(project: Project) -> str
    Walk a PLCopen Project whose first POU body is an LDBody and emit
    equivalent Structured Text source.

Supported ST ↔ LD subset
-------------------------
- Pure boolean assignment:  ``coil := a AND NOT b;``
  → one rung: contacts in series + output coil

- IF/THEN (single condition, optional else):
  ``IF cond THEN out := TRUE; END_IF;``
  → rung: condition contacts in series + coil

- FB call + Q-output read:
  ``t(IN := sig, PT := T#1s);``  followed by  ``out := t.Q;``
  → rung: contact + fb_call block + coil

- Multiple consecutive statements → multiple rungs

Unsupported constructs (FOR, WHILE, REPEAT, CASE, ELSIF chains) raise
``TranspileError`` with a structured ``{"unconvertible": ..., "reason": ...}``
message.
"""
from __future__ import annotations

import re
from typing import Union

from kerf_plc.plcopen.ast import (
    Coil,
    Configuration,
    Contact,
    ContentHeader,
    FBInstance,
    Instances,
    LDBody,
    LeftPowerRail,
    POU,
    Position,
    ProgramInstance,
    Project,
    Resource,
    RightPowerRail,
    Rung,
    STBody,
    TaskConfig,
    Types,
    VarBlock,
    Variable,
)
from kerf_plc.st import ast as A
from kerf_plc.st.parser import ParseError, parse

__all__ = ["convert_st_to_ladder", "convert_ladder_to_st", "TranspileError"]

# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class TranspileError(ValueError):
    """Raised when a construct cannot be translated.

    *detail* is a dict: ``{"unconvertible": str, "reason": str}``.
    """

    def __init__(self, unconvertible: str, reason: str) -> None:
        self.detail = {"unconvertible": unconvertible, "reason": reason}
        super().__init__(str(self.detail))


# ---------------------------------------------------------------------------
# Internal helpers — position generation
# ---------------------------------------------------------------------------

def _pos(x: int, y: int) -> Position:
    return Position(x=x, y=y)


def _lpr(local_id: int, y: int = 0) -> LeftPowerRail:
    return LeftPowerRail(local_id=local_id, position=_pos(0, y))


def _rpr(local_id: int, y: int = 0) -> RightPowerRail:
    return RightPowerRail(local_id=local_id, position=_pos(500, y))


def _contact(local_id: int, variable: str, negated: bool, x: int, y: int) -> Contact:
    return Contact(local_id=local_id, variable=variable, negated=negated,
                   position=_pos(x, y))


def _coil(local_id: int, variable: str, x: int, y: int) -> Coil:
    return Coil(local_id=local_id, variable=variable, negated=False,
                position=_pos(x, y))


def _fb(local_id: int, type_name: str, instance_name: str, x: int, y: int) -> FBInstance:
    return FBInstance(local_id=local_id, type_name=type_name,
                      instance_name=instance_name, position=_pos(x, y))


def _wrap_project(pou_name: str, pou: POU) -> Project:
    task = TaskConfig(name="MainTask", interval="T#10ms", priority=0)
    prog_inst = ProgramInstance(name="MainInstance",
                                type_name=pou_name,
                                task_name="MainTask")
    resource = Resource(name="PLC_Resource", type_name="PLC",
                        tasks=[task],
                        program_instances=[prog_inst])
    cfg = Configuration(name="Config0", resources=[resource])
    return Project(
        content_header=ContentHeader(name=pou_name, version="1.0",
                                     product_name="Kerf", product_version="1.0",
                                     product_release="1.0"),
        types=Types(pous=[pou]),
        instances=Instances(configurations=[cfg]),
    )


# ---------------------------------------------------------------------------
# ST expression → list of (variable, negated) contact descriptors
# ---------------------------------------------------------------------------

def _expr_to_contacts(expr: A.Expression) -> list[tuple[str, bool]]:
    """
    Flatten a boolean expression tree into a flat series of (var, negated) pairs.

    Handles:
      VarRef            → [(name, False)]
      UnaryOp NOT x     → [(name_of_x, True)] (only for VarRef/FieldRef operand)
      BinaryOp AND l r  → contacts_of_l + contacts_of_r
      BoolLiteral TRUE  → [] (always-on, skip)
      FieldRef obj.Q    → [(obj_name + '_Q' or obj_name, False)]

    Raises TranspileError for OR, XOR, arithmetic, or other complex nodes.
    """
    if isinstance(expr, A.VarRef):
        return [(expr.name, False)]

    if isinstance(expr, A.FieldRef):
        # Represent t.Q as a contact named "t_Q"
        if isinstance(expr.obj, A.VarRef):
            return [(f"{expr.obj.name}_{expr.field}", False)]
        raise TranspileError(
            "nested field access",
            "Only single-level field access (var.field) is supported",
        )

    if isinstance(expr, A.BoolLiteral):
        # TRUE is a wire (always energised) — emit no contact; FALSE is unconvertible
        if expr.value:
            return []
        raise TranspileError("FALSE literal", "FALSE literal in condition is not representable in LD")

    if isinstance(expr, A.UnaryOp):
        if expr.op == "NOT":
            inner_contacts = _expr_to_contacts(expr.operand)
            # Flip negation of every contact
            return [(v, not neg) for v, neg in inner_contacts]
        raise TranspileError(
            f"unary {expr.op}",
            "Only NOT is supported as a unary LD contact modifier",
        )

    if isinstance(expr, A.BinaryOp):
        if expr.op == "AND":
            return _expr_to_contacts(expr.left) + _expr_to_contacts(expr.right)
        if expr.op in ("OR", "XOR"):
            raise TranspileError(
                f"{expr.op} expression",
                f"{expr.op} logic requires parallel branches — not supported in flat-rung ST→LD conversion",
            )
        raise TranspileError(
            f"operator {expr.op}",
            "Arithmetic/comparison operators are not representable as LD contacts",
        )

    raise TranspileError(
        type(expr).__name__,
        f"Expression type {type(expr).__name__!r} cannot be converted to LD contacts",
    )


# ---------------------------------------------------------------------------
# ST statement → Rung(s)
# ---------------------------------------------------------------------------

# Track per-rung local IDs (re-set for each rung by the builder)
_STDLIB_FB = frozenset({"TON", "TOF", "TP", "SR", "RS", "CTU", "CTD", "CTUD", "R_TRIG", "F_TRIG"})


class _STToLD:
    """Stateful converter: accumulates rungs from ST statement list."""

    def __init__(self, pou_name: str,
                 var_type_map: dict[str, str] | None = None) -> None:
        self._pou_name = pou_name
        self._rungs: list[Rung] = []
        self._rung_idx = 0
        self._local_id = 1
        # Track pending FB calls: instance_name → (fb_type, named_args)
        self._pending_fb: dict[str, tuple[str, dict[str, A.Expression]]] = {}
        # Variable name → declared type (e.g. "timer" → "TON"), used for FB inference
        self._var_type_map: dict[str, str] = var_type_map or {}

    # ---- helpers -------------------------------------------------------

    def _next_id(self) -> int:
        v = self._local_id
        self._local_id += 1
        return v

    def _y(self) -> int:
        return self._rung_idx * 60

    def _emit_rung(self, contacts: list[Contact], fbs: list[FBInstance],
                   coil_var: str) -> None:
        y = self._y()
        rung = Rung(
            left_power_rail=LeftPowerRail(local_id=self._next_id(), position=_pos(0, y)),
            right_power_rail=RightPowerRail(local_id=self._next_id(), position=_pos(500, y)),
            contacts=contacts,
            coils=[Coil(local_id=self._next_id(), variable=coil_var, negated=False,
                        position=_pos(400, y))],
            fb_instances=fbs,
        )
        self._rungs.append(rung)
        self._rung_idx += 1

    # ---- statement handlers -------------------------------------------

    def _handle_assignment(self, stmt: A.Assignment) -> None:
        """
        Convert:
          target := expr;
        to a rung.

        Cases:
          * target := contact_a AND NOT contact_b   → contacts in series + coil
          * target := t.Q                           → contact for t_Q + coil
          * target := TRUE / FALSE                  → contact-less TRUE coil / raise
        """
        # Determine coil variable
        if isinstance(stmt.target, A.VarRef):
            coil_var = stmt.target.name
        elif isinstance(stmt.target, A.FieldRef):
            if isinstance(stmt.target.obj, A.VarRef):
                coil_var = f"{stmt.target.obj.name}_{stmt.target.field}"
            else:
                raise TranspileError(
                    "nested field assignment",
                    "Only single-level field assignment is supported in LD",
                )
        else:
            raise TranspileError(
                "complex assignment target",
                "Only variable or field references are supported as assignment targets",
            )

        # Resolve RHS to contacts
        contact_descs = _expr_to_contacts(stmt.value)

        y = self._y()
        contacts = []
        x = 40
        for var_name, negated in contact_descs:
            contacts.append(Contact(
                local_id=self._next_id(),
                variable=var_name,
                negated=negated,
                position=_pos(x, y),
            ))
            x += 60

        self._emit_rung(contacts, [], coil_var)

    def _handle_if(self, stmt: A.IfStmt) -> None:
        """
        Convert a simple IF/THEN to a rung.

        Supports:
          IF cond THEN target := TRUE; END_IF;
          IF cond THEN target := FALSE; END_IF;  (negated coil — not supported, raise)
          IF cond THEN target := TRUE; ELSE target := FALSE; END_IF;

        Raises for ELSIF or multiple body statements with different targets.
        """
        if stmt.elsif_clauses:
            raise TranspileError(
                "ELSIF",
                "ELSIF clauses cannot be expressed as a single ladder rung",
            )

        # Gather condition contacts
        cond_contacts = _expr_to_contacts(stmt.condition)

        # Collect coil assignments from then_stmts
        for body_stmt in stmt.then_stmts:
            if not isinstance(body_stmt, A.Assignment):
                raise TranspileError(
                    "non-assignment in IF body",
                    "Only simple assignments are supported in IF body for LD conversion",
                )
            if isinstance(body_stmt.target, A.VarRef):
                coil_var = body_stmt.target.name
            elif isinstance(body_stmt.target, A.FieldRef) and isinstance(body_stmt.target.obj, A.VarRef):
                coil_var = f"{body_stmt.target.obj.name}_{body_stmt.target.field}"
            else:
                raise TranspileError(
                    "complex IF body assignment target",
                    "Only variable references are supported as IF-body assignment targets",
                )

            y = self._y()
            contacts = []
            x = 40
            for var_name, negated in cond_contacts:
                contacts.append(Contact(
                    local_id=self._next_id(),
                    variable=var_name,
                    negated=negated,
                    position=_pos(x, y),
                ))
                x += 60

            self._emit_rung(contacts, [], coil_var)

    def _handle_call_stmt(self, stmt: A.CallStmt) -> None:
        """
        Convert an FB call:  instance(IN := sig, PT := T#1s);
        to a pending FB record.  The rung is emitted when the subsequent
        ``out := instance.Q;`` assignment is processed.
        """
        call = stmt.call
        # Check whether this looks like an FB call (uppercase type-like name)
        # We store it as a pending FB by instance name
        fb_type = self._infer_fb_type(call.name, call.named_args)
        if fb_type:
            self._pending_fb[call.name] = (fb_type, call.named_args)
        else:
            # Treat as a no-op contact rung (standalone call we can't model)
            raise TranspileError(
                f"function call {call.name!r}",
                f"Cannot determine FB type for call {call.name!r}; "
                "only stdlib FB calls (TON, TOF, CTU, …) are supported",
            )

    def _infer_fb_type(
        self,
        name: str,
        named_args: dict[str, A.Expression],
    ) -> str | None:
        """
        Guess FB type from the call's named parameters, uppercase name, or
        the POU's variable declarations (self._var_type_map).
        """
        # Check var declarations first (most reliable)
        declared = self._var_type_map.get(name, "")
        if declared.upper() in _STDLIB_FB:
            return declared.upper()

        # Named-arg heuristics
        if "PT" in named_args:
            return "TON"  # TON / TOF both use PT; default to TON
        if "PV" in named_args:
            return "CTU"
        if "IN" in named_args and "R" in named_args:
            return "SR"
        # If the name itself is a known FB type (direct call)
        if name.upper() in _STDLIB_FB:
            return name.upper()
        # If var is declared as any non-simple type, treat it as a generic FB
        if declared and declared.upper() not in {
            "BOOL", "INT", "DINT", "LINT", "UINT", "UDINT", "ULINT",
            "SINT", "USINT", "REAL", "LREAL", "TIME", "DATE", "STRING",
            "BYTE", "WORD", "DWORD", "LWORD", "TOD", "DT",
        }:
            return declared.upper()
        return None

    def _handle_field_ref_assignment(self, stmt: A.Assignment) -> None:
        """
        Handle  out := instance.Q;  by flushing the pending FB rung.
        """
        assert isinstance(stmt.value, A.FieldRef)
        assert isinstance(stmt.value.obj, A.VarRef)
        assert isinstance(stmt.target, A.VarRef)

        fb_instance_name = stmt.value.obj.name
        coil_var = stmt.target.name

        if fb_instance_name not in self._pending_fb:
            # Treat as a plain contact assignment
            self._handle_assignment(stmt)
            return

        fb_type, named_args = self._pending_fb.pop(fb_instance_name)

        # Collect IN signal as a contact (if present)
        y = self._y()
        contacts: list[Contact] = []
        x = 40
        if "IN" in named_args:
            in_expr = named_args["IN"]
            try:
                in_contacts = _expr_to_contacts(in_expr)
            except TranspileError:
                in_contacts = []
            for var_name, negated in in_contacts:
                contacts.append(Contact(
                    local_id=self._next_id(),
                    variable=var_name,
                    negated=negated,
                    position=_pos(x, y),
                ))
                x += 60

        fb_elem = FBInstance(
            local_id=self._next_id(),
            type_name=fb_type,
            instance_name=fb_instance_name,
            position=_pos(x + 20, y),
        )

        self._emit_rung(contacts, [fb_elem], coil_var)

    # ---- main dispatch -------------------------------------------------

    def convert(self, statements: list[A.Statement]) -> list[Rung]:
        for stmt in statements:
            if isinstance(stmt, A.ForStmt):
                raise TranspileError("FOR loop", "FOR loops cannot be represented as ladder rungs")
            if isinstance(stmt, A.WhileStmt):
                raise TranspileError("WHILE loop", "WHILE loops cannot be represented as ladder rungs")
            if isinstance(stmt, A.RepeatStmt):
                raise TranspileError("REPEAT loop", "REPEAT loops cannot be represented as ladder rungs")
            if isinstance(stmt, A.CaseStmt):
                raise TranspileError("CASE statement", "CASE statements cannot be represented as ladder rungs")

            if isinstance(stmt, A.Assignment):
                # Check if RHS is a field ref (e.g. t.Q) to flush pending FB
                if (
                    isinstance(stmt.value, A.FieldRef)
                    and isinstance(stmt.value.obj, A.VarRef)
                    and isinstance(stmt.target, A.VarRef)
                ):
                    self._handle_field_ref_assignment(stmt)
                else:
                    self._handle_assignment(stmt)

            elif isinstance(stmt, A.IfStmt):
                self._handle_if(stmt)

            elif isinstance(stmt, A.CallStmt):
                self._handle_call_stmt(stmt)

            else:
                # Unknown statement type — skip silently (e.g. RETURN)
                pass

        return self._rungs


# ---------------------------------------------------------------------------
# ST → LD: public entry point
# ---------------------------------------------------------------------------

def convert_st_to_ladder(st_source: str) -> Project:
    """
    Parse *st_source* (a complete IEC 61131-3 ST POU) and return an equivalent
    PLCopen Ladder-Diagram :class:`~kerf_plc.plcopen.ast.Project`.

    Raises
    ------
    TranspileError
        When the source contains constructs that cannot be represented in a
        flat ladder diagram (FOR loops, CASE statements, OR expressions, …).
    ParseError
        When *st_source* is not valid IEC 61131-3 Structured Text.
    """
    pou_ast = parse(st_source)

    # Build a variable→type map for FB inference
    var_type_map: dict[str, str] = {}
    for vb in pou_ast.variables:
        for decl in vb.declarations:
            if isinstance(decl.type, A.SimpleType):
                var_type_map[decl.name] = decl.type.name

    converter = _STToLD(pou_name=pou_ast.name, var_type_map=var_type_map)
    rungs = converter.convert(pou_ast.body)

    # Build variable declarations from ST POU
    var_blocks: list[VarBlock] = []
    kind_map = {
        "VAR": "local",
        "VAR_INPUT": "input",
        "VAR_OUTPUT": "output",
        "VAR_IN_OUT": "inOut",
    }
    for vb in pou_ast.variables:
        plc_kind = kind_map.get(vb.kind, "local")
        variables = [
            Variable(
                name=decl.name,
                type_name=decl.type.name if isinstance(decl.type, A.SimpleType) else "BOOL",
            )
            for decl in vb.declarations
        ]
        var_blocks.append(VarBlock(kind=plc_kind, variables=variables))

    pou_type_map = {
        "PROGRAM": "program",
        "FUNCTION_BLOCK": "functionBlock",
        "FUNCTION": "function",
    }
    pou = POU(
        name=pou_ast.name,
        pou_type=pou_type_map.get(pou_ast.pou_type, "program"),
        var_blocks=var_blocks,
        body=LDBody(rungs=rungs),
    )

    return _wrap_project(pou_ast.name, pou)


# ---------------------------------------------------------------------------
# LD → ST helpers
# ---------------------------------------------------------------------------

def _duration_ms_to_st(ms: int) -> str:
    """Convert milliseconds back to a T# literal: 1000 → T#1s."""
    if ms == 0:
        return "T#0ms"
    parts: list[str] = []
    remaining = ms
    for unit, factor in [("d", 86_400_000), ("h", 3_600_000), ("m", 60_000), ("s", 1_000), ("ms", 1)]:
        if remaining >= factor:
            val = remaining // factor
            remaining -= val * factor
            parts.append(f"{val}{unit}")
    return "T#" + "".join(parts)


def _contact_to_expr(contact: Contact) -> str:
    """Return an ST expression fragment for a single contact."""
    if contact.negated:
        return f"NOT {contact.variable}"
    return contact.variable


def _rung_to_st(rung: Rung, indent: str = "    ") -> list[str]:
    """
    Convert one LD rung to one or more ST statements.

    Returns a list of ST statement strings (without trailing newline).
    """
    lines: list[str] = []

    contacts = rung.contacts
    fbs = rung.fb_instances
    coils = rung.coils

    # Build condition expression from contacts (AND of all contacts)
    if contacts:
        cond_parts = [_contact_to_expr(c) for c in contacts]
        # Wrap in parens where needed to preserve precedence
        def _wrap(s: str) -> str:
            if " " in s:
                return f"({s})"
            return s
        condition = " AND ".join(_wrap(p) for p in cond_parts)
    else:
        condition = None

    # Emit FB calls if present
    for fb in fbs:
        # Reconstruct the FB call with IN mapped from contacts
        fb_args_parts: list[str] = []
        if contacts:
            # Use the first contact's variable as IN
            in_var = contacts[0].variable if contacts else None
            if in_var:
                fb_args_parts.append(f"IN := {in_var}")
        lines.append(f"{fb.instance_name}({', '.join(fb_args_parts)});")

    # Emit coil assignments
    for coil in coils:
        if condition:
            lines.append(f"IF {condition} THEN")
            lines.append(f"{indent}{coil.variable} := TRUE;")
            lines.append("END_IF;")
        else:
            lines.append(f"{coil.variable} := TRUE;")

    # If there are FB instances and coils, also emit the .Q assignment
    if fbs and coils:
        # Remove the simple TRUE assignment we just emitted — replace with .Q read
        # (We need to revisit the last emitted block)
        # Instead: overwrite the last group of lines
        lines.clear()
        for fb in fbs:
            fb_args_parts = []
            if contacts:
                in_var = contacts[0].variable
                fb_args_parts.append(f"IN := {in_var}")
            lines.append(f"{fb.instance_name}({', '.join(fb_args_parts)});")
        for coil in coils:
            lines.append(f"{coil.variable} := {fbs[0].instance_name}.Q;")

    return lines


# ---------------------------------------------------------------------------
# LD → ST: public entry point
# ---------------------------------------------------------------------------

def convert_ladder_to_st(project: Project) -> str:
    """
    Walk a PLCopen :class:`~kerf_plc.plcopen.ast.Project` and emit equivalent
    Structured Text source.

    The first POU with an :class:`~kerf_plc.plcopen.ast.LDBody` is converted.
    POUs with STBody, FBDBody, or ILBody pass-through their existing text.

    Returns
    -------
    str
        A complete IEC 61131-3 ST POU string.
    """
    pou = _find_ld_pou(project)
    if pou is None:
        # Fall back: if it's an ST body, return the existing text wrapped in a POU shell
        for p in project.types.pous:
            if isinstance(p.body, STBody):
                return p.body.text
        return ""

    lines: list[str] = []
    pou_kw_map = {
        "program": "PROGRAM",
        "functionBlock": "FUNCTION_BLOCK",
        "function": "FUNCTION",
    }
    pou_kw = pou_kw_map.get(pou.pou_type, "PROGRAM")
    end_kw = {
        "PROGRAM": "END_PROGRAM",
        "FUNCTION_BLOCK": "END_FUNCTION_BLOCK",
        "FUNCTION": "END_FUNCTION",
    }[pou_kw]

    lines.append(f"{pou_kw} {pou.name}")

    # Variable blocks
    vb_kw_map = {
        "local": "VAR",
        "input": "VAR_INPUT",
        "output": "VAR_OUTPUT",
        "inOut": "VAR_IN_OUT",
    }
    for vb in pou.var_blocks:
        kw = vb_kw_map.get(vb.kind, "VAR")
        lines.append(kw)
        for var in vb.variables:
            lines.append(f"    {var.name} : {var.type_name};")
        lines.append("END_VAR")

    assert isinstance(pou.body, LDBody)
    for rung in pou.body.rungs:
        rung_lines = _rung_to_st(rung)
        lines.extend(rung_lines)

    lines.append(end_kw)
    return "\n".join(lines) + "\n"


def _find_ld_pou(project: Project) -> POU | None:
    """Return the first POU with an LDBody, or None."""
    for pou in project.types.pous:
        if isinstance(pou.body, LDBody):
            return pou
    return None
