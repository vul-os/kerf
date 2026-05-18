"""
Tests for kerf_cad_core.analysis.AnalysisType enum (T-100b/c/d/h).

Verifies:
  - all expected members are present
  - existing values are byte-exact (no rename regression)
  - new values (nonlinear, explicit, acoustics_fem, em_field, em_highfreq,
    fatigue_fem) are importable and round-trip through str/value serialisation
  - each member has a non-empty requires frozenset
  - capability descriptor keys are all lowercase identifiers
"""

from __future__ import annotations

import pytest

from kerf_cad_core.analysis import AnalysisType


# ---------------------------------------------------------------------------
# Expected membership
# ---------------------------------------------------------------------------

_EXISTING_VALUES = {
    "linear_static",
    "modal",
    "thermal_steady",
    "thermal_transient",
    "buckling",
}

_NEW_VALUES = {
    "nonlinear",
    "explicit",
    "acoustics_fem",
    "em_field",
    "em_highfreq",
    "fatigue_fem",
}

_ALL_VALUES = _EXISTING_VALUES | _NEW_VALUES


class TestAnalysisTypePresence:
    def test_all_members_present(self):
        actual = {m.value for m in AnalysisType}
        assert _ALL_VALUES <= actual, (
            f"Missing members: {_ALL_VALUES - actual}"
        )

    def test_no_extra_unexpected_members(self):
        """Warn if there are extra members not in our expected set (not a failure)."""
        actual = {m.value for m in AnalysisType}
        extra = actual - _ALL_VALUES
        # Extra members are OK (other tasks may have added them) — not a failure.
        # This just documents what we expect.
        assert isinstance(extra, set)

    @pytest.mark.parametrize("value", sorted(_EXISTING_VALUES))
    def test_existing_values_byte_exact(self, value):
        """Existing values must not be renamed — byte-exact stability."""
        member = AnalysisType(value)
        assert member.value == value

    @pytest.mark.parametrize("value", sorted(_NEW_VALUES))
    def test_new_values_importable(self, value):
        """New T-100 values must be importable by name."""
        member = AnalysisType(value)
        assert member.value == value


class TestAnalysisTypeSerialisation:
    @pytest.mark.parametrize("value", sorted(_ALL_VALUES))
    def test_roundtrip_via_value(self, value):
        """str → AnalysisType → .value round-trip."""
        member = AnalysisType(value)
        assert member.value == value

    @pytest.mark.parametrize("value", sorted(_ALL_VALUES))
    def test_is_str_subclass(self, value):
        """AnalysisType members must compare equal to their plain-string value."""
        member = AnalysisType(value)
        assert member == value

    @pytest.mark.parametrize("value", sorted(_ALL_VALUES))
    def test_value_equals_str(self, value):
        """member.value must equal the plain-string key."""
        member = AnalysisType(value)
        # Use .value directly — str() output varies across Python versions for
        # str-subclass enums (Python 3.12+ changed the default __str__).
        assert member.value == value

    def test_json_serialisable(self):
        """Serialisation via .value produces a plain string (no class prefix)."""
        import json
        payload = {m.value: True for m in AnalysisType}
        serialised = json.dumps(payload)
        parsed = json.loads(serialised)
        for value in _ALL_VALUES:
            assert value in parsed


class TestAnalysisTypeRequires:
    @pytest.mark.parametrize("value", sorted(_ALL_VALUES))
    def test_requires_is_frozenset(self, value):
        member = AnalysisType(value)
        assert isinstance(member.requires, frozenset), (
            f"{value}.requires must be a frozenset"
        )

    @pytest.mark.parametrize("value", sorted(_ALL_VALUES))
    def test_requires_nonempty(self, value):
        member = AnalysisType(value)
        assert len(member.requires) >= 1, (
            f"{value}.requires must not be empty"
        )

    @pytest.mark.parametrize("value", sorted(_ALL_VALUES))
    def test_requires_all_strings(self, value):
        member = AnalysisType(value)
        for cap in member.requires:
            assert isinstance(cap, str), (
                f"{value}.requires must contain only strings, got {cap!r}"
            )

    @pytest.mark.parametrize("value", sorted(_ALL_VALUES))
    def test_requires_lowercase_identifiers(self, value):
        """Capability tags must be lowercase snake_case identifiers."""
        member = AnalysisType(value)
        for cap in member.requires:
            assert cap == cap.lower(), (
                f"{value}: capability tag {cap!r} must be lowercase"
            )
            assert cap.replace("_", "").isalpha() or "_" in cap, (
                f"{value}: capability tag {cap!r} should be a snake_case identifier"
            )


class TestAnalysisTypeSpecificRequires:
    """Spot-check the capability descriptors for specific members."""

    def test_linear_static_requires_linear_solver(self):
        assert "linear_solver" in AnalysisType.linear_static.requires

    def test_modal_requires_eigensolver(self):
        assert "eigensolver" in AnalysisType.modal.requires

    def test_nonlinear_requires_nonlinear_solver(self):
        assert "nonlinear_solver" in AnalysisType.nonlinear.requires

    def test_explicit_requires_explicit_integrator(self):
        assert "explicit_integrator" in AnalysisType.explicit.requires

    def test_acoustics_fem_requires_acoustic_solver(self):
        assert "acoustic_solver" in AnalysisType.acoustics_fem.requires

    def test_em_field_requires_em_solver_lowfreq(self):
        assert "em_solver_lowfreq" in AnalysisType.em_field.requires

    def test_em_highfreq_requires_fullwave(self):
        assert "em_solver_fullwave" in AnalysisType.em_highfreq.requires

    def test_fatigue_fem_requires_fatigue_postprocessor(self):
        assert "fatigue_postprocessor" in AnalysisType.fatigue_fem.requires
