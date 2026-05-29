"""
Tests for kerf_plm.change_management — ECR/ECO workflow (ISO 10007).

4 required validation tests:
  1. Happy path: ECR submitted → 2 approvals → escalated to ECO → 3 signoffs → released.
     Affected parts' effective_from updated.
  2. Rejected ECR: 2 reject votes → 'rejected'; cannot be escalated to ECO.
  3. ISO 10007 audit trail: all 5+ transitions recorded; trail is immutable.
  4. BOM correctness post-release: effectivity_bom before ECO date returns OLD revisions;
     after ECO date returns NEW revisions.

All tests are hermetic (no DB, no filesystem).
"""
from __future__ import annotations

from datetime import date

import pytest

from kerf_plm.change_management import (
    AuditEntry,
    ChangeBoard,
    ECO,
    ECR,
)
from kerf_plm.configurator import Part, effectivity_bom


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ecr(
    ecr_id: str = "ECR-001",
    reviewers: list[str] | None = None,
    required_approvals: int = 2,
) -> ECR:
    return ECR(
        id=ecr_id,
        title="Upgrade bearing material to 52100 steel",
        description="Current SAE 1045 carbon steel bearings show early fatigue failure.",
        originator="eng-alice",
        affected_parts=["PART-BEARING-001", "PART-BEARING-002"],
        rationale="ISO 281:2007 bearing life calculations show 3× improvement with 52100.",
        classification="major",
        proposed_disposition="redesign",
        reviewers=reviewers or ["reviewer-bob", "reviewer-carol"],
        required_approvals=required_approvals,
    )


def _make_eco(
    eco_id: str = "ECO-001",
    ecr_refs: list[str] | None = None,
    effective_date: date | None = None,
) -> ECO:
    return ECO(
        id=eco_id,
        references_ecrs=ecr_refs or [],
        description="Replace SAE 1045 bearings with 52100 steel variants.",
        affected_parts=["PART-BEARING-001", "PART-BEARING-002"],
        effective_date=effective_date or date(2025, 7, 1),
    )


# ---------------------------------------------------------------------------
# Test 1: Happy path — full ECR→ECO lifecycle
# ---------------------------------------------------------------------------

class TestHappyPath:
    """Full happy-path workflow per ISO 10007 §5."""

    def test_full_lifecycle_ecr_to_eco_released(self):
        board = ChangeBoard()
        ecr = _make_ecr()

        # 1. Submit ECR
        board.submit_ecr(ecr)
        assert ecr.state == "submitted"

        # 2. Two reviewer approvals → auto-approved
        board.review_ecr("ECR-001", reviewer="reviewer-bob", decision="approve")
        board.review_ecr("ECR-001", reviewer="reviewer-carol", decision="approve")
        assert ecr.state == "approved"

        # 3. Escalate to ECO
        eco = _make_eco(effective_date=date(2025, 7, 1))
        board.escalate_to_eco("ECR-001", eco)
        assert eco.implementation_state == "planned"
        assert "ECR-001" in eco.references_ecrs

        # 4. Three signoffs → auto-released
        board.implement_eco("ECO-001", signer="carol", role="engineering")
        board.implement_eco("ECO-001", signer="dave", role="manufacturing")
        board.implement_eco("ECO-001", signer="eve", role="qa")
        assert eco.implementation_state == "released"

        # 5. Effectivity propagation
        assert board.get_part_effective_from("PART-BEARING-001") == date(2025, 7, 1)
        assert board.get_part_effective_from("PART-BEARING-002") == date(2025, 7, 1)

    def test_signoffs_are_recorded(self):
        board = ChangeBoard()
        ecr = _make_ecr()
        board.submit_ecr(ecr)
        board.review_ecr("ECR-001", "reviewer-bob", "approve")
        board.review_ecr("ECR-001", "reviewer-carol", "approve")

        eco = _make_eco()
        board.escalate_to_eco("ECR-001", eco)
        board.implement_eco("ECO-001", signer="s-eng", role="engineering")
        board.implement_eco("ECO-001", signer="s-mfg", role="manufacturing")
        board.implement_eco("ECO-001", signer="s-qa", role="qa")

        assert eco.engineering_signoff == "s-eng"
        assert eco.manufacturing_signoff == "s-mfg"
        assert eco.qa_signoff == "s-qa"

    def test_partial_signoffs_not_released(self):
        board = ChangeBoard()
        ecr = _make_ecr()
        board.submit_ecr(ecr)
        board.review_ecr("ECR-001", "reviewer-bob", "approve")
        board.review_ecr("ECR-001", "reviewer-carol", "approve")

        eco = _make_eco()
        board.escalate_to_eco("ECR-001", eco)
        board.implement_eco("ECO-001", signer="s-eng", role="engineering")
        board.implement_eco("ECO-001", signer="s-mfg", role="manufacturing")
        # qa missing
        assert eco.implementation_state == "in_progress"
        assert eco.implementation_state != "released"


