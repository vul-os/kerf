"""
Analytic oracles for draft notation round-trips.

DoD requirements covered:
  - draft notation round-trips through writer/reader (WIF and JSON)
  - canonical drafts are internally consistent
  - Draft.validate() catches bad indices
"""

from __future__ import annotations

import json
import pytest

from kerf_textiles.draft import (
    Draft,
    draft_to_dict,
    draft_from_dict,
    canonical_plain_draft,
    canonical_twill_draft,
    canonical_satin_draft,
)
from kerf_textiles.export import draft_to_wif, draft_from_wif


# ---------------------------------------------------------------------------
# Draft dataclass
# ---------------------------------------------------------------------------

class TestDraftDataclass:
    def test_validate_valid(self):
        d = canonical_plain_draft()
        d.validate()  # should not raise

    def test_validate_bad_threading(self):
        d = canonical_plain_draft()
        d.threading[0] = 99  # out of range
        with pytest.raises(ValueError, match="threading"):
            d.validate()

    def test_validate_bad_treadling(self):
        d = canonical_plain_draft()
        d.treadling[0] = 99
        with pytest.raises(ValueError, match="treadling"):
            d.validate()

    def test_validate_wrong_tie_up_rows(self):
        d = canonical_plain_draft()
        d.tie_up.append([True, False])  # one extra row
        with pytest.raises(ValueError, match="tie_up"):
            d.validate()

    def test_validate_wrong_tie_up_cols(self):
        d = canonical_plain_draft()
        d.tie_up[0] = [True]  # wrong number of cols
        with pytest.raises(ValueError, match="tie_up"):
            d.validate()

    def test_n_warp_ends_property(self):
        d = canonical_plain_draft()
        assert d.n_warp_ends == len(d.threading)

    def test_n_picks_property(self):
        d = canonical_plain_draft()
        assert d.n_picks == len(d.treadling)


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------

class TestDraftJsonRoundTrip:
    def _roundtrip(self, draft: Draft) -> Draft:
        data = draft_to_dict(draft)
        return draft_from_dict(data)

    def test_plain_roundtrip(self):
        d = canonical_plain_draft()
        d2 = self._roundtrip(d)
        assert d2.threading == d.threading
        assert d2.treadling == d.treadling
        assert d2.tie_up == d.tie_up
        assert d2.n_shafts == d.n_shafts
        assert d2.n_treadles == d.n_treadles

    def test_twill_roundtrip(self):
        d = canonical_twill_draft(over=2, under=1)
        d2 = self._roundtrip(d)
        assert d2.threading == d.threading
        assert d2.tie_up == d.tie_up

    def test_satin_roundtrip(self):
        d = canonical_satin_draft(shafts=5, move=2)
        d2 = self._roundtrip(d)
        assert d2.threading == d.threading
        assert d2.tie_up == d.tie_up

    def test_dict_is_json_serialisable(self):
        d = canonical_plain_draft()
        data = draft_to_dict(d)
        json_str = json.dumps(data)
        recovered = json.loads(json_str)
        d2 = draft_from_dict(recovered)
        assert d2.threading == d.threading

    def test_roundtrip_preserves_notes(self):
        d = canonical_plain_draft()
        d.notes = "test note ñ unicode"
        d2 = self._roundtrip(d)
        assert d2.notes == d.notes

    def test_roundtrip_preserves_name(self):
        d = canonical_plain_draft()
        d2 = self._roundtrip(d)
        assert d2.name == d.name


# ---------------------------------------------------------------------------
# WIF round-trip
# ---------------------------------------------------------------------------

class TestDraftWifRoundTrip:
    def _roundtrip(self, draft: Draft) -> Draft:
        wif = draft_to_wif(draft)
        return draft_from_wif(wif)

    def test_plain_wif_roundtrip(self):
        """
        DoD oracle: draft notation round-trips through WIF writer/reader.
        """
        d = canonical_plain_draft()
        d2 = self._roundtrip(d)
        assert d2.threading == d.threading
        assert d2.treadling == d.treadling
        assert d2.n_shafts == d.n_shafts
        assert d2.n_treadles == d.n_treadles

    def test_wif_tie_up_roundtrip(self):
        d = canonical_plain_draft()
        d2 = self._roundtrip(d)
        assert d2.tie_up == d.tie_up

    def test_twill_wif_roundtrip(self):
        d = canonical_twill_draft(over=2, under=1)
        d2 = self._roundtrip(d)
        assert d2.threading == d.threading
        assert d2.treadling == d.treadling
        assert d2.tie_up == d.tie_up

    def test_satin_wif_roundtrip(self):
        d = canonical_satin_draft(shafts=5, move=2)
        d2 = self._roundtrip(d)
        assert d2.threading == d.threading
        assert d2.tie_up == d.tie_up

    def test_wif_contains_sections(self):
        d = canonical_plain_draft()
        wif = draft_to_wif(d)
        assert "[WIF]" in wif
        assert "[THREADING]" in wif
        assert "[TREADLING]" in wif
        assert "[TIEUP]" in wif

    def test_wif_is_plain_text(self):
        d = canonical_plain_draft()
        wif = draft_to_wif(d)
        assert isinstance(wif, str)
        assert len(wif) > 50

    def test_wif_round_trip_validates(self):
        d = canonical_twill_draft(over=3, under=1)
        wif = draft_to_wif(d)
        d2 = draft_from_wif(wif)
        d2.validate()  # must not raise


# ---------------------------------------------------------------------------
# Canonical draft factories
# ---------------------------------------------------------------------------

class TestCanonicalDrafts:
    def test_plain_draft_is_valid(self):
        d = canonical_plain_draft()
        assert d.n_shafts == 2
        assert d.n_treadles == 2
        d.validate()

    def test_twill_draft_is_valid(self):
        for over, under in [(2, 1), (3, 1), (2, 2), (1, 3)]:
            d = canonical_twill_draft(over=over, under=under)
            assert d.n_shafts == over + under
            d.validate()

    def test_satin_draft_is_valid(self):
        d = canonical_satin_draft(shafts=5, move=2)
        assert d.n_shafts == 5
        d.validate()

    def test_satin_draft_invalid_gcd(self):
        with pytest.raises(ValueError):
            canonical_satin_draft(shafts=6, move=3)

    def test_plain_tie_up_structure(self):
        """Plain weave: shaft 0 lifted by treadle 0 only; shaft 1 by treadle 1 only."""
        d = canonical_plain_draft()
        assert d.tie_up[0][0] is True
        assert d.tie_up[0][1] is False
        assert d.tie_up[1][0] is False
        assert d.tie_up[1][1] is True

    def test_twill_tie_up_has_correct_count(self):
        """Each treadle lifts exactly *over* shafts."""
        over = 2
        d = canonical_twill_draft(over=over, under=1)
        for treadle in range(d.n_treadles):
            count = sum(1 for shaft in range(d.n_shafts) if d.tie_up[shaft][treadle])
            assert count == over, f"treadle {treadle}: lifts {count} shafts, expected {over}"

    def test_satin_tie_up_one_per_treadle(self):
        """Each treadle lifts exactly one shaft in satin."""
        d = canonical_satin_draft(shafts=5, move=2)
        for treadle in range(d.n_treadles):
            count = sum(1 for shaft in range(d.n_shafts) if d.tie_up[shaft][treadle])
            assert count == 1, f"treadle {treadle}: lifts {count} shafts, expected 1"
