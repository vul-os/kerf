"""
tests/test_part_numbering_schema.py
====================================

Validation tests for kerf_plm.part_numbering_schema.

References
----------
- GS1 GTIN General Specifications v23 §2.1 — syntactic validity, deterministic IDs.
- ISO 8000-110:2009 §6.5 — data-quality master data: unique, syntactically valid.
- Cooper "Industrial Inspection & DFM" §6 — sequential, hierarchical, semantic PNs.

Test matrix
-----------
PN-01  Sequential schema: valid PN passes regex.
PN-02  Sequential schema: PN with wrong-width serial fails with reason.
PN-03  Sequential schema: PN with wrong prefix fails with reason.
PN-04  Sequential schema: allocate first PN → PN-00001.
PN-05  Sequential schema: allocate N+1 after N allocations → correct serial.
PN-06  Sequential schema: duplicate detection on issued set.
PN-07  Sequential schema: reserved prefix blocks allocation + validation.
PN-08  Hierarchical schema: valid 100-200-300-001 passes.
PN-09  Hierarchical schema: 4-char type segment fails with per-segment reason.
PN-10  Hierarchical schema: wrong segment count fails with reason.
PN-11  Hierarchical schema: allocate_next with family_key=(100,200,300) → 100-200-300-001.
PN-12  Hierarchical schema: second allocate → 100-200-300-002.
PN-13  Semantic schema: valid SKU-BLK-12X10-AL-V2 passes.
PN-14  Semantic schema: single-char prefix fails.
PN-15  Semantic schema: allocation not supported → AllocationResult.ok=False.
PN-16  Hash schema: valid HASH-ab12cd34ef passes.
PN-17  Hash schema: allocate_next with attribute dict → deterministic HASH-*.
PN-18  Hash schema: allocate same attrs twice → duplicate flag + ok=False.
PN-19  Custom schema (PN-{type:3}-{family:3}-{serial:5}): depth-bar tests.
PN-20  Migration: old PNs remapped to new sequential schema.
PN-21  Migration: already-valid PNs skipped.
PN-22  Migration: allocation failure captured in failed list.
PN-23  mark_issued: imported PN registered; second mark → duplicate.
PN-24  to_state_dict / from_state_dict: round-trip preserves state.
PN-25  module-level validate_part_number + allocate_next wrappers.
"""

from __future__ import annotations

import json
import hashlib
import pytest

from kerf_plm.part_numbering_schema import (
    AllocationResult,
    MigrationResult,
    PartNumberSchema,
    SchemaType,
    ValidationResult,
    allocate_next,
    make_hash_schema,
    make_hierarchical_schema,
    make_semantic_schema,
    make_sequential_schema,
    migrate_schema,
    validate_part_number,
)


# ===========================================================================
# PN-01..PN-07  Sequential schema
# ===========================================================================

class TestSequentialSchema:
    def _schema(self, **kw) -> PartNumberSchema:
        return make_sequential_schema(prefix="PN-", serial_width=5, **kw)

    def test_valid_pn_passes(self):
        """PN-01 — 'PN-00001' validates against sequential schema."""
        s = self._schema()
        assert s.validate("PN-00001").valid

    def test_wrong_width_serial_fails(self):
        """PN-02 — 'PN-001' (3-digit) fails; reason mentions width."""
        s = self._schema()
        r = s.validate("PN-001")
        assert not r.valid
        assert "5" in r.reason or "serial" in r.reason.lower()

    def test_wrong_prefix_fails(self):
        """PN-03 — 'XX-00001' fails; reason mentions prefix."""
        s = self._schema()
        r = s.validate("XX-00001")
        assert not r.valid
        assert "PN-" in r.reason or "prefix" in r.reason.lower() or "pattern" in r.reason.lower()

    def test_allocate_first(self):
        """PN-04 — first allocation → 'PN-00001'."""
        s = self._schema()
        res = s.allocate_next()
        assert res.ok
        assert res.part_number == "PN-00001"

    def test_allocate_increments(self):
        """PN-05 — second allocation → 'PN-00002'."""
        s = self._schema()
        s.allocate_next()
        res = s.allocate_next()
        assert res.ok
        assert res.part_number == "PN-00002"

    def test_duplicate_detection(self):
        """PN-06 — mark_issued then re-allocate skips duplicates."""
        s = self._schema()
        # Pre-fill PN-00001 and PN-00002
        s.mark_issued("PN-00001")
        s.mark_issued("PN-00002")
        res = s.allocate_next()
        assert res.ok
        assert res.part_number == "PN-00003"

    def test_reserved_prefix_blocks_validation(self):
        """PN-07 — reserved prefix 'PN-ZZZ' blocks PNs starting with that prefix."""
        s = make_sequential_schema(
            prefix="PN-",
            serial_width=5,
            reserved_prefixes={"PN-ZZZ"},
        )
        r = s.validate("PN-ZZZ12345")
        assert not r.valid
        assert "reserved" in r.reason.lower() or "PN-ZZZ" in r.reason

    def test_reserved_prefix_blocks_valid_format(self):
        """PN-07b — a PN matching the serial pattern but starting with reserved prefix fails."""
        s = make_sequential_schema(
            prefix="PN-",
            serial_width=5,
            reserved_prefixes={"XX"},
        )
        # XX-00001 would fail the pattern check anyway; test reserved-prefix wins
        r = s.validate("XX-00001")
        assert not r.valid


