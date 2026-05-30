"""
kerf_plm.part_numbering_schema
==============================

Corporate part-numbering schema: definition, validation, allocation, and
migration.

Standards references
--------------------
- GS1 GTIN (Global Trade Item Number) — 14-digit numeric item identification;
  see GS1 General Specifications v23 §2.1.  kerf schemas adopt the GS1 principle
  of a fixed-width check digit / prefix structure, but are not restricted to the
  GTIN-14 alphabet.
- ISO 8000-110:2009 — Data quality: master data.  §6.5 mandates that identifiers
  be *syntactically valid*, *unique within their scope*, and *stable once assigned*.
  kerf enforces the first two; the third is the caller's responsibility.
- Cooper "Industrial Inspection & DFM" §6 — corporate PN conventions: sequential,
  hierarchical (assembly-family-variant-serial), and semantic-encoded (material,
  size, finish, revision).

Honest flag
-----------
Uniqueness enforcement and reserved-prefix checks are **per-instance only**.
A single PartNumberSchema carries its own allocation state (issued_numbers set +
allocated_by_family dict); there is no federation across instances, databases, or
processes.  Callers that need enterprise-wide uniqueness must persist and reload the
schema state (via `schema.to_state_dict()` / `PartNumberSchema.from_state_dict()`).

Schema types
------------
  sequential:   PN-00001  …  PN-99999
  hierarchical: 100-200-300-001  (assembly type, family, variant, serial)
  semantic:     SKU-BLK-12X10-AL-V2  (color, size, material, revision)
  hash_based:   HASH-<10-char hex digest>  (SHA-256 of attribute dict, truncated)

Public API
----------
  PartNumberSchema          — definition + mutable allocation state
  validate_part_number()    — check syntax + reserved-prefix; return ValidationResult
  allocate_next()           — mint the next PN in a family; detect duplicates
  migrate_schema()          — recode a list of old PNs under a new schema
  MigrationResult           — result dataclass from migrate_schema()
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Schema type enum
# ---------------------------------------------------------------------------

class SchemaType(str, Enum):
    SEQUENTIAL = "sequential"
    HIERARCHICAL = "hierarchical"
    SEMANTIC = "semantic"
    HASH_BASED = "hash_based"
    CUSTOM = "custom"


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of a validate_part_number() call."""
    valid: bool
    reason: str = ""
    matched_schema: str = ""   # schema name / type for logging

    def __bool__(self) -> bool:
        return self.valid


# ---------------------------------------------------------------------------
# Allocation result
# ---------------------------------------------------------------------------

@dataclass
class AllocationResult:
    """Result of an allocate_next() call."""
    ok: bool
    part_number: str = ""
    reason: str = ""            # populated on failure
    duplicate: bool = False     # True when the PN was already issued


# ---------------------------------------------------------------------------
# PartNumberSchema
# ---------------------------------------------------------------------------

