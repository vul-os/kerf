"""
kerf_plm.change_notification — ECO Notification Distribution (ISO 10007 §6.2 + APQP §3).

HONEST FLAG
-----------
This module produces a *recipient list* — it does NOT send emails, messages, or
any notifications.  The caller is responsible for routing the returned
``NotificationReport`` to their notification delivery layer.

Standards basis
---------------
* ISO 10007:2003 §6.2 — "Configuration change management: Notification and
  distribution" — specifies that approved changes shall be distributed to all
  affected functions with sufficient lead time.
* APQP "Production Part Approval Process" (PPAP) §3 — requires supplier
  notification and re-submission of PPAP documentation whenever a design record
  or process change affects form, fit, or function.

Change classification (ISO 10007 §5.1)
---------------------------------------
* Class A (Critical / Major) — affects safety, regulatory compliance, or key
  product characteristics.  Requires Quality + Manufacturing + Supplier
  notification regardless of change type.
* Class B (Significant) — functional change that does not rise to Class A;
  affects fit/form/function.  Requires Engineering + Manufacturing notification;
  Quality if process spec changed.
* Class C (Minor / Administrative) — documentation correction, cosmetic change,
  or no effect on fit/form/function.  Engineering + Document Control only.

Stakeholder roles
-----------------
* engineering       — owner of the affected part / assembly; reviews every change.
* supplier          — external supplier of the part; notified when PPAP renewal
                      is triggered (Class A/B dimension, material, process changes).
* manufacturing_lead — lead for the manufacturing route; notified when process
                       specifications are revised or the part tolerance changes.
* quality           — QA team; notified for Class A, Class B functional changes,
                       PPAP renewals, and dimension/tolerance changes.
* document_control  — document-control team; always notified for revision
                       packaging (any ECO line).

Urgency levels (per APQP §3 timing guidance)
---------------------------------------------
* HIGH   — action required before the effectivity date (e.g. PPAP, safety review).
* NORMAL — action required within normal process lead time.
* LOW    — informational; no action deadline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Urgency(str, Enum):
    """Notification urgency level per APQP §3 timing guidance."""
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class ChangeClass(str, Enum):
    """ISO 10007 §5.1 change classification."""
    CLASS_A = "class_a"   # Critical / Major — safety, regulatory, key characteristic
    CLASS_B = "class_b"   # Significant — functional fit/form/function
    CLASS_C = "class_c"   # Minor / Administrative — no effect on fit/form/function


class ChangeType(str, Enum):
    """Type of change on an ECO line item."""
    DIMENSION    = "dimension"      # dimensional tolerance change
    MATERIAL     = "material"       # material specification change
    PROCESS_SPEC = "process_spec"   # manufacturing / process specification change
    DRAWING      = "drawing"        # drawing revision only (no geometry change)
    DOCUMENT     = "document"       # documentation / administrative
    FINISH       = "finish"         # surface finish / coating change
    OTHER        = "other"          # catch-all


# ---------------------------------------------------------------------------
# Input data-classes
# ---------------------------------------------------------------------------

@dataclass
class EcoLineItem:
    """A single line item within an Engineering Change Order.

    Attributes
    ----------
    part_id:
        The part number being changed, e.g. ``'PN-12345'``.
    rev_from:
        Current revision, e.g. ``'A'``.
    rev_to:
        Target revision after the change, e.g. ``'B'``.
    change_class:
        ISO 10007 §5.1 classification.  Defaults to CLASS_B.
    change_types:
        One or more ``ChangeType`` values describing what changed.
    description:
        Free-text description of the change.
    """
    part_id: str
    rev_from: str
    rev_to: str
    change_class: ChangeClass = ChangeClass.CLASS_B
    change_types: list[ChangeType] = field(default_factory=list)
    description: str = ""


@dataclass
class PartRecord:
    """PLM part record linking a part to its owners.

    Attributes
    ----------
    part_id:
        Part number.
    owner_team:
        Engineering team or individual responsible, e.g. ``'@design-team'``.
    suppliers:
        List of supplier names or IDs, e.g. ``['ACME Corp']``.
    manufacturing_routes:
        List of manufacturing route IDs; non-empty signals a process spec
        exists for this part.
    """
    part_id: str
    owner_team: str = ""
    suppliers: list[str] = field(default_factory=list)
    manufacturing_routes: list[str] = field(default_factory=list)


@dataclass
class PlmData:
    """Container for PLM product-structure and stakeholder data.

    Attributes
    ----------
    parts:
        Mapping of part_id → ``PartRecord``.
    quality_team:
        Identifier for the quality team, e.g. ``'@quality-team'``.
    document_control_team:
        Identifier for document control, e.g. ``'@doc-control'``.
    """
    parts: dict[str, PartRecord] = field(default_factory=dict)
    quality_team: str = "@quality-team"
    document_control_team: str = "@doc-control"


# ---------------------------------------------------------------------------
# Output data-classes
# ---------------------------------------------------------------------------

@dataclass
class Notification:
    """A single notification entry for one stakeholder regarding one ECO line.

    Attributes
    ----------
    part_id:
        Part number this notification relates to.
    stakeholder:
        Identifier of the stakeholder (team name, supplier name, etc.).
    role:
        Functional role: ``engineering``, ``supplier``, ``manufacturing_lead``,
        ``quality``, or ``document_control``.
    reason:
        Human-readable rationale, citing the applicable standard where relevant.
    urgency:
        ``Urgency.HIGH``, ``Urgency.NORMAL``, or ``Urgency.LOW``.
    ppap_renewal_required:
        ``True`` if the supplier must re-submit PPAP documentation per APQP §3.
    """
    part_id: str
    stakeholder: str
    role: str
    reason: str
    urgency: Urgency
    ppap_renewal_required: bool = False


@dataclass
class NotificationReport:
    """Aggregated notification distribution for an ECO.

    Attributes
    ----------
    eco_id:
        The ECO identifier.
    notifications:
        Flat list of all ``Notification`` items generated across all ECO lines.
    honest_flag:
        Always ``True``; reminds callers this is a recipient list, not a
        delivery confirmation.

    Notes
    -----
    Use ``by_part()`` or ``by_stakeholder()`` for structured iteration.
    Does NOT send any notifications — caller must route to delivery layer.
    """
    eco_id: str
    notifications: list[Notification] = field(default_factory=list)
    honest_flag: bool = True  # recipient list only — no notifications sent

    def by_part(self) -> dict[str, list[Notification]]:
        """Return notifications grouped by part_id."""
        result: dict[str, list[Notification]] = {}
        for n in self.notifications:
            result.setdefault(n.part_id, []).append(n)
        return result

    def by_stakeholder(self) -> dict[str, list[Notification]]:
        """Return notifications grouped by stakeholder identifier."""
        result: dict[str, list[Notification]] = {}
        for n in self.notifications:
            result.setdefault(n.stakeholder, []).append(n)
        return result


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

# Change types that trigger PPAP renewal per APQP §3 §3.3
_PPAP_TRIGGER_TYPES: frozenset[ChangeType] = frozenset({
    ChangeType.DIMENSION,
    ChangeType.MATERIAL,
    ChangeType.PROCESS_SPEC,
    ChangeType.FINISH,
})

# Change types that require manufacturing-lead notification
_MANUFACTURING_TRIGGER_TYPES: frozenset[ChangeType] = frozenset({
    ChangeType.PROCESS_SPEC,
    ChangeType.DIMENSION,
    ChangeType.MATERIAL,
    ChangeType.FINISH,
})

# Change types that require quality notification
_QUALITY_TRIGGER_TYPES: frozenset[ChangeType] = frozenset({
    ChangeType.DIMENSION,
    ChangeType.MATERIAL,
    ChangeType.PROCESS_SPEC,
    ChangeType.FINISH,
})


def _ppap_required(line: EcoLineItem) -> bool:
    """Return True if PPAP renewal is required per APQP §3 §3.3.

    PPAP is triggered when:
    * Change class is A or B (not minor), AND
    * The change type includes a dimension, material, process, or finish change,
      OR the change class is A (always triggers PPAP for Class A).

    Reference: APQP PPAP §3 — "Any design record or process change affecting
    form, fit, or function, including all changes of subcontractors' design
    records, requires prior customer approval."
    """
    if line.change_class == ChangeClass.CLASS_C:
        return False
    if line.change_class == ChangeClass.CLASS_A:
        return True  # Class A always triggers PPAP per APQP §3
    # Class B: trigger only on specific change types
    return bool(set(line.change_types) & _PPAP_TRIGGER_TYPES)


def _quality_required(line: EcoLineItem) -> bool:
    """Return True if quality team notification is required.

    Triggered by:
    * Class A (always) per ISO 10007 §6.2.
    * Class B with dimension/material/process/finish change type.
    * PPAP renewal required (implies quality sign-off).
    """
    if line.change_class == ChangeClass.CLASS_A:
        return True
    if line.change_class == ChangeClass.CLASS_C:
        return False
    return bool(set(line.change_types) & _QUALITY_TRIGGER_TYPES)


def _manufacturing_required(line: EcoLineItem, part: Optional[PartRecord]) -> bool:
    """Return True if manufacturing-lead notification is required.

    Triggered by:
    * Class A (always).
    * Class B with process-spec, dimension, material, or finish change type.
    * Part has manufacturing routes defined (process documentation exists).
    """
    if line.change_class == ChangeClass.CLASS_A:
        return True
    if line.change_class == ChangeClass.CLASS_C:
        return False
    has_process = bool(part and part.manufacturing_routes)
    return bool(set(line.change_types) & _MANUFACTURING_TRIGGER_TYPES) or has_process


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_notification_distribution(
    eco_id: str,
    eco_lines: list[EcoLineItem],
    plm_data: PlmData,
) -> NotificationReport:
    """Compute the full notification distribution for an ECO.

    For each ECO line item the function identifies every stakeholder that
    must be notified, the reason (citing ISO 10007 §6.2 or APQP §3 where
    applicable), and the urgency level.

    Parameters
    ----------
    eco_id:
        Identifier of the Engineering Change Order, e.g. ``'ECO-0042'``.
    eco_lines:
        List of ``EcoLineItem`` objects — each represents one part revision
        change within the ECO.
    plm_data:
        ``PlmData`` container with part records, owner teams, supplier lists,
        manufacturing routes, and stakeholder identifiers.

    Returns
    -------
    NotificationReport
        Aggregated list of ``Notification`` records.  The report's
        ``honest_flag`` attribute is always ``True`` — this is a *recipient
        list*, not a delivery confirmation.  No actual notifications are sent.

    Examples
    --------
    Depth-bar scenario (PN-12345 Rev A → Rev B, dimension change, Class B):

    >>> from kerf_plm.change_notification import (
    ...     EcoLineItem, PartRecord, PlmData, ChangeClass, ChangeType,
    ...     compute_notification_distribution,
    ... )
    >>> line = EcoLineItem(
    ...     part_id="PN-12345",
    ...     rev_from="A",
    ...     rev_to="B",
    ...     change_class=ChangeClass.CLASS_B,
    ...     change_types=[ChangeType.DIMENSION],
    ...     description="Shaft diameter tolerance tightened from ±0.1 to ±0.05 mm",
    ... )
    >>> part = PartRecord(
    ...     part_id="PN-12345",
    ...     owner_team="@design-team",
    ...     suppliers=["ACME Corp"],
    ...     manufacturing_routes=["ROUTE-LATHE-01"],
    ... )
    >>> plm = PlmData(parts={"PN-12345": part})
    >>> report = compute_notification_distribution("ECO-0042", [line], plm)
    >>> {n.role: n.urgency.value for n in report.notifications}
    {'engineering': 'normal', 'supplier': 'high', 'manufacturing_lead': 'normal', 'quality': 'high', 'document_control': 'normal'}

    References
    ----------
    ISO 10007:2003 §6.2 — Configuration change notification and distribution.
    APQP PPAP §3 — Production Part Approval Process, change notification obligations.
    """
    notifications: list[Notification] = []

    for line in eco_lines:
        part = plm_data.parts.get(line.part_id)

        # ------------------------------------------------------------------
        # 1. Engineering (owner) — notified for every ECO line (ISO 10007 §6.2)
        # ------------------------------------------------------------------
        owner = part.owner_team if part else "@engineering"
        notifications.append(Notification(
            part_id=line.part_id,
            stakeholder=owner,
            role="engineering",
            reason=(
                f"Owner review required: {line.part_id} Rev {line.rev_from} → "
                f"Rev {line.rev_to} (ISO 10007 §6.2 — all affected functions "
                f"must be notified of approved changes)."
            ),
            urgency=Urgency.NORMAL,
        ))

        # ------------------------------------------------------------------
        # 2. Suppliers — PPAP renewal per APQP §3
        # Class C changes do not require supplier notification (no PPAP, no
        # fit/form/function impact by definition).
        # ------------------------------------------------------------------
        ppap = _ppap_required(line)
        if part and part.suppliers and line.change_class != ChangeClass.CLASS_C:
            for supplier in part.suppliers:
                notifications.append(Notification(
                    part_id=line.part_id,
                    stakeholder=supplier,
                    role="supplier",
                    reason=(
                        f"{'PPAP renewal required' if ppap else 'Change notification'}: "
                        f"{line.part_id} Rev {line.rev_from} → Rev {line.rev_to}. "
                        f"Change class: {line.change_class.value}. "
                        f"APQP §3 — any design-record or process change affecting "
                        f"form, fit, or function requires prior customer approval."
                    ),
                    urgency=Urgency.HIGH if ppap else Urgency.NORMAL,
                    ppap_renewal_required=ppap,
                ))

        # ------------------------------------------------------------------
        # 3. Manufacturing lead — process doc revision
        # ------------------------------------------------------------------
        if _manufacturing_required(line, part):
            mfg_lead = "@manufacturing-lead"
            if part and part.manufacturing_routes:
                routes_str = ", ".join(part.manufacturing_routes)
                reason = (
                    f"Process documentation revision required for routes [{routes_str}]: "
                    f"{line.part_id} Rev {line.rev_from} → Rev {line.rev_to}. "
                    f"ISO 10007 §6.2 — manufacturing functions must receive approved "
                    f"change documentation before effectivity date."
                )
            else:
                reason = (
                    f"Manufacturing impact review required: {line.part_id} "
                    f"Rev {line.rev_from} → Rev {line.rev_to} "
                    f"({', '.join(ct.value for ct in line.change_types)} change). "
                    f"ISO 10007 §6.2."
                )
            # Urgency: HIGH if Class A (process stop potential), else NORMAL
            urgency = Urgency.HIGH if line.change_class == ChangeClass.CLASS_A else Urgency.NORMAL
            notifications.append(Notification(
                part_id=line.part_id,
                stakeholder=mfg_lead,
                role="manufacturing_lead",
                reason=reason,
                urgency=urgency,
            ))

        # ------------------------------------------------------------------
        # 4. Quality — ISO 10007 Class A/B threshold + PPAP
        # ------------------------------------------------------------------
        if _quality_required(line):
            quality_reason_parts = []
            if line.change_class == ChangeClass.CLASS_A:
                quality_reason_parts.append(
                    "ISO 10007 §5.1 Class A change — safety/regulatory review mandatory"
                )
            if ppap:
                quality_reason_parts.append("PPAP renewal requires quality sign-off (APQP §3)")
            if ChangeType.DIMENSION in line.change_types:
                quality_reason_parts.append("dimensional change affects key product characteristics")
            if ChangeType.MATERIAL in line.change_types:
                quality_reason_parts.append("material change may affect compliance certifications")
            if ChangeType.PROCESS_SPEC in line.change_types:
                quality_reason_parts.append("process-spec change requires inspection plan update")

            quality_urgency = Urgency.HIGH if (ppap or line.change_class == ChangeClass.CLASS_A) else Urgency.NORMAL
            notifications.append(Notification(
                part_id=line.part_id,
                stakeholder=plm_data.quality_team,
                role="quality",
                reason=(
                    f"Quality review: {line.part_id} Rev {line.rev_from} → Rev {line.rev_to}. "
                    + "; ".join(quality_reason_parts) + "."
                ),
                urgency=quality_urgency,
                ppap_renewal_required=ppap,
            ))

        # ------------------------------------------------------------------
        # 5. Document control — revision packaging for every ECO line
        # ------------------------------------------------------------------
        notifications.append(Notification(
            part_id=line.part_id,
            stakeholder=plm_data.document_control_team,
            role="document_control",
            reason=(
                f"Revision packaging required: {line.part_id} Rev {line.rev_from} → "
                f"Rev {line.rev_to}. Document control must archive the approved ECO "
                f"package and update the controlled document index (ISO 10007 §6.2)."
            ),
            urgency=Urgency.NORMAL,
        ))

    return NotificationReport(
        eco_id=eco_id,
        notifications=notifications,
        honest_flag=True,
    )


# ---------------------------------------------------------------------------
# Convenience: dict → dataclass constructors (for JSON/tool integration)
# ---------------------------------------------------------------------------

def eco_line_from_dict(d: dict) -> EcoLineItem:
    """Construct an ``EcoLineItem`` from a plain dictionary.

    Keys:
        part_id (str, required), rev_from (str), rev_to (str),
        change_class (str — 'class_a'|'class_b'|'class_c'), change_types
        (list[str]), description (str).
    """
    raw_class = d.get("change_class", "class_b")
    try:
        change_class = ChangeClass(raw_class)
    except ValueError:
        change_class = ChangeClass.CLASS_B

    change_types: list[ChangeType] = []
    for ct_str in d.get("change_types", []):
        try:
            change_types.append(ChangeType(ct_str))
        except ValueError:
            pass  # unknown type — skip gracefully

    return EcoLineItem(
        part_id=d["part_id"],
        rev_from=d.get("rev_from", ""),
        rev_to=d.get("rev_to", ""),
        change_class=change_class,
        change_types=change_types,
        description=d.get("description", ""),
    )


def plm_data_from_dict(d: dict) -> PlmData:
    """Construct a ``PlmData`` instance from a plain dictionary.

    Expected shape::

        {
          "parts": {
            "PN-12345": {
              "owner_team": "@design-team",
              "suppliers": ["ACME Corp"],
              "manufacturing_routes": ["ROUTE-01"]
            }
          },
          "quality_team": "@quality",
          "document_control_team": "@doc-control"
        }
    """
    parts: dict[str, PartRecord] = {}
    for pid, pdata in d.get("parts", {}).items():
        parts[pid] = PartRecord(
            part_id=pid,
            owner_team=pdata.get("owner_team", "@engineering"),
            suppliers=pdata.get("suppliers", []),
            manufacturing_routes=pdata.get("manufacturing_routes", []),
        )
    return PlmData(
        parts=parts,
        quality_team=d.get("quality_team", "@quality-team"),
        document_control_team=d.get("document_control_team", "@doc-control"),
    )
