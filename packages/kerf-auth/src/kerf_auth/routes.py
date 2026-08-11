import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from pydantic import BaseModel

from kerf_core.db.errors import is_unique_violation
from kerf_core.config import get_settings
from kerf_core.db.connection import get_pool_required
from kerf_core.db.queries import users as users_queries
from kerf_core.db.queries import workspaces as workspaces_queries
from kerf_core.db.queries import refresh_tokens as rt_queries
from kerf_core.db.queries import api_tokens as api_tokens_queries
from kerf_core.dependencies import require_auth

router = APIRouter()
api_tokens_router = APIRouter()
settings = get_settings()


def hash_password(password: str) -> str:
    pepper = settings.password_pepper
    peppered = (password + pepper).encode("utf-8")
    return bcrypt.hashpw(peppered, bcrypt.gensalt()).decode("utf-8")


def check_password(stored_hash: str, password: str) -> bool:
    if not stored_hash:
        return False
    pepper = settings.password_pepper
    peppered = (password + pepper).encode("utf-8")
    try:
        return bcrypt.checkpw(peppered, stored_hash.encode("utf-8"))
    except ValueError:
        return False


def generate_access_token(user_id: str) -> tuple[str, datetime]:
    exp = datetime.utcnow() + timedelta(minutes=settings.jwt_access_ttl_minutes)
    payload = {"sub": user_id, "exp": exp, "iat": datetime.utcnow()}
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return token, exp


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Token lifetime for the operator-relayed password-reset link (see
# admin_generate_password_reset_link below).
RESET_TOKEN_TTL = timedelta(minutes=30)

# Constant-time guard: bcrypt hash of a throwaway value used to dummy-check
# when the email address is not registered.  This keeps the /login response
# time indistinguishable regardless of whether the account exists, preventing
# user-enumeration via timing.
_DUMMY_HASH: str = bcrypt.hashpw(b"kerf-dummy-guard", bcrypt.gensalt()).decode("utf-8")


def _app_url() -> str:
    return (settings.cors_origin or "https://app.kerf.sh").rstrip("/")


async def _create_email_token(conn, user_id: str, kind: str, ttl: timedelta) -> str:
    """Mint a single-use token; only the sha256 hash is stored."""
    raw = secrets.token_urlsafe(32)
    await conn.execute(
        """
        INSERT INTO email_tokens (user_id, kind, token_hash, expires_at)
        VALUES ($1, $2, $3, $4)
        """,
        user_id, kind, hash_token(raw),
        datetime.now(timezone.utc) + ttl,
    )
    return raw


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    avatar_url: str
    account_role: str
    is_system: bool
    email_verified: bool = False
    created_at: datetime


class WorkspaceResponse(BaseModel):
    id: str
    slug: str
    name: str
    avatar_url: Optional[str] = None
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserResponse
    default_workspace: Optional[WorkspaceResponse] = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class CreateTokenRequest(BaseModel):
    name: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


class TokenResponse(BaseModel):
    id: str
    name: str
    token: Optional[str] = None
    scopes: list[str]
    created_at: datetime


async def create_personal_workspace(conn: asyncpg.Connection, user_id: str, display_name: str) -> Optional[dict]:
    slug = f"personal-{user_id[:8]}-{secrets.token_hex(4)}"
    slug = slug.lower()
    try:
        workspace = await workspaces_queries.create_workspace(conn, slug, display_name, user_id)
        await workspaces_queries.add_workspace_member(conn, workspace["id"], user_id, "owner")
        return workspace
    except Exception:
        return None


async def get_default_workspace(conn: asyncpg.Connection, user_id: str) -> tuple[Optional[dict], bool]:
    row = await conn.fetchrow(
        """
        SELECT w.* FROM workspaces w
        JOIN workspace_members wm ON w.id = wm.workspace_id
        WHERE wm.user_id = $1 AND wm.role = 'owner'
        ORDER BY w.created_at ASC
        LIMIT 1
        """,
        user_id,
    )
    if row:
        return dict(row), True
    return None, False


async def issue_tokens(conn: asyncpg.Connection, user_id: str) -> tuple[str, str]:
    access_token, _ = generate_access_token(user_id)
    refresh_token = generate_refresh_token()
    refresh_hash = hash_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days)
    await rt_queries.create_refresh_token(conn, user_id, refresh_hash, expires_at)
    return access_token, refresh_token


def user_to_response(user: dict) -> UserResponse:
    return UserResponse(
        id=str(user["id"]),
        email=user["email"],
        name=user["name"],
        avatar_url=user["avatar_url"] or "",
        account_role=user["account_role"],
        is_system=user["is_system"],
        email_verified=bool(dict(user).get("email_verified", False)),
        created_at=user["created_at"],
    )