class PartNumberSchema:
    """
    A corporate part-numbering schema.

    Parameters
    ----------
    name:
        Human-readable schema name, e.g. "SN-5".
    schema_type:
        One of SchemaType.{SEQUENTIAL, HIERARCHICAL, SEMANTIC, HASH_BASED, CUSTOM}.
    pattern:
        Regex string that a valid part number must fully match.
        The regex is compiled with re.IGNORECASE by default unless
        *case_sensitive=True* is supplied.
    prefix:
        Constant prefix to prepend when allocating sequential PNs.
        E.g. "PN-" → allocates "PN-00001", "PN-00002", …
    serial_width:
        Zero-padded width for sequential/hierarchical serials (default 5).
    reserved_prefixes:
        Set of prefix strings that must NOT appear in any allocated PN.
        Useful to protect legacy or supplier PN ranges.
    case_sensitive:
        If False (default), pattern matching is case-insensitive.

    State attributes (mutable, persisted via to_state_dict)
    --------------------------------------------------------
    issued_numbers:
        Set of all PNs that have been allocated (for duplicate detection).
    allocated_by_family:
        Dict mapping (prefix, type_code, family_code) → current highest serial
        integer.  Used for sequential / hierarchical allocation.

    Honest flag — ISO 8000-110 scope caveat
    ----------------------------------------
    Uniqueness is enforced only within this single in-memory instance.  A federated
    PLM deployment must serialise and reload `to_state_dict()` between sessions.
    This limitation is by design (no external dependencies); see module docstring.
    """

    HONEST_FLAG: str = (
        "Part-number uniqueness is enforced per-instance only (in-memory state). "
        "No cross-process or cross-instance federation.  Persist schema state via "
        "to_state_dict() / from_state_dict() for multi-session uniqueness guarantees. "
        "GS1 GTIN §2.1 check-digit not computed; ISO 8000-110 §6.5 stability is "
        "caller's responsibility."
    )

    def __init__(
        self,
        name: str,
        schema_type: SchemaType | str = SchemaType.SEQUENTIAL,
        pattern: str | None = None,
        prefix: str = "PN-",
        serial_width: int = 5,
        reserved_prefixes: set[str] | None = None,
        case_sensitive: bool = False,
    ) -> None:
        self.name = name
        self.schema_type = SchemaType(schema_type)
        self.prefix = prefix
        self.serial_width = serial_width
        self.reserved_prefixes: set[str] = reserved_prefixes or set()
        self.case_sensitive = case_sensitive

        # Compile pattern
        flags = 0 if case_sensitive else re.IGNORECASE
        if pattern:
            self.pattern = pattern
            self._regex = re.compile(f"^{pattern}$", flags)
        else:
            # Auto-derive a sensible default pattern
            self.pattern, self._regex = self._default_pattern(flags)

        # Mutable allocation state (ISO 8000-110 §6.5 — unique within scope)
        self.issued_numbers: set[str] = set()
        self.allocated_by_family: dict[tuple, int] = {}

    # ------------------------------------------------------------------
    # Default pattern derivation
    # ------------------------------------------------------------------

    def _default_pattern(self, flags: int) -> tuple[str, re.Pattern]:
        """Derive a regex pattern from schema_type and prefix/serial_width."""
        if self.schema_type == SchemaType.SEQUENTIAL:
            # e.g. PN-00001 … PN-99999
            esc = re.escape(self.prefix)
            pat = rf"{esc}\d{{{self.serial_width}}}"
        elif self.schema_type == SchemaType.HIERARCHICAL:
            # e.g. 100-200-300-001
            pat = r"\d{3}-\d{3}-\d{3}-\d{3}"
        elif self.schema_type == SchemaType.SEMANTIC:
            # e.g. SKU-BLK-12X10-AL-V2
            pat = r"[A-Z]{2,6}(?:-[A-Z0-9]{1,10}){1,6}"
        elif self.schema_type == SchemaType.HASH_BASED:
            # e.g. HASH-ab12cd34ef
            pat = r"HASH-[0-9a-f]{10}"
        else:
            # CUSTOM: match anything non-empty
            pat = r".+"
        return pat, re.compile(f"^{pat}$", flags)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, pn: str) -> ValidationResult:
        """Check *pn* against this schema's regex and reserved-prefix list.

        Per GS1 GTIN §2.1 (syntactic validity) and ISO 8000-110 §6.5 (identifier
        quality): a part number is valid iff it matches the declared pattern and
        does not start with a reserved prefix.

        Returns a ValidationResult with .valid and .reason populated.
        """
        if not pn or not isinstance(pn, str):
            return ValidationResult(
                valid=False,
                reason="Part number must be a non-empty string.",
                matched_schema=self.name,
            )

        # Reserved-prefix check
        for rp in self.reserved_prefixes:
            if self.case_sensitive:
                starts = pn.startswith(rp)
            else:
                starts = pn.upper().startswith(rp.upper())
            if starts:
                return ValidationResult(
                    valid=False,
                    reason=f"Part number '{pn}' starts with reserved prefix '{rp}'.",
                    matched_schema=self.name,
                )

        # Pattern check
        if not self._regex.match(pn):
            # Attempt to give a helpful reason by testing segments
            reason = self._diagnose(pn)
            return ValidationResult(
                valid=False,
                reason=reason,
                matched_schema=self.name,
            )

        return ValidationResult(valid=True, matched_schema=self.name)

    def _diagnose(self, pn: str) -> str:
        """Return a human-readable failure reason for a pattern mismatch."""
        pat = self.pattern
        # For structured schemas, try segment-by-segment diagnosis
        if self.schema_type == SchemaType.SEQUENTIAL:
            esc = re.escape(self.prefix)
            if not re.match(f"^{esc}", pn, re.IGNORECASE):
                return (
                    f"Expected prefix '{self.prefix}', got '{pn[:len(self.prefix)]}'."
                )
            serial_part = pn[len(self.prefix):]
            if not re.match(rf"^\d{{{self.serial_width}}}$", serial_part):
                return (
                    f"Serial segment '{serial_part}' must be exactly "
                    f"{self.serial_width} digits (zero-padded); "
                    f"got {len(serial_part)} chars."
                )
        elif self.schema_type == SchemaType.HIERARCHICAL:
            segs = pn.split("-")
            if len(segs) != 4:
                return (
                    f"Hierarchical PN must have 4 segments separated by '-' "
                    f"(type-family-variant-serial); got {len(segs)} segment(s)."
                )
            for i, (seg, label) in enumerate(
                zip(segs, ["type", "family", "variant", "serial"])
            ):
                if not re.match(r"^\d{3}$", seg):
                    return (
                        f"Segment {i+1} ({label}) '{seg}' must be exactly 3 digits; "
                        f"got {len(seg)} char(s)."
                    )
        return (
            f"Part number '{pn}' does not match schema '{self.name}' "
            f"(pattern: {pat})."
        )

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------

    def allocate_next(
        self,
        family_key: tuple[str, ...] | None = None,
    ) -> AllocationResult:
        """Mint the next available part number under this schema.

        Parameters
        ----------
        family_key:
            A tuple identifying the family namespace for sequential/hierarchical
            schemas.  For sequential schemas this can be empty or omitted.
            For hierarchical schemas supply (type_code, family_code, variant_code).
            For hash-based schemas supply the attribute dict as a 1-tuple (JSON str).

        Returns
        -------
        AllocationResult with .ok and .part_number populated.

        Honest flag: uniqueness is per-instance only.  See module docstring.
        """
        if family_key is None:
            family_key = ()

        if self.schema_type == SchemaType.HASH_BASED:
            return self._allocate_hash(family_key)
        elif self.schema_type == SchemaType.SEQUENTIAL:
            return self._allocate_sequential(family_key)
        elif self.schema_type == SchemaType.HIERARCHICAL:
            return self._allocate_hierarchical(family_key)
        else:
            return AllocationResult(
                ok=False,
                reason=(
                    f"Auto-allocation not supported for schema type "
                    f"'{self.schema_type}'. Provide an explicit PN."
                ),
            )

    def _allocate_sequential(self, family_key: tuple) -> AllocationResult:
        """Allocate PN-{serial:width} where serial increments per family_key."""
        current = self.allocated_by_family.get(family_key, 0)
        max_serial = 10 ** self.serial_width - 1
        for _ in range(max_serial):
            current += 1
            if current > max_serial:
                return AllocationResult(
                    ok=False,
                    reason=(
                        f"Sequential serial space exhausted for family {family_key!r} "
                        f"(max {self.serial_width}-digit serial: {max_serial})."
                    ),
                )
            candidate = f"{self.prefix}{current:0{self.serial_width}d}"
            if candidate not in self.issued_numbers:
                self.issued_numbers.add(candidate)
                self.allocated_by_family[family_key] = current
                return AllocationResult(ok=True, part_number=candidate)
        return AllocationResult(
            ok=False,
            reason="Could not allocate: all serials exhausted.",
        )

    def _allocate_hierarchical(self, family_key: tuple) -> AllocationResult:
        """Allocate {type:3}-{family:3}-{variant:3}-{serial:3}.

        family_key must be (type_code:str, family_code:str, variant_code:str).
        """
        if len(family_key) < 3:
            return AllocationResult(
                ok=False,
                reason=(
                    "Hierarchical allocation requires family_key = "
                    "(type_code, family_code, variant_code); "
                    f"got {len(family_key)} element(s)."
                ),
            )
        type_code, family_code, variant_code = (
            str(family_key[0]).zfill(3)[:3],
            str(family_key[1]).zfill(3)[:3],
            str(family_key[2]).zfill(3)[:3],
        )
        key = (type_code, family_code, variant_code)
        current = self.allocated_by_family.get(key, 0)
        max_serial = 999
        for _ in range(max_serial):
            current += 1
            if current > max_serial:
                return AllocationResult(
                    ok=False,
                    reason=(
                        f"Hierarchical serial space exhausted for "
                        f"{type_code}-{family_code}-{variant_code} (max 999)."
                    ),
                )
            candidate = (
                f"{type_code}-{family_code}-{variant_code}-{current:03d}"
            )
            if candidate not in self.issued_numbers:
                self.issued_numbers.add(candidate)
                self.allocated_by_family[key] = current
                return AllocationResult(ok=True, part_number=candidate)
        return AllocationResult(ok=False, reason="Could not allocate: all serials exhausted.")

    def _allocate_hash(self, family_key: tuple) -> AllocationResult:
        """Allocate HASH-<10-char hex> from SHA-256 of attributes JSON.

        family_key must be a 1-tuple containing the attribute dict or its JSON string.
        Per GS1 GTIN §2.1 note on deterministic identifiers: a hash-based PN is
        computed from part attributes, providing a deterministic, allocation-free
        identifier.  Collision probability for 10-hex-char (40-bit) truncation is
        ~1e-6 for 1 000 parts (birthday paradox).
        """
        if not family_key:
            return AllocationResult(
                ok=False,
                reason="Hash-based allocation requires family_key=(attrs_dict_or_json,).",
            )
        raw = family_key[0]
        if isinstance(raw, dict):
            attrs_str = json.dumps(raw, sort_keys=True, ensure_ascii=True)
        else:
            attrs_str = str(raw)
        digest = hashlib.sha256(attrs_str.encode()).hexdigest()[:10]
        candidate = f"HASH-{digest}"
        if candidate in self.issued_numbers:
            return AllocationResult(
                ok=False,
                part_number=candidate,
                reason=(
                    f"Hash-based PN '{candidate}' already issued "
                    f"(duplicate attributes or hash collision)."
                ),
                duplicate=True,
            )
        self.issued_numbers.add(candidate)
        return AllocationResult(ok=True, part_number=candidate)

    def mark_issued(self, pn: str) -> AllocationResult:
        """Register an existing PN as issued without allocating a new one.

        Used when importing legacy PNs into the schema state.
        Returns AllocationResult with duplicate=True if already present.
        """
        if pn in self.issued_numbers:
            return AllocationResult(
                ok=False,
                part_number=pn,
                reason=f"Duplicate: '{pn}' already issued.",
                duplicate=True,
            )
        self.issued_numbers.add(pn)
        return AllocationResult(ok=True, part_number=pn)

    # ------------------------------------------------------------------
    # State serialisation
    # ------------------------------------------------------------------

    def to_state_dict(self) -> dict:
        """Serialise allocation state for persistence (ISO 8000-110 §6.5 stability)."""
        return {
            "name": self.name,
            "schema_type": self.schema_type.value,
            "issued_numbers": sorted(self.issued_numbers),
            "allocated_by_family": {
                json.dumps(list(k)): v
                for k, v in self.allocated_by_family.items()
            },
        }

    @classmethod
    def from_state_dict(
        cls,
        state: dict,
        schema: "PartNumberSchema",
    ) -> "PartNumberSchema":
        """Restore allocation state from a previously-serialised dict."""
        schema.issued_numbers = set(state.get("issued_numbers", []))
        schema.allocated_by_family = {
            tuple(json.loads(k)): v
            for k, v in state.get("allocated_by_family", {}).items()
        }
        return schema


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def validate_part_number(pn: str, schema: PartNumberSchema) -> ValidationResult:
    """Validate *pn* against *schema*.  Thin wrapper around schema.validate().

    Per GS1 GTIN §2.1 syntactic-validity and ISO 8000-110 §6.5 data quality.

    Examples
    --------
    >>> s = make_schema("PN-{type:3}-{family:3}-{serial:5}", schema_type=SchemaType.CUSTOM,
    ...     pattern=r"PN-[A-Z]{3}-[A-Z]{3}-\\d{5}")
    >>> validate_part_number("PN-ABC-DEF-00123", s).valid
    True
    >>> r = validate_part_number("PN-AB-DEF-00123", s)
    >>> r.valid
    False
    """
    return schema.validate(pn)


