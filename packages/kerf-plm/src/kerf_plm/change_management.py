"""
kerf_plm.change_management — ECR/ECO workflow (ISO 10007).

Engineering Change Request (ECR) → reviewed → approved/rejected →
Engineering Change Order (ECO) → implemented → released.

ISO 10007:2003 §5 — Configuration change management:
  §5.1  Change identification
  §5.2  Change evaluation and approval
  §5.3  Change implementation
  §5.4  Verification of change

State machines
--------------
ECR:
  draft → submitted → under_review → approved/rejected
                                   ↘ withdrawn  (any non-terminal)

ECO (from approved ECR only):
  planned → in_progress → verified → released → closed

Effectivity propagation
-----------------------
When an ECO is released the affected parts' ``effective_from`` date is set
to ``eco.effective_date``.  The ``effectivity_bom`` function in
``kerf_plm.configurator`` (half-open [from, to) interval) then naturally
returns the correct revision for any query date.

Audit trail
-----------
Every state transition appends a ``_AuditEntry`` to ``ChangeBoard._audit``.
The collection is a tuple (immutable); attempting to mutate it raises
``TypeError``.  Callers read it via ``board.audit_trail()`` (returns a copy).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


# ---------------------------------------------------------------------------
# Audit entry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditEntry:
    """Immutable record of a single state transition.

    Attributes:
        timestamp:  ISO-8601 UTC datetime string.
        actor:      User id / reviewer id / signer id.
        entity_id:  ECR or ECO identifier.
        entity_type: "ECR" or "ECO".
        old_state:  Previous state string.
        new_state:  New state string.
        note:       Optional free-text note.
    """
    timestamp: str
    actor: str
    entity_id: str
    entity_type: str
    old_state: str
    new_state: str
    note: str = ""


# ---------------------------------------------------------------------------
# ECR
# ---------------------------------------------------------------------------

ECR_STATES = frozenset({
    "draft",
    "submitted",
    "under_review",
    "approved",
    "rejected",
    "withdrawn",
})

ECR_TERMINAL_STATES = frozenset({"approved", "rejected", "withdrawn"})

ECR_CLASSIFICATIONS = frozenset({"minor", "major", "critical"})

ECR_DISPOSITIONS = frozenset({"use_as_is", "rework", "scrap", "redesign"})


@dataclass
class ECR:
    """Engineering Change Request.

    Attributes:
        id:                   Unique identifier (e.g. "ECR-2025-001").
        title:                Short human-readable title.
        description:          Full description of the problem / proposed change.
        originator:           User id of the person raising the ECR.
        affected_parts:       Part ids affected by this change.
        rationale:            Engineering justification for the change.
        classification:       Severity class — minor / major / critical.
        proposed_disposition: Outcome proposed — use_as_is / rework / scrap / redesign.
        state:                Current workflow state.
        created_at:           ISO-8601 UTC datetime string.
        reviewers:            List of reviewer user ids assigned to evaluate this ECR.
        votes:                Dict mapping reviewer id → "approve" | "reject".
        required_approvals:   Minimum number of approve votes needed to move to
                              'approved' state automatically (default 2).
    """
    id: str
    title: str
    description: str
    originator: str
    affected_parts: list[str] = field(default_factory=list)
    rationale: str = ""
    classification: str = "minor"
    proposed_disposition: str = "rework"
    state: str = "draft"
    created_at: str = field(default_factory=_utcnow_iso)
    reviewers: list[str] = field(default_factory=list)
    votes: dict[str, str] = field(default_factory=dict)
    required_approvals: int = 2

    def __post_init__(self) -> None:
        if self.classification not in ECR_CLASSIFICATIONS:
            raise ValueError(
                f"ECR classification must be one of {sorted(ECR_CLASSIFICATIONS)}, "
                f"got {self.classification!r}"
            )
        if self.proposed_disposition not in ECR_DISPOSITIONS:
            raise ValueError(
                f"ECR proposed_disposition must be one of {sorted(ECR_DISPOSITIONS)}, "
                f"got {self.proposed_disposition!r}"
            )
        if self.state not in ECR_STATES:
            raise ValueError(
                f"ECR state must be one of {sorted(ECR_STATES)}, got {self.state!r}"
            )


# ---------------------------------------------------------------------------
# ECO
# ---------------------------------------------------------------------------

ECO_IMPL_STATES = frozenset({
    "planned",
    "in_progress",
    "verified",
    "released",
    "closed",
})

REQUIRED_SIGNOFF_ROLES = frozenset({"engineering", "manufacturing", "qa"})


@dataclass
class ECO:
    """Engineering Change Order.

    Attributes:
        id:                   Unique identifier (e.g. "ECO-2025-001").
        references_ecrs:      List of ECR ids that this ECO implements.
        description:          What will be changed and how.
        affected_parts:       Part ids that will be updated by this ECO.
        effective_date:       ``date`` on which the changes become effective.
        implementation_state: Workflow state of the ECO.
        engineering_signoff:  User id who signed off from engineering (or None).
        manufacturing_signoff: User id who signed off from manufacturing (or None).
        qa_signoff:           User id who signed off from QA (or None).
        created_at:           ISO-8601 UTC datetime string.
    """
    id: str
    references_ecrs: list[str] = field(default_factory=list)
    description: str = ""
    affected_parts: list[str] = field(default_factory=list)
    effective_date: date | None = None
    implementation_state: str = "planned"
    engineering_signoff: str | None = None
    manufacturing_signoff: str | None = None
    qa_signoff: str | None = None
    created_at: str = field(default_factory=_utcnow_iso)

    def __post_init__(self) -> None:
        if self.implementation_state not in ECO_IMPL_STATES:
            raise ValueError(
                f"ECO implementation_state must be one of {sorted(ECO_IMPL_STATES)}, "
                f"got {self.implementation_state!r}"
            )

    def _all_signoffs_present(self) -> bool:
        return (
            self.engineering_signoff is not None
            and self.manufacturing_signoff is not None
            and self.qa_signoff is not None
        )


# ---------------------------------------------------------------------------
# ChangeBoard
# ---------------------------------------------------------------------------

class ChangeBoard:
    """ISO 10007 Engineering Change Board.

    Manages the full ECR → ECO lifecycle with immutable audit trail.

    Usage::

        board = ChangeBoard()

        ecr = ECR(id="ECR-001", title="Fix tolerance", ...)
        board.submit_ecr(ecr)

        board.review_ecr("ECR-001", reviewer="alice", decision="approve")
        board.review_ecr("ECR-001", reviewer="bob", decision="approve")
        # → ECR auto-transitions to 'approved' after 2 approvals

        eco = ECO(id="ECO-001", references_ecrs=["ECR-001"],
                  affected_parts=["P-001"], effective_date=date(2025, 7, 1))
        board.escalate_to_eco("ECR-001", eco)

        board.implement_eco("ECO-001", signer="carol", role="engineering")
        board.implement_eco("ECO-001", signer="dave",  role="manufacturing")
        board.implement_eco("ECO-001", signer="eve",   role="qa")
        # → ECO auto-transitions to 'released' after all 3 signoffs
    """

    def __init__(self) -> None:
        self._ecrs: dict[str, ECR] = {}
        self._ecos: dict[str, ECO] = {}
        # Tuple makes the audit trail immutable at the collection level.
        self._audit: tuple[AuditEntry, ...] = ()
        # parts registry: part_id → effective_from date (updated on ECO release)
        self._part_effectivity: dict[str, date | None] = {}

    # ------------------------------------------------------------------
    # ECR operations
    # ------------------------------------------------------------------

    def submit_ecr(self, ecr: ECR) -> ECR:
        """Submit an ECR for review.

        Transitions ECR from 'draft' → 'submitted'.
        Routes to all listed reviewers.

        Args:
            ecr: ECR instance (must be in 'draft' state).

        Returns:
            Updated ECR (also mutated in place for convenience).

        Raises:
            ValueError: If the ECR is not in 'draft' state.
            KeyError:   If an ECR with the same id already exists.
        """
        if ecr.id in self._ecrs:
            raise KeyError(f"ECR '{ecr.id}' already registered with ChangeBoard")
        if ecr.state != "draft":
            raise ValueError(
                f"ECR '{ecr.id}' must be in 'draft' state to submit; "
                f"current state: {ecr.state!r}"
            )

        old = ecr.state
        ecr.state = "submitted"
        self._ecrs[ecr.id] = ecr
        self._append_audit(AuditEntry(
            timestamp=_utcnow_iso(),
            actor=ecr.originator,
            entity_id=ecr.id,
            entity_type="ECR",
            old_state=old,
            new_state="submitted",
            note=f"Submitted by originator {ecr.originator!r}; "
                 f"routed to reviewers: {ecr.reviewers}",
        ))
        return ecr

    def review_ecr(self, ecr_id: str, reviewer: str, decision: str) -> ECR:
        """Record a reviewer's vote on an ECR.

        When the accumulated approvals reach ``ecr.required_approvals``, the
        ECR transitions to 'approved'.  If the majority of all assigned
        reviewers have voted 'reject', the ECR transitions to 'rejected'.

        Args:
            ecr_id:   ECR identifier.
            reviewer: Reviewer user id.
            decision: "approve" or "reject".

        Returns:
            Updated ECR.

        Raises:
            KeyError:   If the ECR is not found.
            ValueError: If the ECR is not in 'submitted' or 'under_review' state,
                        or if ``decision`` is not "approve"/"reject",
                        or if the reviewer is not in the ECR's reviewers list.
        """
        ecr = self._get_ecr(ecr_id)
        if ecr.state not in {"submitted", "under_review"}:
            raise ValueError(
                f"ECR '{ecr_id}' must be in 'submitted' or 'under_review' state "
                f"to receive reviews; current state: {ecr.state!r}"
            )
        if decision not in {"approve", "reject"}:
            raise ValueError(
                f"review decision must be 'approve' or 'reject', got {decision!r}"
            )
        if ecr.reviewers and reviewer not in ecr.reviewers:
            raise ValueError(
                f"Reviewer {reviewer!r} is not in the assigned reviewers list "
                f"for ECR '{ecr_id}': {ecr.reviewers}"
            )

        old_state = ecr.state

        # Move to under_review on first vote if still 'submitted'
        if ecr.state == "submitted":
            ecr.state = "under_review"
            self._append_audit(AuditEntry(
                timestamp=_utcnow_iso(),
                actor=reviewer,
                entity_id=ecr_id,
                entity_type="ECR",
                old_state="submitted",
                new_state="under_review",
                note=f"First review vote received from {reviewer!r}",
            ))
            old_state = "under_review"

        ecr.votes[reviewer] = decision

        # Tally votes
        approve_count = sum(1 for v in ecr.votes.values() if v == "approve")
        reject_count = sum(1 for v in ecr.votes.values() if v == "reject")

        prev_state = ecr.state

        if approve_count >= ecr.required_approvals:
            ecr.state = "approved"
        elif ecr.reviewers and reject_count > len(ecr.reviewers) // 2:
            # Majority rejection
            ecr.state = "rejected"
        elif not ecr.reviewers and reject_count >= ecr.required_approvals:
            # No explicit reviewer list — use same threshold for rejections
            ecr.state = "rejected"

        if ecr.state != prev_state:
            self._append_audit(AuditEntry(
                timestamp=_utcnow_iso(),
                actor=reviewer,
                entity_id=ecr_id,
                entity_type="ECR",
                old_state=prev_state,
                new_state=ecr.state,
                note=(
                    f"Vote by {reviewer!r}: {decision!r}. "
                    f"Tally: {approve_count} approve / {reject_count} reject."
                ),
            ))
        else:
            self._append_audit(AuditEntry(
                timestamp=_utcnow_iso(),
                actor=reviewer,
                entity_id=ecr_id,
                entity_type="ECR",
                old_state=ecr.state,
                new_state=ecr.state,
                note=(
                    f"Vote recorded by {reviewer!r}: {decision!r}. "
                    f"Tally: {approve_count} approve / {reject_count} reject. "
                    f"Awaiting more votes."
                ),
            ))

        return ecr

    def escalate_to_eco(self, ecr_id: str, eco: ECO) -> ECO:
        """Escalate an approved ECR to an Engineering Change Order.

        Args:
            ecr_id: The ECR that authorises this ECO.
            eco:    ECO instance to register (must not already exist).

        Returns:
            The registered ECO.

        Raises:
            KeyError:   If the ECR is not found, or if the ECO id already exists.
            ValueError: If the ECR is not in 'approved' state.
        """
        ecr = self._get_ecr(ecr_id)
        if ecr.state != "approved":
            raise ValueError(
                f"ECR '{ecr_id}' must be in 'approved' state to escalate to ECO; "
                f"current state: {ecr.state!r}"
            )
        if eco.id in self._ecos:
            raise KeyError(f"ECO '{eco.id}' already registered with ChangeBoard")

        # Ensure the ECO back-references the authorising ECR
        if ecr_id not in eco.references_ecrs:
            eco.references_ecrs.append(ecr_id)

        self._ecos[eco.id] = eco
        self._append_audit(AuditEntry(
            timestamp=_utcnow_iso(),
            actor=ecr.originator,
            entity_id=eco.id,
            entity_type="ECO",
            old_state="(new)",
            new_state=eco.implementation_state,
            note=f"ECO created from approved ECR '{ecr_id}'",
        ))
        return eco

    # ------------------------------------------------------------------
    # ECO operations
    # ------------------------------------------------------------------

    def implement_eco(self, eco_id: str, signer: str, role: str) -> ECO:
        """Record a functional signoff on an ECO.

        Required roles: engineering, manufacturing, qa.
        When all three are present, the ECO transitions to 'released' and
        effectivity propagation runs.

        Args:
            eco_id: ECO identifier.
            signer: User id of the signer.
            role:   One of "engineering", "manufacturing", "qa".

        Returns:
            Updated ECO.

        Raises:
            KeyError:   ECO not found.
            ValueError: ECO not in a signoff-eligible state, or invalid role.
        """
        eco = self._get_eco(eco_id)
        if eco.implementation_state not in {"planned", "in_progress", "verified"}:
            raise ValueError(
                f"ECO '{eco_id}' is in state {eco.implementation_state!r}; "
                f"signoffs are not accepted in this state."
            )
        if role not in REQUIRED_SIGNOFF_ROLES:
            raise ValueError(
                f"role must be one of {sorted(REQUIRED_SIGNOFF_ROLES)}, got {role!r}"
            )

        old_impl_state = eco.implementation_state

        if role == "engineering":
            eco.engineering_signoff = signer
        elif role == "manufacturing":
            eco.manufacturing_signoff = signer
        elif role == "qa":
            eco.qa_signoff = signer

        # Advance to in_progress once any signoff is recorded
        if eco.implementation_state == "planned":
            eco.implementation_state = "in_progress"
            self._append_audit(AuditEntry(
                timestamp=_utcnow_iso(),
                actor=signer,
                entity_id=eco_id,
                entity_type="ECO",
                old_state="planned",
                new_state="in_progress",
                note=f"First signoff by {signer!r} ({role})",
            ))
            old_impl_state = "in_progress"

        self._append_audit(AuditEntry(
            timestamp=_utcnow_iso(),
            actor=signer,
            entity_id=eco_id,
            entity_type="ECO",
            old_state=old_impl_state,
            new_state=eco.implementation_state,
            note=f"Signoff recorded: role={role!r}, signer={signer!r}",
        ))

        # Auto-release when all three signoffs are present
        if eco._all_signoffs_present():
            old = eco.implementation_state
            eco.implementation_state = "released"
            self._propagate_effectivity(eco)
            self._append_audit(AuditEntry(
                timestamp=_utcnow_iso(),
                actor=signer,
                entity_id=eco_id,
                entity_type="ECO",
                old_state=old,
                new_state="released",
                note=(
                    f"All signoffs complete (eng={eco.engineering_signoff}, "
                    f"mfg={eco.manufacturing_signoff}, qa={eco.qa_signoff}). "
                    f"ECO released; effectivity date={eco.effective_date}."
                ),
            ))

        return eco

    # ------------------------------------------------------------------
    # Effectivity propagation
    # ------------------------------------------------------------------

    def _propagate_effectivity(self, eco: ECO) -> None:
        """Update parts registry with new effective_from from the released ECO.

        Called automatically when an ECO transitions to 'released'.
        The ``effective_from`` for each affected part is set to
        ``eco.effective_date``.  Subsequent ``effectivity_bom`` calls using
        a date >= eco.effective_date will return the new revision.
        """
        for part_id in eco.affected_parts:
            self._part_effectivity[part_id] = eco.effective_date

    def get_part_effective_from(self, part_id: str) -> date | None:
        """Return the current effective_from date for *part_id* (or None)."""
        return self._part_effectivity.get(part_id)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_ecr(self, ecr_id: str) -> ECR:
        """Return the ECR with *ecr_id*.  Raises KeyError if not found."""
        return self._get_ecr(ecr_id)

    def get_eco(self, eco_id: str) -> ECO:
        """Return the ECO with *eco_id*.  Raises KeyError if not found."""
        return self._get_eco(eco_id)

    def audit_trail(self) -> list[AuditEntry]:
        """Return a copy of the immutable audit trail as a list."""
        return list(self._audit)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_ecr(self, ecr_id: str) -> ECR:
        try:
            return self._ecrs[ecr_id]
        except KeyError:
            raise KeyError(f"ECR '{ecr_id}' not found in ChangeBoard")

    def _get_eco(self, eco_id: str) -> ECO:
        try:
            return self._ecos[eco_id]
        except KeyError:
            raise KeyError(f"ECO '{eco_id}' not found in ChangeBoard")

    def _append_audit(self, entry: AuditEntry) -> None:
        """Append an AuditEntry to the immutable tuple."""
        self._audit = self._audit + (entry,)