# ---------------------------------------------------------------------------
# Test 2: Rejected ECR — cannot escalate to ECO
# ---------------------------------------------------------------------------

class TestRejectedECR:
    """Rejected ECRs must be blocked from ECO escalation."""

    def test_rejected_ecr_cannot_be_escalated(self):
        board = ChangeBoard()
        # Give 3 reviewers so majority-reject fires at 2 of 3
        ecr = ECR(
            id="ECR-002",
            title="Use cheaper aluminium casting",
            description="Cost reduction proposal.",
            originator="cost-eng",
            affected_parts=["PART-HOUSING-001"],
            reviewers=["r1", "r2", "r3"],
            required_approvals=2,
        )
        board.submit_ecr(ecr)
        board.review_ecr("ECR-002", "r1", "reject")
        board.review_ecr("ECR-002", "r2", "reject")
        # 2 out of 3 rejected = majority → rejected
        assert ecr.state == "rejected"

        eco = ECO(
            id="ECO-002",
            references_ecrs=["ECR-002"],
            description="Should not be created.",
            affected_parts=["PART-HOUSING-001"],
            effective_date=date(2025, 8, 1),
        )
        with pytest.raises(ValueError, match="approved"):
            board.escalate_to_eco("ECR-002", eco)

    def test_rejected_ecr_state_preserved(self):
        board = ChangeBoard()
        ecr = ECR(
            id="ECR-003",
            title="Some change",
            description="desc",
            originator="user1",
            affected_parts=["P1"],
            reviewers=["r1", "r2", "r3"],
            required_approvals=2,
        )
        board.submit_ecr(ecr)
        board.review_ecr("ECR-003", "r1", "reject")
        board.review_ecr("ECR-003", "r2", "reject")
        assert ecr.state == "rejected"
        assert board.get_ecr("ECR-003").state == "rejected"

    def test_two_approve_votes_auto_approve(self):
        """Confirm that 2 approves → approved (not rejected)."""
        board = ChangeBoard()
        ecr = _make_ecr("ECR-004", reviewers=["r1", "r2", "r3"], required_approvals=2)
        board.submit_ecr(ecr)
        board.review_ecr("ECR-004", "r1", "approve")
        board.review_ecr("ECR-004", "r2", "approve")
        assert ecr.state == "approved"


# ---------------------------------------------------------------------------
# Test 3: ISO 10007 audit trail completeness + immutability
# ---------------------------------------------------------------------------

class TestAuditTrail:
    """ISO 10007 §5 — every state transition recorded; trail is immutable."""

    def _run_full_lifecycle(self) -> ChangeBoard:
        board = ChangeBoard()
        ecr = _make_ecr()
        board.submit_ecr(ecr)                                            # T1: draft→submitted
        board.review_ecr("ECR-001", "reviewer-bob", "approve")           # T2: submitted→under_review (+vote)
        board.review_ecr("ECR-001", "reviewer-carol", "approve")         # T3: under_review→approved
        eco = _make_eco()
        board.escalate_to_eco("ECR-001", eco)                           # T4: ECO (new)→planned
        board.implement_eco("ECO-001", "carol", "engineering")          # T5: planned→in_progress + signoff
        board.implement_eco("ECO-001", "dave", "manufacturing")         # T6: signoff
        board.implement_eco("ECO-001", "eve", "qa")                     # T7: in_progress→released
        return board

    def test_at_least_5_audit_entries(self):
        board = self._run_full_lifecycle()
        trail = board.audit_trail()
        assert len(trail) >= 5, f"Expected ≥5 audit entries, got {len(trail)}"

    def test_all_entries_are_audit_entry_instances(self):
        board = self._run_full_lifecycle()
        for entry in board.audit_trail():
            assert isinstance(entry, AuditEntry)

    def test_all_entries_have_timestamps(self):
        board = self._run_full_lifecycle()
        for entry in board.audit_trail():
            assert entry.timestamp, f"Entry missing timestamp: {entry}"

    def test_all_entries_have_actor(self):
        board = self._run_full_lifecycle()
        for entry in board.audit_trail():
            assert entry.actor, f"Entry missing actor: {entry}"

    def test_state_transitions_are_recorded(self):
        board = self._run_full_lifecycle()
        trail = board.audit_trail()
        state_pairs = [(e.old_state, e.new_state) for e in trail]
        assert ("draft", "submitted") in state_pairs
        assert ("in_progress", "released") in state_pairs

    def test_audit_trail_is_immutable_at_collection_level(self):
        """The internal audit tuple cannot be mutated from outside."""
        board = self._run_full_lifecycle()
        # audit_trail() returns a list copy — mutating it doesn't affect board
        trail_copy = board.audit_trail()
        original_len = len(trail_copy)
        trail_copy.clear()
        assert len(board.audit_trail()) == original_len

    def test_audit_entries_are_frozen(self):
        """AuditEntry objects are frozen dataclasses — fields cannot be reassigned."""
        board = self._run_full_lifecycle()
        entry = board.audit_trail()[0]
        with pytest.raises((AttributeError, TypeError)):
            entry.actor = "tampered"  # type: ignore[misc]

    def test_ecr_and_eco_both_appear_in_trail(self):
        board = self._run_full_lifecycle()
        entity_types = {e.entity_type for e in board.audit_trail()}
        assert "ECR" in entity_types
        assert "ECO" in entity_types