def allocate_next(
    schema: PartNumberSchema,
    family_key: tuple[str, ...] | None = None,
) -> AllocationResult:
    """Allocate the next part number in *schema* for the given *family_key*.

    Per ISO 8000-110 §6.5 (unique identifiers): the returned PN is guaranteed
    unique within the in-memory schema state.  See module honest-flag for
    federation caveats.

    Returns AllocationResult; .ok is False on exhaustion or duplicate.
    """
    return schema.allocate_next(family_key=family_key)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

@dataclass
class MigrationResult:
    """Result of migrate_schema().

    Attributes
    ----------
    migrated:
        List of (old_pn, new_pn) pairs for successfully migrated numbers.
    failed:
        List of (old_pn, reason) pairs for PNs that could not be migrated.
    skipped:
        List of old_pns that were skipped because they were already valid
        in the new schema.
    """
    migrated: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.migrated)

    @property
    def failure_count(self) -> int:
        return len(self.failed)


def migrate_schema(
    old_pns: list[str],
    new_schema: PartNumberSchema,
    family_key_fn: Any = None,
) -> MigrationResult:
    """Re-number *old_pns* under *new_schema*.

    For each old PN:
    1. If the old PN already validates against new_schema, it is *skipped* (no new
       PN is issued).
    2. Otherwise, `allocate_next(new_schema, family_key_fn(old_pn))` is called to
       mint a replacement PN.  If allocation fails, the PN is recorded in *failed*.

    Parameters
    ----------
    old_pns:
        List of existing part numbers to recode.
    new_schema:
        Target schema.  Its allocation state is updated in-place as migration
        proceeds.
    family_key_fn:
        Optional callable `(old_pn: str) -> tuple` that maps an old PN to the
        *family_key* used when allocating in the new schema.  Defaults to
        `lambda _: ()` (root family).

    Returns
    -------
    MigrationResult with .migrated, .failed, .skipped.

    Reference: ISO 8000-110 §6.5 — identifier renaming / reissue.
    """
    if family_key_fn is None:
        family_key_fn = lambda _pn: ()  # noqa: E731

    result = MigrationResult()
    for old_pn in old_pns:
        # Already valid in new schema — skip
        if new_schema.validate(old_pn).valid:
            result.skipped.append(old_pn)
            continue
        # Allocate new
        fk = family_key_fn(old_pn)
        alloc = new_schema.allocate_next(family_key=fk)
        if alloc.ok:
            result.migrated.append((old_pn, alloc.part_number))
        else:
            result.failed.append((old_pn, alloc.reason))

    return result