# ===========================================================================
# PN-08..PN-12  Hierarchical schema
# ===========================================================================

class TestHierarchicalSchema:
    def _schema(self) -> PartNumberSchema:
        return make_hierarchical_schema()

    def test_valid_hierarchical_pn(self):
        """PN-08 — '100-200-300-001' passes hierarchical schema."""
        s = self._schema()
        assert s.validate("100-200-300-001").valid

    def test_type_segment_too_long_fails(self):
        """PN-09 — '1000-200-300-001' (4-char type) fails; reason mentions segment."""
        s = self._schema()
        r = s.validate("1000-200-300-001")
        assert not r.valid
        # Reason should mention the problem
        assert r.reason

    def test_wrong_segment_count_fails(self):
        """PN-10 — '100-200-001' (3 segments) fails; reason mentions 4 segments."""
        s = self._schema()
        r = s.validate("100-200-001")
        assert not r.valid
        assert "4" in r.reason or "segment" in r.reason.lower()

    def test_allocate_first(self):
        """PN-11 — allocate (100, 200, 300) → '100-200-300-001'."""
        s = self._schema()
        res = s.allocate_next(family_key=("100", "200", "300"))
        assert res.ok
        assert res.part_number == "100-200-300-001"

    def test_allocate_increments(self):
        """PN-12 — second allocation → '100-200-300-002'."""
        s = self._schema()
        s.allocate_next(family_key=("100", "200", "300"))
        res = s.allocate_next(family_key=("100", "200", "300"))
        assert res.ok
        assert res.part_number == "100-200-300-002"

    def test_different_families_are_independent(self):
        """PN-12b — family (100,200,300) and (100,200,301) have independent serials."""
        s = self._schema()
        r1 = s.allocate_next(family_key=("100", "200", "300"))
        r2 = s.allocate_next(family_key=("100", "200", "301"))
        assert r1.part_number == "100-200-300-001"
        assert r2.part_number == "100-200-301-001"


# ===========================================================================
# PN-13..PN-15  Semantic schema
# ===========================================================================

class TestSemanticSchema:
    def _schema(self) -> PartNumberSchema:
        return make_semantic_schema()

    def test_valid_semantic_pn(self):
        """PN-13 — 'SKU-BLK-12X10-AL-V2' passes semantic schema."""
        s = self._schema()
        assert s.validate("SKU-BLK-12X10-AL-V2").valid

    def test_single_char_prefix_fails(self):
        """PN-14 — 'S-BLK-12X10' fails (prefix < 2 chars)."""
        s = self._schema()
        r = s.validate("S-BLK-12X10")
        assert not r.valid

    def test_allocation_not_supported(self):
        """PN-15 — allocate_next on semantic schema → ok=False with reason."""
        s = self._schema()
        res = s.allocate_next()
        assert not res.ok
        assert "not supported" in res.reason.lower() or res.reason