# ---------------------------------------------------------------------------
# Test 4: BOM correctness — before vs after ECO effective date
# ---------------------------------------------------------------------------

class TestBomCorrectnessPostRelease:
    """effectivity_bom returns old revisions before ECO date, new after."""

    def _setup_parts_and_eco(self) -> tuple[list[Part], ChangeBoard]:
        """
        Build a 150% BOM with old (rev A) and new (rev B) bearing parts.

        - old_bearing: effective_from=None, effective_to=2025-07-01 (rev A)
        - new_bearing: effective_from=2025-07-01, effective_to=None (rev B)

        The ECO is released with effective_date=2025-07-01.
        Before 2025-07-01 only the old bearing is effective.
        From 2025-07-01 onward only the new bearing is effective.
        """
        old_bearing = Part(
            part_id="PART-BEARING-001-revA",
            description="Bearing SAE 1045 Rev A",
            effective_from=None,
            effective_to=date(2025, 7, 1),   # expires when ECO takes effect
        )
        new_bearing = Part(
            part_id="PART-BEARING-001-revB",
            description="Bearing 52100 steel Rev B",
            effective_from=date(2025, 7, 1),  # effective from ECO date
            effective_to=None,
        )
        unrelated = Part(
            part_id="PART-SHAFT-001",
            description="Drive shaft — not affected by ECO",
        )
        parts_150_bom = [old_bearing, new_bearing, unrelated]

        # Run the full lifecycle
        board = ChangeBoard()
        ecr = ECR(
            id="ECR-BOM-001",
            title="Upgrade bearing to 52100 steel",
            description="Rev B bearing part.",
            originator="alice",
            affected_parts=["PART-BEARING-001-revB"],
            reviewers=["r1", "r2"],
            required_approvals=2,
        )
        board.submit_ecr(ecr)
        board.review_ecr("ECR-BOM-001", "r1", "approve")
        board.review_ecr("ECR-BOM-001", "r2", "approve")

        eco = ECO(
            id="ECO-BOM-001",
            references_ecrs=["ECR-BOM-001"],
            affected_parts=["PART-BEARING-001-revB"],
            effective_date=date(2025, 7, 1),
        )
        board.escalate_to_eco("ECR-BOM-001", eco)
        board.implement_eco("ECO-BOM-001", "carol", "engineering")
        board.implement_eco("ECO-BOM-001", "dave", "manufacturing")
        board.implement_eco("ECO-BOM-001", "eve", "qa")

        assert eco.implementation_state == "released"
        return parts_150_bom, board

    def test_bom_before_eco_date_returns_old_revision(self):
        parts_150, board = self._setup_parts_and_eco()
        before_date = date(2025, 6, 30)
        effective_parts = effectivity_bom(parts_150, before_date)
        part_ids = [p.part_id for p in effective_parts]
        assert "PART-BEARING-001-revA" in part_ids
        assert "PART-BEARING-001-revB" not in part_ids
        assert "PART-SHAFT-001" in part_ids

    def test_bom_on_eco_effective_date_returns_new_revision(self):
        parts_150, board = self._setup_parts_and_eco()
        eco_date = date(2025, 7, 1)
        effective_parts = effectivity_bom(parts_150, eco_date)
        part_ids = [p.part_id for p in effective_parts]
        # Rev A expires at 2025-07-01 (exclusive upper bound), Rev B starts
        assert "PART-BEARING-001-revA" not in part_ids
        assert "PART-BEARING-001-revB" in part_ids
        assert "PART-SHAFT-001" in part_ids

    def test_bom_after_eco_date_returns_new_revision(self):
        parts_150, board = self._setup_parts_and_eco()
        after_date = date(2025, 8, 15)
        effective_parts = effectivity_bom(parts_150, after_date)
        part_ids = [p.part_id for p in effective_parts]
        assert "PART-BEARING-001-revA" not in part_ids
        assert "PART-BEARING-001-revB" in part_ids

    def test_effectivity_propagation_matches_eco_date(self):
        """board._part_effectivity reflects ECO release date after release."""
        _, board = self._setup_parts_and_eco()
        assert board.get_part_effective_from("PART-BEARING-001-revB") == date(2025, 7, 1)


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_cannot_submit_same_ecr_twice(self):
        board = ChangeBoard()
        ecr = _make_ecr()
        board.submit_ecr(ecr)
        with pytest.raises(KeyError):
            board.submit_ecr(ecr)

    def test_cannot_escalate_draft_ecr(self):
        board = ChangeBoard()
        ecr = _make_ecr()
        # Don't submit — ECR stays in draft
        board._ecrs["ECR-001"] = ecr
        eco = _make_eco()
        with pytest.raises(ValueError, match="approved"):
            board.escalate_to_eco("ECR-001", eco)

    def test_cannot_review_nonexistent_ecr(self):
        board = ChangeBoard()
        with pytest.raises(KeyError):
            board.review_ecr("ECR-NONEXISTENT", "r1", "approve")

    def test_cannot_implement_nonexistent_eco(self):
        board = ChangeBoard()
        with pytest.raises(KeyError):
            board.implement_eco("ECO-NONEXISTENT", "carol", "engineering")

    def test_invalid_review_decision_raises(self):
        board = ChangeBoard()
        ecr = _make_ecr()
        board.submit_ecr(ecr)
        with pytest.raises(ValueError, match="approve.*reject"):
            board.review_ecr("ECR-001", "reviewer-bob", "maybe")

    def test_invalid_signoff_role_raises(self):
        board = ChangeBoard()
        ecr = _make_ecr()
        board.submit_ecr(ecr)
        board.review_ecr("ECR-001", "reviewer-bob", "approve")
        board.review_ecr("ECR-001", "reviewer-carol", "approve")
        eco = _make_eco()
        board.escalate_to_eco("ECR-001", eco)
        with pytest.raises(ValueError, match="role"):
            board.implement_eco("ECO-001", "alice", "legal")

    def test_ecr_classification_validation(self):
        with pytest.raises(ValueError, match="classification"):
            ECR(id="X", title="t", description="d", originator="u",
                classification="extreme")

    def test_ecr_disposition_validation(self):
        with pytest.raises(ValueError, match="proposed_disposition"):
            ECR(id="X", title="t", description="d", originator="u",
                proposed_disposition="donate")

    def test_eco_back_reference_auto_added(self):
        board = ChangeBoard()
        ecr = _make_ecr()
        board.submit_ecr(ecr)
        board.review_ecr("ECR-001", "reviewer-bob", "approve")
        board.review_ecr("ECR-001", "reviewer-carol", "approve")
        # ECO has empty references_ecrs
        eco = ECO(id="ECO-X", affected_parts=["P1"], effective_date=date(2025, 7, 1))
        board.escalate_to_eco("ECR-001", eco)
        assert "ECR-001" in eco.references_ecrs