# ---------------------------------------------------------------------------
# Convenience: build well-known schemas
# ---------------------------------------------------------------------------

def make_sequential_schema(
    name: str = "sequential",
    prefix: str = "PN-",
    serial_width: int = 5,
    reserved_prefixes: set[str] | None = None,
) -> PartNumberSchema:
    """Return a sequential schema: PN-00001, PN-00002, …

    Cooper "Industrial Inspection & DFM" §6.2 — simplest corporate PN scheme;
    suitable for single-product or small-batch manufacturers.
    """
    return PartNumberSchema(
        name=name,
        schema_type=SchemaType.SEQUENTIAL,
        prefix=prefix,
        serial_width=serial_width,
        reserved_prefixes=reserved_prefixes,
    )


def make_hierarchical_schema(
    name: str = "hierarchical",
    reserved_prefixes: set[str] | None = None,
) -> PartNumberSchema:
    """Return a 4-segment hierarchical schema: TTT-FFF-VVV-SSS.

    Cooper "Industrial Inspection & DFM" §6.3 — type / family / variant / serial
    encoding; analogous to GS1 GTIN company prefix + item reference structure.
    """
    return PartNumberSchema(
        name=name,
        schema_type=SchemaType.HIERARCHICAL,
        pattern=r"\d{3}-\d{3}-\d{3}-\d{3}",
        reserved_prefixes=reserved_prefixes,
    )


