"""
kerf_plc.power_flow — IEC 61131-3 §3 power-flow computation engine.

Given a :class:`~kerf_plc.plcopen.ast.Rung` and a snapshot of current
variable values, compute which elements carry logical "power" (the left-to-right
energy flow on a Ladder Diagram rung).

Topology derivation
-------------------
The PLCopen XML AST stores all rung elements as flat typed lists with
:class:`~kerf_plc.plcopen.ast.Position` attributes.  Connectivity is
inferred by grouping elements into **columns** ordered by ``position.x``
(ascending).  Elements sharing the same x-coordinate form a **parallel
group** (OR); consecutive groups are in **series** (AND).

Contact semantics (IEC 61131-3 §9.2.2)
---------------------------------------
- **NO** (``contact_types`` == ``'no'`` or default when ``negated=False``):
  passes power iff variable is ``True``.
- **NC** (``contact_types`` == ``'nc'`` or default when ``negated=True``):
  passes power iff variable is ``False``.
- **POS** (rising-edge, ``contact_types`` == ``'pos'``):
  passes power iff variable transitions ``False → True`` in this scan
  (requires *prev_variables* for previous state; defaults to ``False``).
- **NEG** (falling-edge, ``contact_types`` == ``'neg'``):
  passes power iff variable transitions ``True → False`` in this scan.

Power propagation
-----------------
The left power rail always supplies power (True).  Power passes through
the series chain of column groups.  Within each parallel group the group
output is the OR of each element's individual output.  A coil is energised
iff power arrives at its column.

Usage
-----
::

    from kerf_plc.plcopen.ast import Contact, Coil, LeftPowerRail, RightPowerRail, Rung
    from kerf_plc.power_flow import compute

    rung = Rung(
        left_power_rail=LeftPowerRail(local_id=1),
        contacts=[
            Contact(local_id=2, variable="start", negated=False),
            Contact(local_id=3, variable="stop",  negated=True),
        ],
        coils=[Coil(local_id=4, variable="motor")],
        right_power_rail=RightPowerRail(local_id=5),
    )
    flow = compute(rung, {"start": True, "stop": False})
    assert flow.coils[4] is True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from kerf_plc.plcopen.ast import (
    Coil,
    Contact,
    FBInstance,
    LeftPowerRail,
    Rung,
)

# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass
class PowerFlow:
    """Result of a power-flow evaluation on a single rung.

    Attributes
    ----------
    contacts:
        Maps each Contact ``local_id`` to ``True`` when that contact passes
        power (is energised) in this scan.
    coils:
        Maps each Coil ``local_id`` to ``True`` when power reaches that coil.
    wires:
        Maps ``(from_local_id, to_local_id)`` to ``True`` when the wire
        segment between those two element IDs is energised.  The left power
        rail uses its own ``local_id`` as the *from* node; the right power
        rail (if present) uses its ``local_id`` as the *to* node of the final
        wire.
    fb_outputs:
        Maps each FBInstance ``local_id`` to the boolean output value
        computed by its internal logic (currently the pass-through power
        rail value arriving at that FB column).
    """

    contacts: dict[int, bool] = field(default_factory=dict)
    coils: dict[int, bool] = field(default_factory=dict)
    wires: dict[tuple[int, int], bool] = field(default_factory=dict)
    fb_outputs: dict[int, bool] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _x_of(elem: Contact | Coil | FBInstance | LeftPowerRail) -> int:
    """Return the x-coordinate of an element, defaulting to 0."""
    pos = getattr(elem, "position", None)
    if pos is None:
        return 0
    return pos.x


def _contact_passes(
    contact: Contact,
    variables: dict[str, bool],
    prev_variables: dict[str, bool],
    contact_types: dict[int, str],
) -> bool:
    """Return True iff this contact passes power given variable states."""
    ctype = contact_types.get(contact.local_id)
    if ctype is None:
        # Derive from negated flag: False → NO, True → NC
        ctype = "nc" if contact.negated else "no"

    var_val = bool(variables.get(contact.variable, False))
    prev_val = bool(prev_variables.get(contact.variable, False))

    if ctype == "no":
        return var_val
    if ctype == "nc":
        return not var_val
    if ctype == "pos":
        # Rising edge: True only on 0→1 transition
        return var_val and not prev_val
    if ctype == "neg":
        # Falling edge: True only on 1→0 transition
        return not var_val and prev_val
    # Unknown type: treat as NO
    return var_val


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute(
    rung: Rung,
    variables: dict[str, bool],
    prev_variables: Optional[dict[str, bool]] = None,
    contact_types: Optional[dict[int, str]] = None,
) -> PowerFlow:
    """Evaluate the power flow for a single LD rung.

    Parameters
    ----------
    rung:
        The PLCopen AST rung to evaluate.
    variables:
        Current variable snapshot: ``{name: bool_value}``.  Missing
        variables default to ``False``.
    prev_variables:
        Variable snapshot from the *previous* scan cycle.  Required only
        when rising- or falling-edge contacts are present.  Defaults to an
        empty dict (all variables previously ``False``).
    contact_types:
        Optional override mapping ``{local_id: type_string}`` where
        *type_string* is one of ``'no'``, ``'nc'``, ``'pos'``, ``'neg'``.
        When absent for a contact, the type is inferred from
        ``contact.negated`` (``False`` → ``'no'``, ``True`` → ``'nc'``).

    Returns
    -------
    PowerFlow
        Energised state for every element and inter-element wire in the
        rung.
    """
    if prev_variables is None:
        prev_variables = {}
    if contact_types is None:
        contact_types = {}

    flow = PowerFlow()

    # ------------------------------------------------------------------
    # 1. Collect all elements into typed buckets
    # ------------------------------------------------------------------
    lpr = rung.left_power_rail
    rpr = rung.right_power_rail
    contacts = list(rung.contacts)
    coils = list(rung.coils)
    fbs = list(rung.fb_instances)

    # ------------------------------------------------------------------
    # 2. Build an ordered column list
    #
    #    Each "column" is a list of (local_id, element) pairs at the same
    #    x-position.  The left power rail anchors column x = -infinity
    #    (always first); the right power rail anchors x = +infinity (last).
    #
    #    Middle elements (contacts, coils, FBs) are sorted ascending by x.
    # ------------------------------------------------------------------

    # Combine non-rail elements and sort by x
    middle: list[tuple[int, Contact | Coil | FBInstance]] = []
    for c in contacts:
        middle.append((_x_of(c), c))
    for c in coils:
        middle.append((_x_of(c), c))
    for fb in fbs:
        middle.append((_x_of(fb), fb))

    # Stable sort by x
    middle.sort(key=lambda t: t[0])

    # Group into columns: list of list[(x, elem)]
    columns: list[list[tuple[int, Contact | Coil | FBInstance]]] = []
    for item in middle:
        if columns and columns[-1][0][0] == item[0]:
            columns[-1].append(item)
        else:
            columns.append([item])

    # ------------------------------------------------------------------
    # 3. Evaluate power column by column, tracking per-element results
    # ------------------------------------------------------------------

    # Start: the left power rail supplies power unconditionally
    lpr_id = lpr.local_id if lpr is not None else -1
    power_in = True   # power entering the first column

    # We track the "previous node id" for wire generation
    prev_node_id: int = lpr_id

    for col in columns:
        # Evaluate each element in this column independently
        element_results: list[tuple[int, bool]] = []  # (local_id, passes_power)

        for _x, elem in col:
            if isinstance(elem, Contact):
                passes = _contact_passes(elem, variables, prev_variables, contact_types)
                effective = power_in and passes
                flow.contacts[elem.local_id] = effective
                element_results.append((elem.local_id, effective))

            elif isinstance(elem, Coil):
                # Coil is energised iff power reaches it
                energised = power_in
                flow.coils[elem.local_id] = energised
                element_results.append((elem.local_id, energised))

            elif isinstance(elem, FBInstance):
                # FB passes power through; the "output" records power_in
                flow.fb_outputs[elem.local_id] = power_in
                element_results.append((elem.local_id, power_in))

        # Parallel group output: OR of all element outputs
        if element_results:
            col_output = any(energised for _, energised in element_results)

            # Emit wires: each element is connected from prev_node_id
            # and to the representative next node (first element of next col).
            # For a parallel group, the "from" wire fans in from prev_node_id
            # and the "to" wire fans out to the next node.
            for eid, energised in element_results:
                flow.wires[(prev_node_id, eid)] = power_in  # wire carries power_in into element
                # Wire from element to "after column" will be added when we
                # know the next node; for now use a sentinel value.

            # Determine next-column representative for the "output" wire
            power_in = col_output
            prev_node_id = element_results[0][0]  # canonical "exit" node for the column

    # ------------------------------------------------------------------
    # 4. Connect final column to right power rail (if present)
    # ------------------------------------------------------------------
    if rpr is not None and prev_node_id != lpr_id:
        flow.wires[(prev_node_id, rpr.local_id)] = power_in
    elif rpr is not None:
        # No elements: LPR directly wired to RPR
        flow.wires[(lpr_id, rpr.local_id)] = True

    return flow
