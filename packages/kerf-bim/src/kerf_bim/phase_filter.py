"""
phase_filter.py — Renovation / Phase Management for BIM projects.

Implements ArchiCAD-style renovation phase management: tag elements as
Existing / New Construction / Demolish / Future / Alternate-A / Alternate-B,
then apply named layer-combination filters to control what's visible in each
drawing output (Existing Plan, Demolition Plan, New Construction Plan, etc.).

Public API
----------
PhaseTag          — enum of supported phase labels
ElementPhase      — per-element phase assignment record
PhaseFilter       — named visibility filter (layer combination)
PhaseFilterResult — output of applying a filter to an element list

apply_phase_filter          — apply a PhaseFilter to a list of ElementPhase records
validate_phase_consistency  — return list of human-readable inconsistency warnings
set_element_phase           — create / update an ElementPhase entry in a manifest dict
compute_phase_statistics    — count elements per PhaseTag
get_default_filters         — ArchiCAD-style default layer combinations
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# PhaseTag
# ---------------------------------------------------------------------------

class PhaseTag(str, Enum):
    """Renovation phase tag, mirroring ArchiCAD's element status model."""

    EXISTING = "existing"
    NEW_CONSTRUCTION = "new_construction"
    DEMOLISH = "demolish"
    FUTURE = "future"
    ALTERNATE_A = "alternate_a"
    ALTERNATE_B = "alternate_b"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ElementPhase:
    """Phase assignment for a single BIM element.

    Parameters
    ----------
    element_id:
        Unique element identifier (matches the 'id' field in a .bim document).
    primary_phase:
        The phase in which this element exists or is being introduced.
    demolish_phase:
        If set, the element will be demolished during this phase.
        Must be different from primary_phase.
    notes:
        Free-text annotation for the design team.
    """

    element_id: str
    primary_phase: PhaseTag
    demolish_phase: Optional[PhaseTag] = None
    notes: str = ""


@dataclass
class PhaseFilter:
    """Named visibility configuration (ArchiCAD "layer combination").

    Parameters
    ----------
    name:
        Human-readable filter name, e.g. "Demolition Plan".
    visible_phases:
        List of PhaseTag values for elements that should be fully visible.
    demolished_visible:
        When True, elements marked for demolition are shown as ghosts
        (dashed overrides in drawing output) rather than hidden entirely.
    future_visible:
        When True, elements in the FUTURE phase are shown (typically with
        a lighter linetype / colour override).
    """

    name: str
    visible_phases: list[PhaseTag] = field(default_factory=list)
    demolished_visible: bool = False
    future_visible: bool = False


@dataclass
class PhaseFilterResult:
    """Output of apply_phase_filter.

    Attributes
    ----------
    visible_element_ids:
        Elements fully shown under this filter.
    hidden_element_ids:
        Elements completely suppressed.
    demolished_ghost_ids:
        Elements shown as ghosts / with demolition linetype.
        Only populated when the filter has demolished_visible=True.
    """

    visible_element_ids: list[str] = field(default_factory=list)
    hidden_element_ids: list[str] = field(default_factory=list)
    demolished_ghost_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def apply_phase_filter(
    element_phases: list[ElementPhase],
    filter: PhaseFilter,
) -> PhaseFilterResult:
    """Apply a PhaseFilter to a list of ElementPhase records.

    Classification rules
    --------------------
    An element's visibility is determined by the combination of its
    primary_phase and demolish_phase against the filter's visible_phases set:

    1. If the element's primary_phase is in visible_phases → visible
       (subject to rules 2–4 below, which can demote it).
    2. If the element has a demolish_phase AND that phase is in visible_phases:
       - demolished_visible=True  → ghost
       - demolished_visible=False → hidden (demolished, not shown)
    3. If primary_phase == FUTURE and future_visible=False → hidden.
    4. Otherwise the element is hidden.

    The result is O(N) in the number of element_phases.
    """
    visible_phases_set = set(filter.visible_phases)

    visible: list[str] = []
    hidden: list[str] = []
    ghost: list[str] = []

    for ep in element_phases:
        eid = ep.element_id

        # Future shortcut
        if ep.primary_phase == PhaseTag.FUTURE and not filter.future_visible:
            hidden.append(eid)
            continue

        in_visible = ep.primary_phase in visible_phases_set

        if not in_visible:
            hidden.append(eid)
            continue

        # Element's primary phase is visible — check if it's being demolished
        # in a phase that is also within the filter window.
        if ep.demolish_phase is not None and ep.demolish_phase in visible_phases_set:
            if filter.demolished_visible:
                ghost.append(eid)
            else:
                hidden.append(eid)
            continue

        visible.append(eid)

    return PhaseFilterResult(
        visible_element_ids=visible,
        hidden_element_ids=hidden,
        demolished_ghost_ids=ghost,
    )