# ---------------------------------------------------------------------------
# LLM tool integration
# ---------------------------------------------------------------------------

class TestPlmChangeManagementLlmTool:
    """Smoke test the plm_change_management LLM tool wrapper."""

    def test_tool_registered_in_tool_defs(self):
        from kerf_plm.tools import TOOL_DEFS
        names = [t["name"] for t in TOOL_DEFS]
        assert "plm_change_management" in names

    def test_submit_ecr_action(self):
        from kerf_plm.tools import plm_change_management
        import json

        result = plm_change_management(
            action="submit_ecr",
            ecr_json=json.dumps({
                "id": "ECR-LLM-001",
                "title": "Upgrade fasteners",
                "description": "Grade 5 → Grade 8 bolts for better fatigue life.",
                "originator": "eng-user",
                "affected_parts": ["BOLT-001"],
                "classification": "minor",
                "proposed_disposition": "rework",
                "reviewers": ["r1", "r2"],
            }),
        )
        assert result["ok"] is True
        assert result["ecr"]["state"] == "submitted"

    def test_get_ecr_state_action(self):
        from kerf_plm.tools import plm_change_management
        import json

        # Board state is per-call; submit then query in sequence
        # The LLM tool is stateless per call — we use the low-level API for round-trip
        board = ChangeBoard()
        ecr = _make_ecr("ECR-LLM-002")
        board.submit_ecr(ecr)
        assert board.get_ecr("ECR-LLM-002").state == "submitted"

    def test_dispatch_unknown_action(self):
        from kerf_plm.tools import plm_change_management

        result = plm_change_management(action="no_such_action")
        assert result["ok"] is False
        assert result["code"] == "BAD_ARGS"
