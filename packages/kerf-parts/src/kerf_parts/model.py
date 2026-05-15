"""Kerf-native part representation.

We deliberately do NOT invent a new DB schema. Kerf already stores library
parts as ``files`` rows with ``kind = 'part'`` and a JSON body. The body
shape is defined by two existing pieces of the codebase:

  * ``kerf_api.tools.scaffold.run_create_part`` — the canonical ``.part``
    JSON: ``version, name, description, category, manufacturer, mpn, value,
    datasheet_url, distributors, metadata``.
  * ``kerf_imports.kicad_library`` — already emits, per part, the
    ``schematic_symbol`` / ``pcb_footprint`` / ``model_3d_paths`` /
    ``content_hash`` sub-objects, and ``kerf_core.db.queries.library`` reads
    parts back out of ``files.content::jsonb`` for the public library /
    BOM. Electronic library parts in Kerf therefore already carry these
    keys inside the ``.part`` JSON.

So a :class:`KerfPart` is just the union of those two shapes. ``to_part_doc()``
produces the exact JSON written into a ``kind='part'`` file — no migration,
no new kind, fully consumable by the existing material/library/BOM tooling.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class KerfPart:
    name: str
    category: str = ""
    description: str = ""
    manufacturer: str = ""
    mpn: str = ""
    value: str = ""
    datasheet_url: str = ""
    # Electronic sub-objects (same shape kerf_imports.kicad_library emits).
    schematic_symbol: Optional[dict] = None
    pcb_footprint: Optional[dict] = None
    model_3d_paths: list[str] = field(default_factory=list)
    distributors: list[dict] = field(default_factory=list)
    # Free-form provenance (source repo, upstream license, in-repo path).
    metadata: dict[str, Any] = field(default_factory=dict)
    # Stable per-part hash for incremental, skip-unchanged seeding.
    content_hash: str = ""

    # Relative path the seeder will create inside the Parts Library project,
    # e.g. "KiCad/Symbols/Device/R.part". The adapter sets this.
    rel_path: str = ""

    def to_part_doc(self) -> dict:
        """The exact JSON body written to a ``kind='part'`` file."""
        doc: dict[str, Any] = {
            "version": 1,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "manufacturer": self.manufacturer,
            "mpn": self.mpn,
            "value": self.value,
            "datasheet_url": self.datasheet_url,
            "distributors": self.distributors,
            "metadata": self.metadata,
        }
        if self.schematic_symbol is not None:
            doc["schematic_symbol"] = self.schematic_symbol
        if self.pcb_footprint is not None:
            doc["pcb_footprint"] = self.pcb_footprint
        if self.model_3d_paths:
            doc["model_3d_paths"] = self.model_3d_paths
        return doc

    def ensure_hash(self) -> str:
        """Compute a deterministic content hash if not already set.

        Adapters that have a meaningful upstream hash (KiCad gives us a
        sha256 of the s-expr text) should set ``content_hash`` directly;
        otherwise we hash the serialized doc so re-seeding is incremental.
        """
        if not self.content_hash:
            body = json.dumps(self.to_part_doc(), sort_keys=True)
            self.content_hash = hashlib.sha256(body.encode()).hexdigest()
        return self.content_hash


def part_filename(name: str) -> str:
    """Sanitize a part name into a safe ``*.part`` leaf filename."""
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in name).strip("_")
    if not safe:
        safe = "part"
    if not safe.lower().endswith(".part"):
        safe += ".part"
    return safe