def validate_phase_consistency(element_phases: list[ElementPhase]) -> list[str]:
    """Return a list of human-readable inconsistency warnings.

    Checks performed
    ----------------
    - demolish_phase equals primary_phase (self-demolition).
    - primary_phase is DEMOLISH (should be expressed via demolish_phase).
    - demolish_phase is EXISTING (nothing can demolish the existing past).
    - demolish_phase is set but primary_phase is FUTURE (logically odd but
      allowed; flagged as a warning for design review).
    - Duplicate element_ids (same element tagged twice).
    """
    warnings: list[str] = []
    seen_ids: dict[str, int] = {}

    for i, ep in enumerate(element_phases):
        tag = f"element '{ep.element_id}'"

        # Track duplicates
        if ep.element_id in seen_ids:
            warnings.append(
                f"{tag}: duplicate element_id (also at index {seen_ids[ep.element_id]})"
            )
        else:
            seen_ids[ep.element_id] = i

        # Self-demolition
        if ep.demolish_phase is not None and ep.demolish_phase == ep.primary_phase:
            warnings.append(
                f"{tag}: demolish_phase equals primary_phase ({ep.primary_phase.value})"
            )

        # Primary set to DEMOLISH — use demolish_phase instead
        if ep.primary_phase == PhaseTag.DEMOLISH:
            warnings.append(
                f"{tag}: primary_phase='demolish' is ambiguous; "
                "use primary_phase='existing' + demolish_phase='demolish' instead"
            )

        # Demolish phase is EXISTING — makes no sense
        if ep.demolish_phase == PhaseTag.EXISTING:
            warnings.append(
                f"{tag}: demolish_phase='existing' is invalid; "
                "demolition must occur in a later phase"
            )

        # Future element flagged for demolition — unusual, worth a note
        if ep.primary_phase == PhaseTag.FUTURE and ep.demolish_phase is not None:
            warnings.append(
                f"{tag}: primary_phase='future' combined with demolish_phase "
                f"='{ep.demolish_phase.value}' — confirm design intent"
            )

    return warnings


def set_element_phase(
    element_id: str,
    phase: PhaseTag,
    manifest: dict,
    demolish_phase: Optional[PhaseTag] = None,
    notes: str = "",
) -> ElementPhase:
    """Create or update an ElementPhase entry inside a BIM manifest dict.

    The manifest is expected to contain an 'element_phases' list of dicts with
    keys matching ElementPhase fields.  The list is mutated in-place so that
    the caller can serialise the manifest back to JSON.

    Returns the new / updated ElementPhase.
    """
    ep = ElementPhase(
        element_id=element_id,
        primary_phase=phase,
        demolish_phase=demolish_phase,
        notes=notes,
    )

    phases_list: list[dict] = manifest.setdefault("element_phases", [])
    for i, entry in enumerate(phases_list):
        if entry.get("element_id") == element_id:
            phases_list[i] = _ep_to_dict(ep)
            return ep

    phases_list.append(_ep_to_dict(ep))
    return ep


def compute_phase_statistics(element_phases: list[ElementPhase]) -> dict[PhaseTag, int]:
    """Return a count of elements per PhaseTag (keyed by primary_phase).

    All PhaseTag values appear in the result even if the count is zero,
    so callers can always display a complete bar chart.
    """
    counts: dict[PhaseTag, int] = {tag: 0 for tag in PhaseTag}
    for ep in element_phases:
        counts[ep.primary_phase] += 1
    return counts


def get_default_filters() -> list[PhaseFilter]:
    """Return the four ArchiCAD-style default layer combinations.

    Filters
    -------
    "Existing Plan"
        Show only existing elements.  New construction and future hidden.

    "Demolition Plan"
        Show existing elements; demolished elements shown as ghosts.
        New construction hidden (not yet built at this drawing stage).

    "New Construction Plan"
        Show new_construction elements only.

    "Composite (All Phases)"
        Show every element including future and alternates.
        Demolished elements shown as ghosts.
    """
    return [
        PhaseFilter(
            name="Existing Plan",
            visible_phases=[PhaseTag.EXISTING],
            demolished_visible=False,
            future_visible=False,
        ),
        PhaseFilter(
            name="Demolition Plan",
            visible_phases=[PhaseTag.EXISTING, PhaseTag.DEMOLISH],
            demolished_visible=True,
            future_visible=False,
        ),
        PhaseFilter(
            name="New Construction Plan",
            visible_phases=[PhaseTag.NEW_CONSTRUCTION],
            demolished_visible=False,
            future_visible=False,
        ),
        PhaseFilter(
            name="Composite (All Phases)",
            visible_phases=[
                PhaseTag.EXISTING,
                PhaseTag.NEW_CONSTRUCTION,
                PhaseTag.DEMOLISH,
                PhaseTag.FUTURE,
                PhaseTag.ALTERNATE_A,
                PhaseTag.ALTERNATE_B,
            ],
            demolished_visible=True,
            future_visible=True,
        ),
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ep_to_dict(ep: ElementPhase) -> dict:
    return {
        "element_id": ep.element_id,
        "primary_phase": ep.primary_phase.value,
        "demolish_phase": ep.demolish_phase.value if ep.demolish_phase else None,
        "notes": ep.notes,
    }
