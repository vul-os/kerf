"""Smoke tests for the migrated kerf_cloud.distributors package.

These are import-level and logic tests that require no DB or network.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from kerf_cloud.distributors.service import (
    ALL_PROVIDERS,
    PROVIDER_DIGIKEY,
    PROVIDER_LCSC,
    PROVIDER_MCMASTER,
    PROVIDER_MOUSER,
    Credentials,
    DistributorAuthError,
    DistributorNotConfigured,
    DistributorNotFound,
    DistributorNotSupported,
    DistributorPart,
    Service,
    validate_credentials,
)
from kerf_cloud.distributors.sync import is_stale


# ---------------------------------------------------------------------------
# service.py
# ---------------------------------------------------------------------------


def test_all_providers_constant():
    assert set(ALL_PROVIDERS) == {PROVIDER_DIGIKEY, PROVIDER_MOUSER, PROVIDER_LCSC, PROVIDER_MCMASTER}


def test_credentials_defaults():
    c = Credentials()
    assert c.client_id == ""
    assert c.client_secret == ""
    assert c.api_key == ""


def test_validate_credentials_digikey_ok():
    validate_credentials(PROVIDER_DIGIKEY, Credentials(client_id="id", client_secret="secret"))


def test_validate_credentials_digikey_missing():
    with pytest.raises(ValueError):
        validate_credentials(PROVIDER_DIGIKEY, Credentials())


def test_validate_credentials_mouser_ok():
    validate_credentials(PROVIDER_MOUSER, Credentials(api_key="key"))


def test_validate_credentials_mouser_missing():
    with pytest.raises(ValueError):
        validate_credentials(PROVIDER_MOUSER, Credentials())


def test_validate_credentials_lcsc_ok():
    validate_credentials(PROVIDER_LCSC, Credentials(api_key="key"))


def test_validate_credentials_mcmaster_no_creds_needed():
    # McMaster has no public API, no credentials required
    validate_credentials(PROVIDER_MCMASTER, Credentials())


def test_validate_credentials_unknown():
    with pytest.raises(ValueError):
        validate_credentials("unknown_dist", Credentials())


# ---------------------------------------------------------------------------
# sync.py — is_stale()
# ---------------------------------------------------------------------------


def _make_part_json(fetched_at_iso: str) -> str:
    doc = {
        "name": "test-part",
        "distributors": [
            {"name": PROVIDER_DIGIKEY, "sku": "123", "fetched_at": fetched_at_iso}
        ],
    }
    return json.dumps(doc)


def test_is_stale_fresh():
    now = datetime.utcnow()
    recent = (now - timedelta(hours=1)).isoformat() + "Z"
    assert not is_stale(_make_part_json(recent))


def test_is_stale_old():
    old = (datetime.utcnow() - timedelta(hours=30)).isoformat() + "Z"
    assert is_stale(_make_part_json(old))


def test_is_stale_missing_fetched_at():
    doc = {"distributors": [{"name": PROVIDER_DIGIKEY, "sku": "123"}]}
    assert is_stale(json.dumps(doc))


def test_is_stale_no_distributors():
    doc = {"name": "part-no-distributors"}
    assert not is_stale(json.dumps(doc))


def test_is_stale_invalid_json():
    assert not is_stale("not-json")


# ---------------------------------------------------------------------------
# mcmaster.py — always raises DistributorNotSupported
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcmaster_lookup_raises():
    from kerf_cloud.distributors.mcmaster import McMasterService

    svc = McMasterService()
    with pytest.raises(DistributorNotSupported):
        await svc.lookup(None, "some-sku")


@pytest.mark.asyncio
async def test_mcmaster_search_raises():
    from kerf_cloud.distributors.mcmaster import McMasterService

    svc = McMasterService()
    with pytest.raises(DistributorNotSupported):
        await svc.search(None, "some query", 5)