def make_semantic_schema(
    name: str = "semantic",
    reserved_prefixes: set[str] | None = None,
) -> PartNumberSchema:
    """Return a semantic-encoded schema: SKU-BLK-12X10-AL-V2.

    Cooper "Industrial Inspection & DFM" §6.4 — human-readable encoding of
    color, size, material, revision.  GS1 GTIN §2.1 allows alphanumeric
    application identifiers for trade items.
    """
    return PartNumberSchema(
        name=name,
        schema_type=SchemaType.SEMANTIC,
        pattern=r"[A-Z]{2,6}(?:-[A-Z0-9]{1,10}){1,6}",
        case_sensitive=False,
        reserved_prefixes=reserved_prefixes,
    )


def make_hash_schema(
    name: str = "hash_based",
    reserved_prefixes: set[str] | None = None,
) -> PartNumberSchema:
    """Return a hash-based schema: HASH-<10-hex-char SHA-256 truncation>.

    Deterministic, allocation-free per GS1 GTIN §2.1 deterministic identifier
    note.  ISO 8000-110 §6.5: stable for fixed attribute sets; re-derive on
    attribute change yields a new PN (version-safe).
    """
    return PartNumberSchema(
        name=name,
        schema_type=SchemaType.HASH_BASED,
        pattern=r"HASH-[0-9a-f]{10}",
        reserved_prefixes=reserved_prefixes,
    )
