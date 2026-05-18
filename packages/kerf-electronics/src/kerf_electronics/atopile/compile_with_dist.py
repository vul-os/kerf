"""compile_with_dist.py — atopile compile + distributor part resolution.

Entry point::

    from kerf_electronics.atopile.compile_with_dist import compile_with_distributor
    circuit_json = compile_with_distributor(source_text, dist_mode='mock')

Wraps :func:`compile_ato` and post-processes every ``source_component``
record by calling :func:`resolve_component` from the library bridge.

On a successful resolution the component record is augmented with::

    {
        "distributor_part_number": "C25076",
        "distributor_url": "https://...",
        "manufacturer": "YAGEO",
        "lcsc_part": "C25076",
    }

On an unresolved component::

    {
        "warnings": ["unresolved"],
    }

The Circuit JSON schema is preserved; only ``source_component`` records are
touched.  All other record types (source_net, pcb_component, pcb_smtpad,
source_trace) are passed through unchanged.
"""
from __future__ import annotations

import logging
import re
from typing import List, Literal, Optional

from .compile import compile_ato
from .library import (
    MockCatalogue,
    LiveCatalogue,
    DistributorCatalogue,
    resolve_component,
    set_catalogue,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

DistMode = Literal["mock", "live"]


def compile_with_distributor(
    source: str,
    *,
    top_module: Optional[str] = None,
    dist_mode: DistMode = "mock",
    catalogue: Optional[DistributorCatalogue] = None,
) -> List[dict]:
    """Compile a `.ato` source string to Circuit JSON with distributor part refs.

    Parameters
    ----------
    source:
        The text of a `.ato` file.
    top_module:
        Name of the module block to compile.  If *None*, the first
        ``module`` block found is used.
    dist_mode:
        ``'mock'`` (default) — use the in-memory fixture catalogue (no network).
        ``'live'`` — use the live LCSC / JLCPCB distributor registry.
    catalogue:
        Optional :class:`DistributorCatalogue` instance to inject directly
        (overrides *dist_mode*).  Primarily for testing.

    Returns
    -------
    A list of Circuit JSON dicts.  ``source_component`` records are
    augmented with distributor metadata; all other records are unchanged.

    Raises
    ------
    ValueError
        If no module block is found in the source (propagated from
        :func:`compile_ato`).
    """
    # Step 1: Standard compile
    circuit_json: List[dict] = compile_ato(source, top_module=top_module)

    # Step 2: Set up the catalogue
    if catalogue is not None:
        set_catalogue(catalogue)
    elif dist_mode == "live":
        set_catalogue(LiveCatalogue())
    else:
        # mock mode — try the default fixture; fall back to empty catalogue
        try:
            set_catalogue(MockCatalogue.from_default_fixture())
        except FileNotFoundError:
            logger.warning(
                "compile_with_distributor: fixture not found; "
                "source_component records will be unresolved"
            )
            set_catalogue(None)

    # Step 3: Walk and enrich source_component records
    try:
        circuit_json = _enrich_components(circuit_json)
    finally:
        # Always restore the catalogue to None so we don't leak state
        set_catalogue(None)

    return circuit_json


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _component_type_from_footprint(footprint: str) -> str:
    """Derive a canonical part_type string from a KiCad footprint identifier."""
    fp_lower = footprint.lower()
    if "resistor" in fp_lower or ":r" in fp_lower:
        return "Resistor"
    if "capacitor" in fp_lower or ":c" in fp_lower:
        return "Capacitor"
    if "led" in fp_lower:
        return "LED"
    if "inductor" in fp_lower or ":l" in fp_lower:
        return "Inductor"
    if "transistor" in fp_lower or "nmos" in fp_lower or "pmos" in fp_lower:
        return "Transistor"
    if "diode" in fp_lower or ":d" in fp_lower:
        return "Diode"
    return ""


def _build_spec(record: dict) -> dict:
    """Build a resolve_component spec dict from a source_component record.

    Extracts ``part``, ``value``, and ``package`` from the compiled record.
    The ``part`` key is derived from the footprint field (e.g. ``Device:R``
    → ``Resistor``).

    Values are normalised to strip trailing base-unit letters so that
    library.parse_value can handle them.  Examples:
        "10kohm" → "10k"
        "100nF"  → "100n"
        "4.7uH"  → "4.7u"
        "1k"     → "1k"  (unchanged)
    """
    footprint = record.get("footprint", "")
    value = record.get("value", "") or ""
    part_type = _component_type_from_footprint(footprint)

    spec: dict = {}
    if part_type:
        spec["part"] = part_type
    if value:
        spec["value"] = _normalise_value(value)
    return spec


# Base units to strip from the end of a value string.
_BASE_UNIT_RE = re.compile(
    r"^(?P<si>[0-9]+(?:\.[0-9]+)?[fFpPnNuUmkKMGT]?)(?:ohm|Ohm|OHM|F|H|V|A|W|Hz)$"
)


def _normalise_value(raw: str) -> str:
    """Strip trailing base-unit suffix so parse_value can handle the string.

    "10kohm" → "10k",  "100nF" → "100n",  "4.7uH" → "4.7u",  "1k" → "1k"
    """
    raw = raw.strip()
    m = _BASE_UNIT_RE.match(raw)
    if m:
        return m.group("si")
    return raw


def _enrich_components(circuit_json: List[dict]) -> List[dict]:
    """Post-process the circuit JSON list, enriching source_component entries."""
    enriched: List[dict] = []
    for record in circuit_json:
        if not isinstance(record, dict) or record.get("type") != "source_component":
            enriched.append(record)
            continue

        spec = _build_spec(record)
        result = resolve_component(spec)

        new_record = dict(record)  # shallow copy — preserve all existing keys

        if result.get("resolved"):
            lcsc_id = result.get("lcsc_id", "")
            new_record["distributor_part_number"] = lcsc_id
            new_record["distributor_url"] = result.get("datasheet_url", "")
            new_record["manufacturer"] = result.get("mfr_part", "")
            new_record["lcsc_part"] = lcsc_id
        else:
            # Unresolved — attach a warning; do NOT raise
            warnings = list(new_record.get("warnings", []))
            warnings.append("unresolved")
            new_record["warnings"] = warnings
            logger.debug(
                "compile_with_distributor: unresolved component %r: %s",
                record.get("name", "?"),
                result.get("warning", ""),
            )

        enriched.append(new_record)

    return enriched
