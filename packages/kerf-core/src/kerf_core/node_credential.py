"""The node's single password.

Kerf is moving from accounts to one credential per node: you install it, you
set a password on first load, and that password is what a session is exchanged
for. No usernames, no email, no roles — there is nobody to have a different
role from. Recovery is `kerf admin set-password`, not a reset email, because a
self-hosted node has no mail transport and pretending otherwise is how
`/auth/forgot-password` ended up returning 501.

FIRST RUN IS A CLAIM, AND CLAIMS CAN BE RACED
---------------------------------------------
An unconfigured node is claimable by whoever reaches it first. On loopback that
is you, by construction. On any other bind it is whoever gets there first, and
the honest answer is not to allow it: :func:`may_configure_over_network`
refuses remote setup on a non-loopback bind, and the operator sets the password
from the CLI, where reaching the machine already proves the point.

This mirrors how the terminal is gated — on the listen address, because that is
what actually determines who can reach a thing.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any, Optional

import bcrypt

from kerf_core.bind import get_bind_host, is_loopback
from kerf_core.config import get_settings

# Same construction as kerf_auth.hash_password: bcrypt over a peppered
# password, so the pepper has to be compromised as well as the database.
_PEPPER_ENV = "PASSWORD_PEPPER"

# Compared against when no credential is set, so "unconfigured" and "wrong
# password" take the same time. Without it, a stopwatch tells you whether a
# node is claimable.
_DUMMY_HASH = bcrypt.hashpw(b"kerf-node-dummy-guard", bcrypt.gensalt()).decode("utf-8")

# Short enough to type, long enough that guessing is not the attack.
MIN_PASSWORD_LENGTH = 8


def _pepper() -> bytes:
    settings = get_settings()
    return str(getattr(settings, "password_pepper", "") or os.environ.get(_PEPPER_ENV, "")).encode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8") + _pepper(), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    """Constant-time-ish check that also burns a hash when unconfigured."""
    candidate = stored_hash or _DUMMY_HASH
    try:
        matched = bcrypt.checkpw(password.encode("utf-8") + _pepper(), candidate.encode("utf-8"))
    except (ValueError, TypeError):
        return False
    # A node with no credential must never authenticate, even against a hash
    # that happens to match the dummy.
    return bool(matched and stored_hash)


@dataclass(frozen=True)
class SetupState:
    """What the first-load screen needs to know."""

    configured: bool
    can_configure_here: bool
    reason: str


def may_configure_over_network() -> tuple[bool, str]:
    """Whether first-run setup may happen through the browser.

    Claiming an unconfigured node is claiming the machine. Over loopback the
    claimant is necessarily whoever is sitting at it. Over a network it is
    whoever arrives first, which is a race with a stranger, so it is refused
    and the operator uses the CLI instead.
    """
    host = get_bind_host()
    if is_loopback(host):
        return True, "Loopback bind — you are the only one who can reach this."
    return False, (
        f"This server is bound to {host}, not loopback, so whoever reached it "
        "first could claim it. Set the password on the machine itself with "
        "`kerf admin set-password`, then sign in."
    )


async def get_hash(conn) -> Optional[str]:
    row = await conn.fetchrow("SELECT password_hash FROM node_credential WHERE singleton = true")
    return row["password_hash"] if row else None


async def is_configured(conn) -> bool:
    return await get_hash(conn) is not None


async def setup_state(conn) -> SetupState:
    configured = await is_configured(conn)
    allowed, reason = may_configure_over_network()
    return SetupState(
        configured=configured,
        can_configure_here=allowed,
        reason="" if configured else reason,
    )


async def set_password(conn, password: str) -> None:
    """Set or replace the node password. Callers enforce who may do this."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")

    await conn.execute(
        """
        INSERT INTO node_credential (singleton, password_hash)
        VALUES (true, $1)
        ON CONFLICT (singleton) DO UPDATE
            SET password_hash = EXCLUDED.password_hash,
                updated_at = now()
        """,
        hash_password(password),
    )


async def check_password(conn, password: str) -> bool:
    return verify_password(password, await get_hash(conn))


def suggest_password() -> str:
    """A password for the operator to accept when they cannot think of one.

    Offered by `kerf admin set-password` rather than generated silently: a
    credential the user never saw is one they cannot write down.
    """
    return secrets.token_urlsafe(18)


def public_state(state: SetupState) -> dict[str, Any]:
    return {
        "configured": state.configured,
        "can_configure_here": state.can_configure_here,
        "reason": state.reason,
    }
