"""
xref.py — Federated XRef / Hotlinks for multi-discipline IFC coordination.

ArchiCAD's killer feature: live-linked external IFC files that auto-update when
source changes. Enables struct/arch/MEP team coordination on a shared federated
model without merging files.

Public API
----------
XRefSpec       — per-reference descriptor (path, discipline, placement, hash)
XRefStatus     — freshness snapshot for one XRef
XRefManifest   — project-level collection of all XRefs

add_xref(manifest, spec) -> XRefManifest
check_xref_status(spec)  -> XRefStatus
refresh_xref(spec)       -> tuple[Body, XRefStatus]
remove_xref(manifest, source_path) -> XRefManifest
compose_federated_model(manifest)  -> dict[discipline, list[Body]]
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Discipline literal values
# ---------------------------------------------------------------------------

VALID_DISCIPLINES = frozenset({"structural", "mep", "architecture", "civil"})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class XRefSpec:
    """Descriptor for one federated external IFC reference."""

    source_path: str
    """Absolute or project-relative path to the .ifc file."""

    discipline: str
    """One of 'structural' | 'mep' | 'architecture' | 'civil'."""

    reference_origin_xyz_mm: tuple[float, float, float] = field(default=(0.0, 0.0, 0.0))
    """Translation offset in millimetres applied when composing the federated model."""

    reference_rotation_deg: float = 0.0
    """Z-axis rotation in degrees applied when composing the federated model."""

    last_loaded_hash: str = ""
    """SHA-256 hex digest of the source file at last successful load. Empty = never loaded."""

    def validate(self) -> None:
        if not self.source_path or not self.source_path.strip():
            raise ValueError("XRefSpec.source_path must not be empty")
        if self.discipline not in VALID_DISCIPLINES:
            raise ValueError(
                f"XRefSpec.discipline must be one of {sorted(VALID_DISCIPLINES)}, "
                f"got {self.discipline!r}"
            )
        if len(self.reference_origin_xyz_mm) != 3:
            raise ValueError("reference_origin_xyz_mm must be a 3-tuple")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "discipline": self.discipline,
            "reference_origin_xyz_mm": list(self.reference_origin_xyz_mm),
            "reference_rotation_deg": self.reference_rotation_deg,
            "last_loaded_hash": self.last_loaded_hash,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "XRefSpec":
        xyz = d.get("reference_origin_xyz_mm", [0.0, 0.0, 0.0])
        return cls(
            source_path=d["source_path"],
            discipline=d["discipline"],
            reference_origin_xyz_mm=tuple(float(v) for v in xyz),  # type: ignore[arg-type]
            reference_rotation_deg=float(d.get("reference_rotation_deg", 0.0)),
            last_loaded_hash=d.get("last_loaded_hash", ""),
        )


@dataclass
class XRefStatus:
    """Freshness snapshot for a single XRef."""

    is_stale: bool
    """True if the source file hash differs from last_loaded_hash, or if it has never been loaded."""

    last_loaded_iso: str
    """ISO-8601 UTC timestamp of the last successful load, or '' if never loaded."""

    current_file_hash: str
    """Current SHA-256 hex digest of the source file, or '' if file is missing."""

    num_elements: int
    """Number of IFC top-level elements detected in the source file (0 if unavailable)."""

    source_exists: bool
    """True when the source file is present on disk."""

    @property
    def status_label(self) -> str:
        """Human-readable status: 'current' | 'stale' | 'missing'."""
        if not self.source_exists:
            return "missing"
        if self.is_stale:
            return "stale"
        return "current"

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_stale": self.is_stale,
            "last_loaded_iso": self.last_loaded_iso,
            "current_file_hash": self.current_file_hash,
            "num_elements": self.num_elements,
            "source_exists": self.source_exists,
            "status_label": self.status_label,
        }


@dataclass
class XRefManifest:
    """Project-level collection of federated XRef entries."""

    refs: list[XRefSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"refs": [r.to_dict() for r in self.refs]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "XRefManifest":
        return cls(refs=[XRefSpec.from_dict(r) for r in d.get("refs", [])])

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, s: str) -> "XRefManifest":
        return cls.from_dict(json.loads(s))


# ---------------------------------------------------------------------------
# Body stub — used when kerf_cad_core is not available
# ---------------------------------------------------------------------------

@dataclass
class _BodyStub:
    """Minimal stand-in for kerf_cad_core Body when the kernel is absent."""

    source_path: str
    discipline: str
    elements: list[dict[str, Any]] = field(default_factory=list)
    origin_xyz_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg: float = 0.0

    def __repr__(self) -> str:
        return (
            f"<BodyStub discipline={self.discipline!r} "
            f"elements={len(self.elements)} src={self.source_path!r}>"
        )


# Try importing the real Body; fall back to stub so module is hermetically testable.
try:
    from kerf_cad_core.body import Body  # type: ignore
except ImportError:
    Body = _BodyStub  # type: ignore[misc,assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of the file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_ifc_elements(path: Path) -> int:
    """
    Return a lightweight element count from an IFC file without fully parsing it.

    Counts lines that start with '#N=' in the DATA section.  This is intentionally
    fast and dependency-free — no ifcopenshell required.
    """
    count = 0
    in_data = False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.upper() == "DATA;":
                    in_data = True
                    continue
                if stripped.upper() == "ENDSEC;":
                    in_data = False
                    continue
                if in_data and stripped.startswith("#"):
                    count += 1
    except OSError:
        pass
    return count


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def add_xref(manifest: XRefManifest, spec: XRefSpec) -> XRefManifest:
    """
    Add *spec* to *manifest*, replacing any existing entry for the same source_path.

    Parameters
    ----------
    manifest : XRefManifest
    spec     : XRefSpec — the reference to add (validated before insertion)

    Returns
    -------
    XRefManifest — a new manifest with *spec* added or updated.
    """
    spec.validate()
    new_refs = [r for r in manifest.refs if r.source_path != spec.source_path]
    new_refs.append(spec)
    return XRefManifest(refs=new_refs)


def check_xref_status(spec: XRefSpec) -> XRefStatus:
    """
    Compare the stored hash in *spec* against the current file on disk.

    Does not modify *spec*. No IFC parsing is performed — only a fast
    SHA-256 digest of the raw bytes.

    Parameters
    ----------
    spec : XRefSpec

    Returns
    -------
    XRefStatus
    """
    path = Path(spec.source_path)
    if not path.exists():
        return XRefStatus(
            is_stale=True,
            last_loaded_iso=spec.last_loaded_hash and "" or "",
            current_file_hash="",
            num_elements=0,
            source_exists=False,
        )

    current_hash = _sha256_file(path)
    never_loaded = not spec.last_loaded_hash
    is_stale = never_loaded or (current_hash != spec.last_loaded_hash)
    num_elements = _count_ifc_elements(path)

    return XRefStatus(
        is_stale=is_stale,
        last_loaded_iso="",          # last_loaded timestamp not stored on spec; callers set it
        current_file_hash=current_hash,
        num_elements=num_elements,
        source_exists=True,
    )


def refresh_xref(spec: XRefSpec) -> tuple[Any, XRefStatus]:
    """
    Re-import the IFC file at *spec.source_path*, update *spec.last_loaded_hash*,
    and return (body, status).

    The IFC file is read with ifcopenshell when available; otherwise a lightweight
    stub body is created from the raw element count so the function remains testable
    without IfcOpenShell.

    Parameters
    ----------
    spec : XRefSpec — modified in-place: last_loaded_hash is updated.

    Returns
    -------
    (Body | _BodyStub, XRefStatus)

    Raises
    ------
    FileNotFoundError  — source file is missing
    RuntimeError       — file cannot be parsed
    """
    path = Path(spec.source_path)
    if not path.exists():
        raise FileNotFoundError(f"XRef source not found: {spec.source_path}")

    current_hash = _sha256_file(path)
    num_elements = 0

    # Attempt full IFC parse via ifcopenshell
    elements: list[dict[str, Any]] = []
    try:
        import ifcopenshell  # type: ignore
        ifc_file = ifcopenshell.open(str(path))
        # Collect all product entities as lightweight dicts
        for product in ifc_file.by_type("IfcProduct"):
            elements.append({
                "global_id": getattr(product, "GlobalId", ""),
                "ifc_type":  product.is_a(),
                "name":      str(getattr(product, "Name", "") or ""),
            })
        num_elements = len(elements)
    except ImportError:
        # ifcopenshell not installed — count lines only
        num_elements = _count_ifc_elements(path)
        elements = [{"index": i} for i in range(num_elements)]
    except Exception as exc:
        raise RuntimeError(f"Failed to parse IFC file {spec.source_path}: {exc}") from exc

    # Build body
    body = Body(  # type: ignore[call-arg]
        source_path=spec.source_path,
        discipline=spec.discipline,
        elements=elements,
        origin_xyz_mm=tuple(spec.reference_origin_xyz_mm),  # type: ignore[arg-type]
        rotation_deg=spec.reference_rotation_deg,
    )

    # Update spec in-place
    spec.last_loaded_hash = current_hash

    status = XRefStatus(
        is_stale=False,
        last_loaded_iso=_now_iso(),
        current_file_hash=current_hash,
        num_elements=num_elements,
        source_exists=True,
    )
    return body, status


def remove_xref(manifest: XRefManifest, source_path: str) -> XRefManifest:
    """
    Return a new manifest with the entry for *source_path* removed.

    A no-op if *source_path* is not in the manifest.

    Parameters
    ----------
    manifest    : XRefManifest
    source_path : str

    Returns
    -------
    XRefManifest
    """
    return XRefManifest(refs=[r for r in manifest.refs if r.source_path != source_path])


def compose_federated_model(manifest: XRefManifest) -> dict[str, list[Any]]:
    """
    Refresh all XRefs in *manifest* and return a dict mapping discipline to list of bodies.

    Entries whose source file is missing are skipped with a logged warning.
    If ifcopenshell is unavailable, stub bodies are produced via the lightweight path.

    Parameters
    ----------
    manifest : XRefManifest

    Returns
    -------
    dict[str, list[Body | _BodyStub]]
        Keys are discipline strings (e.g. 'structural', 'mep', …).
        Values are lists of body objects, one per successfully loaded XRef of that discipline.
    """
    result: dict[str, list[Any]] = {}
    for spec in manifest.refs:
        try:
            body, _ = refresh_xref(spec)
            result.setdefault(spec.discipline, []).append(body)
        except FileNotFoundError:
            logger.warning("compose_federated_model: missing file %s — skipped", spec.source_path)
        except Exception as exc:
            logger.warning("compose_federated_model: failed to load %s: %s — skipped", spec.source_path, exc)
    return result