def workspace_to_response(ws: dict) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=str(ws["id"]),
        slug=ws["slug"],
        name=ws["name"],
        avatar_url=ws.get("avatar_url"),
        created_at=ws["created_at"],
    )


@router.post("/refresh", response_model=AuthResponse)
async def refresh(req: RefreshRequest):
    if not req.refresh_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid body")

    pool = await get_pool_required()
    async with pool.acquire() as conn:
        token_hash = hash_token(req.refresh_token)
        rt = await rt_queries.get_refresh_token(conn, token_hash)
        if not rt:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token")

        await rt_queries.revoke_refresh_token(conn, token_hash)
        new_access, new_refresh = await issue_tokens(conn, str(rt["user_id"]))

        user = await users_queries.get_user(conn, rt["user_id"])
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")

        default_ws, _ = await get_default_workspace(conn, str(user["id"]))

        return AuthResponse(
            access_token=new_access,
            refresh_token=new_refresh,
            user=user_to_response(user),
            default_workspace=workspace_to_response(default_ws) if default_ws else None,
        )


@router.post("/logout")
async def logout(req: RefreshRequest, response: Response):
    if req.refresh_token:
        pool = await get_pool_required()
        async with pool.acquire() as conn:
            token_hash = hash_token(req.refresh_token)
            await rt_queries.revoke_refresh_token(conn, token_hash)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def issue_node_session() -> AuthResponse:
    """Mint a session for this node's single owner.

    Replaces the `/auth/bootstrap-local` route, which did the same thing over
    HTTP with **no credential at all**: anything that could reach the port was
    signed in, which on a machine where a hostile page can point the browser at
    loopback (DNS rebinding is the usual route) is not a credential. The
    password set on first load is, so this is now reachable only through
    `POST /api/setup/signin`, behind that check.

    Not gated on `local_mode`. The old route was, because it was the *local*
    way in and accounts were the other way; there is one way in now, and it is
    the same on a laptop and on a box in a rack.
    """
    email = settings.system_user_email.strip().lower() if settings.system_user_email else "local@kerf.local"
    name = settings.system_user_name.strip() if settings.system_user_name else "Local"

    pool = await get_pool_required()
    async with pool.acquire() as conn:
        user = await users_queries.get_user_by_email(conn, email)
        if not user:
            try:
                user = await users_queries.create_user(conn, email, name, None, None)
                user = dict(user)
            except Exception as exc:
                # Two requests can bootstrap the singleton at once (a second
                # tab, or two e2e workers). Losing that race is fine — read
                # back the row the winner wrote.
                if not is_unique_violation(exc):
                    raise
                user = await users_queries.get_user_by_email(conn, email)

        if not user:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="failed to create or find user")

        access_token, refresh_token = await issue_tokens(conn, str(user["id"]))
        default_ws, _ = await get_default_workspace(conn, str(user["id"]))

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=user_to_response(user),
            default_workspace=workspace_to_response(default_ws) if default_ws else None,
        )


def generate_api_token() -> str:
    return secrets.token_urlsafe(32)


@api_tokens_router.post("/api-tokens", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def create_api_token(request: Request, req: CreateTokenRequest, payload: dict = Depends(require_auth)):
    if not req.name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required")

    user_id = payload.get("sub")
    workspace_id = getattr(request.state, "workspace_id", None)

    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="workspace context required")

    pool = await get_pool_required()
    async with pool.acquire() as conn:
        token = generate_api_token()
        token_hash = hash_token(token)
        scopes = ["workspace:member-role"]
        result = await api_tokens_queries.create_api_token(conn, workspace_id, user_id, token_hash, req.name, scopes)
        return TokenResponse(
            id=str(result["id"]),
            name=result["name"],
            token=token,
            scopes=result["scopes"] or [],
            created_at=result["created_at"],
        )


@api_tokens_router.get("/api-tokens", response_model=list[TokenResponse])
async def list_api_tokens(request: Request, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    workspace_id = getattr(request.state, "workspace_id", None)

    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="workspace context required")

    pool = await get_pool_required()
    async with pool.acquire() as conn:
        tokens = await api_tokens_queries.list_api_tokens(conn, workspace_id, user_id)
        return [
            TokenResponse(
                id=str(t["id"]),
                name=t["name"],
                scopes=t["scopes"] or [],
                created_at=t["created_at"],
            )
            for t in tokens
        ]


@api_tokens_router.delete("/api-tokens/{token_id}")
async def revoke_api_token(request: Request, token_id: str, payload: dict = Depends(require_auth)):
    workspace_id = getattr(request.state, "workspace_id", None)

    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="workspace context required")

    pool = await get_pool_required()
    async with pool.acquire() as conn:
        revoked = await api_tokens_queries.revoke_api_token(conn, uuid.UUID(token_id), uuid.UUID(workspace_id))
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="token not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
