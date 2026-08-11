"""routes_setup.py — first run: set the node password, then sign in with it.

Kerf is collapsing from accounts to one credential per node. These are the
endpoints for that: ask whether a password has been set, set it once, and
exchange it for a session.

Why this exists at all: `local_mode` — the default, and the only mode a desktop
install has ever used — hands out a full session from `/auth/bootstrap-local`
with **no credential whatsoever**. Anything that can reach the port is signed
in. On a machine where the browser can be pointed at loopback by a hostile page
(DNS rebinding is the usual route), "bound to loopback" is not on its own a
credential. So there is now a password, set on first load.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from kerf_core import node_credential
from kerf_core.db.connection import get_pool_required
from kerf_core.dependencies import rate_limit

router = APIRouter()


class SetPasswordRequest(BaseModel):
    password: str


class SignInRequest(BaseModel):
    password: str


@router.get("/setup/state")
async def setup_state() -> dict[str, Any]:
    """GET /api/setup/state — has a password been set, and may it be set here?

    Unauthenticated by necessity: it is what the app asks before it knows
    whether there is anything to authenticate against. It reveals only whether
    the node is claimed, which is the thing a first-run screen has to branch on.
    """
    pool = await get_pool_required()
    async with pool.acquire() as conn:
        return node_credential.public_state(await node_credential.setup_state(conn))


@router.post("/setup/password", status_code=status.HTTP_201_CREATED)
async def set_node_password(
    req: SetPasswordRequest,
    # Claiming is one-shot, but probing "is it claimed yet" is cheap to
    # repeat; this keeps a scanner from hammering it.
    _rl: None = Depends(rate_limit(max_per_window=10, window_seconds=3600, key_prefix="setup:claim")),
) -> dict[str, Any]:
    """POST /api/setup/password — claim an unconfigured node.

    Succeeds exactly once. Re-setting the password later is deliberately not
    possible through the browser: an attacker with a live session should not be
    able to lock the owner out, and the owner can always reach the machine.
    `kerf admin set-password` is the supported way to change it.
    """
    pool = await get_pool_required()
    async with pool.acquire() as conn:
        if await node_credential.is_configured(conn):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This node already has a password. Change it on the machine "
                    "with `kerf admin set-password`."
                ),
            )

        allowed, reason = node_credential.may_configure_over_network()
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)

        try:
            await node_credential.set_password(conn, req.password)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return {"configured": True}


@router.post("/setup/signin")
async def sign_in(
    req: SignInRequest,
    # One password guarding a whole node makes brute force the obvious attack.
    _rl: None = Depends(rate_limit(max_per_window=10, window_seconds=60, key_prefix="setup:signin")),
) -> Any:
    """POST /api/setup/signin — exchange the node password for a session.

    A single wrong-password answer for both "no password set" and "wrong
    password": which of the two it is tells an attacker whether the node is
    claimable, which is the more useful fact of the pair.
    """
    pool = await get_pool_required()
    async with pool.acquire() as conn:
        if not await node_credential.check_password(conn, req.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="incorrect password",
            )

    # Session issuance still goes through the account machinery while it
    # exists; when users collapse into publishing profiles this returns a
    # node-scoped token instead. Deliberately imported here so this module
    # does not depend on kerf-auth at import time.
    from kerf_auth.routes import bootstrap_local  # noqa: PLC0415
    from fastapi import Response

    # bootstrap_local returns an AuthResponse model, not a dict. Annotating
    # this route `-> dict` made FastAPI validate the response against dict and
    # 500 on every correct password — the return type here has to stay wide
    # enough for whatever the session machinery hands back.
    return await bootstrap_local(Response())
