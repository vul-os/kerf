"""
Materials database — ICE v3 embodied-carbon factors.

Each entry holds:
  label                          — human-readable name
  embodied_carbon_kg_co2_per_kg  — kg CO₂-eq per kg (cradle-to-gate)
  recycled_content_pct           — typical % recycled input
  recyclability_pct              — end-of-life recyclability %
  category                       — broad material family
  aliases                        — alternate names used for fuzzy lookup
"""

from __future__ import annotations

import json
import pathlib
from typing import Optional

_DB_PATH = pathlib.Path(__file__).parent / "data" / "ice_v3.json"

_DB: Optional[dict] = None


def load_database() -> dict:
    """Load and cache the ICE v3 materials database. Returns the full dict."""
    global _DB
    if _DB is None:
        with open(_DB_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
        _DB = raw["materials"]
    return _DB


def list_materials() -> list[dict]:
    """Return all materials as a list of dicts (includes the key as 'id')."""
    db = load_database()
    return [{"id": k, **v} for k, v in db.items()]


def lookup_material(name: str) -> Optional[dict]:
    """
    Look up a material by key, label, or alias (case-insensitive).

    Returns the material dict (with 'id' set) or None if not found.
    """
    if not name:
        return None
    db = load_database()
    needle = name.strip().lower()

    # 1. exact key match
    if needle in db:
        return {"id": needle, **db[needle]}

    # 2. label match
    for key, entry in db.items():
        if entry["label"].lower() == needle:
            return {"id": key, **entry}

    # 3. alias match
    for key, entry in db.items():
        for alias in entry.get("aliases", []):
            if alias.lower() == needle:
                return {"id": key, **entry}

    # 4. substring match (longest alias that contains the needle wins)
    candidates = []
    for key, entry in db.items():
        if needle in entry["label"].lower():
            candidates.append((len(entry["label"]), key, entry))
        for alias in entry.get("aliases", []):
            if needle in alias.lower():
                candidates.append((len(alias), key, entry))

    if candidates:
        candidates.sort(key=lambda t: t[0])
        _, key, entry = candidates[0]
        return {"id": key, **entry}

    return None