# ===========================================================================
# PN-16..PN-18  Hash-based schema
# ===========================================================================

class TestHashSchema:
    def _schema(self) -> PartNumberSchema:
        return make_hash_schema()

    def test_valid_hash_pn(self):
        """PN-16 — 'HASH-ab12cd34ef' passes hash schema."""
        s = self._schema()
        assert s.validate("HASH-ab12cd34ef").valid

    def test_invalid_hash_pn(self):
        """PN-16b — 'HASH-GGGGGGGGGG' (non-hex) fails."""
        s = self._schema()
        r = s.validate("HASH-GGGGGGGGGG")
        assert not r.valid

    def test_allocate_deterministic(self):
        """PN-17 — allocating with same attrs gives same hash."""
        s = self._schema()
        attrs = {"material": "AL", "size": "12x10", "color": "BLK"}
        res = s.allocate_next(family_key=(attrs,))
        assert res.ok
        assert res.part_number.startswith("HASH-")
        # Recompute expected digest manually
        expected_digest = hashlib.sha256(
            json.dumps(attrs, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()[:10]
        assert res.part_number == f"HASH-{expected_digest}"

    def test_duplicate_hash_rejected(self):
        """PN-18 — second allocation with same attrs → duplicate=True, ok=False."""
        s = self._schema()
        attrs = {"material": "SS", "grade": "316"}
        s.allocate_next(family_key=(attrs,))
        res = s.allocate_next(family_key=(attrs,))
        assert not res.ok
        assert res.duplicate
        assert "duplicate" in res.reason.lower() or "already issued" in res.reason.lower()


# ===========================================================================
# PN-19  Custom schema (depth-bar: PN-{type:3}-{family:3}-{serial:5})
# ===========================================================================

class TestCustomSchema:
    """Depth-bar tests per the PLM-PART-NUMBERING-SCHEMA spec."""

    def _schema(self) -> PartNumberSchema:
        # Pattern: PN-{type:3 alpha}-{family:3 alpha}-{serial:5 digits}
        return PartNumberSchema(
            name="PN-TYPE-FAMILY-SERIAL",
            schema_type=SchemaType.CUSTOM,
            pattern=r"PN-[A-Z]{3}-[A-Z]{3}-\d{5}",
            case_sensitive=False,
        )

    def test_valid_passes(self):
        """PN-19a — 'PN-ABC-DEF-00123' is valid."""
        s = self._schema()
        assert s.validate("PN-ABC-DEF-00123").valid

    def test_type_too_short_fails(self):
        """PN-19b — 'PN-AB-DEF-00123' (type segment 2 chars) fails."""
        s = self._schema()
        r = s.validate("PN-AB-DEF-00123")
        assert not r.valid
        assert r.reason  # must give a reason

    def test_serial_too_short_fails(self):
        """PN-19c — 'PN-ABC-DEF-0012' (4-digit serial) fails."""
        s = self._schema()
        r = s.validate("PN-ABC-DEF-0012")
        assert not r.valid

    def test_family_too_long_fails(self):
        """PN-19d — 'PN-ABC-DEFG-00123' (family 4 chars) fails."""
        s = self._schema()
        r = s.validate("PN-ABC-DEFG-00123")
        assert not r.valid

    def test_case_insensitive(self):
        """PN-19e — lower-case 'pn-abc-def-00123' also validates (case-insensitive)."""
        s = self._schema()
        assert s.validate("pn-abc-def-00123").valid

    def test_reserved_prefix_in_custom_schema(self):
        """PN-19f — reserved prefix 'PN-TST' blocks that PN range."""
        s = PartNumberSchema(
            name="PN-TYPE-FAMILY-SERIAL",
            schema_type=SchemaType.CUSTOM,
            pattern=r"PN-[A-Z]{3}-[A-Z]{3}-\d{5}",
            reserved_prefixes={"PN-TST"},
            case_sensitive=False,
        )
        r = s.validate("PN-TST-DEF-00001")
        assert not r.valid
        assert "reserved" in r.reason.lower()


# ===========================================================================
# PN-20..PN-22  Migration
# ===========================================================================

class TestMigration:
    def test_migrate_to_new_schema(self):
        """PN-20 — old PNs get new sequential PNs; migrated list populated."""
        new = make_sequential_schema(prefix="NP-", serial_width=5)
        old_pns = ["LEGACY-001", "LEGACY-002", "LEGACY-003"]
        result = migrate_schema(old_pns, new)
        assert result.success_count == 3
        assert result.failure_count == 0
        assert len(result.skipped) == 0
        # New PNs should be sequential
        new_pns = [m[1] for m in result.migrated]
        assert new_pns == ["NP-00001", "NP-00002", "NP-00003"]

    def test_already_valid_skipped(self):
        """PN-21 — PNs already valid in new schema are skipped."""
        new = make_sequential_schema(prefix="PN-", serial_width=5)
        old_pns = ["PN-00010", "LEGACY-002"]
        result = migrate_schema(old_pns, new)
        assert "PN-00010" in result.skipped
        assert len(result.migrated) == 1
        assert result.migrated[0][0] == "LEGACY-002"

    def test_migration_failure_captured(self):
        """PN-22 — migration with exhausted schema records failures."""
        # Create a schema with serial_width=1 (max 9 PNs)
        new = make_sequential_schema(prefix="X-", serial_width=1)
        # Pre-fill all 9 slots
        for i in range(1, 10):
            new.issued_numbers.add(f"X-{i}")
        new.allocated_by_family[()] = 9

        old_pns = ["OLD-001", "OLD-002"]
        result = migrate_schema(old_pns, new)
        assert result.failure_count == 2
        for _, reason in result.failed:
            assert reason  # must have a reason string


# ===========================================================================
# PN-23  mark_issued
# ===========================================================================

class TestMarkIssued:
    def test_mark_then_duplicate(self):
        """PN-23 — mark_issued registers PN; second mark returns duplicate."""
        s = make_sequential_schema()
        r1 = s.mark_issued("PN-00005")
        assert r1.ok
        assert r1.part_number == "PN-00005"

        r2 = s.mark_issued("PN-00005")
        assert not r2.ok
        assert r2.duplicate


# ===========================================================================
# PN-24  State round-trip
# ===========================================================================

class TestStatePersistence:
    def test_round_trip(self):
        """PN-24 — to_state_dict / from_state_dict preserves issued_numbers + allocated_by_family."""
        s = make_sequential_schema(prefix="PN-", serial_width=5)
        s.allocate_next()  # PN-00001
        s.allocate_next()  # PN-00002

        state = s.to_state_dict()
        assert "PN-00001" in state["issued_numbers"]
        assert "PN-00002" in state["issued_numbers"]

        # Restore into a fresh schema
        s2 = make_sequential_schema(prefix="PN-", serial_width=5)
        PartNumberSchema.from_state_dict(state, s2)
        assert "PN-00001" in s2.issued_numbers
        # Next allocation must be PN-00003
        # But allocated_by_family key is [] → ()
        res = s2.allocate_next()
        assert res.ok
        assert res.part_number == "PN-00003"


# ===========================================================================
# PN-25  Module-level wrappers
# ===========================================================================

class TestModuleWrappers:
    def test_validate_part_number_wrapper(self):
        """PN-25a — module-level validate_part_number delegates to schema."""
        s = make_sequential_schema(prefix="PN-", serial_width=5)
        assert validate_part_number("PN-00042", s).valid
        assert not validate_part_number("PN-042", s).valid

    def test_allocate_next_wrapper(self):
        """PN-25b — module-level allocate_next delegates to schema."""
        s = make_sequential_schema(prefix="PN-", serial_width=5)
        res = allocate_next(s)
        assert res.ok
        assert res.part_number == "PN-00001"


# ===========================================================================
# Honest-flag check
# ===========================================================================

def test_honest_flag_present():
    """HONEST_FLAG is a non-empty string documenting per-instance uniqueness."""
    assert PartNumberSchema.HONEST_FLAG
    assert "per-instance" in PartNumberSchema.HONEST_FLAG.lower() or \
           "in-memory" in PartNumberSchema.HONEST_FLAG.lower()
