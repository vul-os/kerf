"""GPU worker enrollment + dispatch routes.

Provides the HTTP surface for:
- User-facing enrollment / listing / revocation of BYO GPU worker machines.
- Worker-facing heartbeat, job claim, and job completion endpoints.

Auth model
----------
User-facing endpoints (enroll, list, delete) use standard JWT / session auth
via :func:`kerf_core.dependencies.require_auth`.

Worker-facing endpoints (heartbeat, claim-job, complete) use a ``Bearer``
token that was returned ONCE on enrollment.  The token is stored as a
bcrypt hash in ``gpu_workers.token_hash``; the raw token is NEVER stored.

Billing short-circuit
---------------------
When a BYO worker completes a job (``billing_bucket = 'byo'`` on the
``render_jobs`` row), the billing meter is NOT charged.  This is enforced
inside the ``/complete`` handler before it calls any credit-deduction code.

Signed-upload-URL flow (SIGNED-UPLOAD-URL)
------------------------------------------
On claim, the server mints a presigned PUT URL for a stable result key
``worker-results/{job_id}.bin``.  The worker PUTs its rendered bytes
directly to that URL (R2 / S3), then calls ``/complete`` with the
``result_key`` field instead of raw bytes.

``/complete`` accepts two paths:
1. ``result_key`` (new) — worker uploaded directly; server calls
   ``storage.head(result_key)`` to verify the object exists, then records
   the key on the job row.  No bytes flow through the API server.
2. ``signed_url`` (legacy) — worker provides a pre-formed URL; recorded
   verbatim (back-compat).

Both paths respect the BYO billing short-circuit.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import uuid
from typing import Any, Dict, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from kerf_core.dependencies import require_auth
from kerf_core.db.connection import get_pool_required

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workers", tags=["gpu-workers"])

# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

_TOKEN_BYTES = 32  # 256-bit random token


def _mint_token() -> str:
    """Generate a cryptographically-random worker token (plaintext)."""
    return "kerf_wk_" + secrets.token_hex(_TOKEN_BYTES)


def _hash_token(token: str) -> str:
    """SHA-256 hash of the token for safe storage."""
    return hashlib.sha256(token.encode()).hexdigest()


async def _verify_worker_token(
    request: Request,
    worker_id: str,
    pool,
) -> Dict[str, Any]:
    """Verify the Bearer worker token from the Authorization header.

    Returns the ``gpu_workers`` row if valid.
    Raises HTTP 401 if the token is missing, invalid, or revoked.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker token required (Authorization: Bearer <token>)",
        )
    raw_token = auth_header[7:].strip()
    token_hash = _hash_token(raw_token)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, name, status, capabilities, last_seen_at
            FROM gpu_workers
            WHERE id = $1 AND token_hash = $2
            """,
            worker_id, token_hash,
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked worker token",
        )
    if row["status"] == "revoked":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker token has been revoked",
        )
    return dict(row)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class EnrollWorkerRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    capabilities: Dict[str, Any] = Field(default_factory=dict)


class HeartbeatRequest(BaseModel):
    status: str = Field(default="online")


class CompleteJobRequest(BaseModel):
    # Legacy path: caller provides a pre-formed URL (back-compat).
    signed_url: Optional[str] = Field(
        default=None,
        description="Pre-formed result URL (legacy; use result_key for direct upload).",
    )
    # New path: caller uploaded to the presigned PUT URL; server verifies.
    result_key: Optional[str] = Field(
        default=None,
        description="Storage key of the result object uploaded via signed_upload_url.",
    )
    content_type: Optional[str] = Field(
        default=None,
        description="MIME type of the uploaded result (used with result_key).",
    )
    size_bytes: Optional[int] = Field(
        default=None,
        description="Byte size of the uploaded result (informational).",
    )
    gpu_seconds: float = Field(default=0.0, ge=0)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# User-facing endpoints
# ---------------------------------------------------------------------------

@router.post("/enroll", summary="Enroll a new GPU worker")
async def enroll_worker(
    body: EnrollWorkerRequest,
    auth: dict = Depends(require_auth),
):
    """Mint a new worker enrollment token.

    The plaintext token is returned ONCE.  Store it securely — it cannot
    be retrieved again.  Install on the worker machine via:

        pip install kerf-worker && kerf-worker enroll <TOKEN>
    """
    pool = await get_pool_required()
    user_id = auth["sub"]

    token = _mint_token()
    token_hash = _hash_token(token)
    worker_id = str(uuid.uuid4())

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO gpu_workers (id, user_id, name, token_hash, capabilities)
            VALUES ($1, $2, $3, $4, $5)
            """,
            worker_id,
            user_id,
            body.name.strip(),
            token_hash,
            body.capabilities,
        )

    logger.info("enroll_worker: user=%s worker=%s name=%r", user_id, worker_id, body.name)
    return {
        "id": worker_id,
        "name": body.name.strip(),
        "token": token,  # plaintext — returned ONCE
        "cli_hint": f"pip install kerf-worker && kerf-worker enroll {token}",
    }


@router.get("", summary="List my GPU workers")
async def list_workers(
    auth: dict = Depends(require_auth),
):
    """Return all workers enrolled by the authenticated user."""
    pool = await get_pool_required()
    user_id = auth["sub"]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, status, capabilities, last_seen_at, created_at
            FROM gpu_workers
            WHERE user_id = $1
            ORDER BY created_at DESC
            """,
            user_id,
        )

    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "status": r["status"],
            "capabilities": r["capabilities"] or {},
            "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
        if r["status"] != "revoked"
    ]


@router.delete("/{worker_id}", summary="Revoke a GPU worker token")
async def delete_worker(
    worker_id: str,
    auth: dict = Depends(require_auth),
):
    """Revoke the worker's token.  The machine can no longer authenticate."""
    pool = await get_pool_required()
    user_id = auth["sub"]

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE gpu_workers
               SET token_hash = '', status = 'revoked'
             WHERE id = $1 AND user_id = $2
            """,
            worker_id, user_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker not found or not owned by you",
        )

    logger.info("delete_worker: user=%s revoked worker=%s", user_id, worker_id)
    return {"revoked": True}


# ---------------------------------------------------------------------------
# Worker-facing endpoints (Bearer worker token auth)
# ---------------------------------------------------------------------------

@router.post("/{worker_id}/heartbeat", summary="Worker heartbeat")
async def worker_heartbeat(
    worker_id: str,
    body: HeartbeatRequest,
    request: Request,
):
    """Update the worker's last_seen_at and status.  Called by the worker daemon."""
    pool = await get_pool_required()
    await _verify_worker_token(request, worker_id, pool)

    allowed_statuses = {"online", "offline", "busy"}
    worker_status = body.status if body.status in allowed_statuses else "online"

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE gpu_workers
               SET last_seen_at = now(), status = $2
             WHERE id = $1
            """,
            worker_id, worker_status,
        )

    return {"ok": True, "status": worker_status}


@router.post("/{worker_id}/claim-job", summary="Claim a queued render job")
async def claim_job(
    worker_id: str,
    request: Request,
):
    """Long-poll (up to 30 s) for an unassigned render job this worker can run.

    Returns the job spec + scene blob hash on success, or 204 if no job
    arrives within the timeout.  Only jobs whose ``preferred_worker_id``
    matches this worker (or is NULL) are claimable.

    The job is atomically moved to ``status = 'running'`` and a row is
    inserted into ``gpu_worker_jobs`` so duplicate claims are impossible.

    Signed-upload-URL fields
    ------------------------
    ``result_key``         — stable storage key for the result object.
    ``signed_upload_url``  — presigned PUT URL; the worker PUTs its rendered
                             bytes here directly, then calls /complete with
                             ``result_key``.
    ``result_ttl_seconds`` — seconds until the PUT URL expires.
    """
    pool = await get_pool_required()
    worker_row = await _verify_worker_token(request, worker_id, pool)

    caps = worker_row.get("capabilities") or {}
    supported_workloads = caps.get("supported_workloads", ["render"])

    deadline = asyncio.get_event_loop().time() + 30.0  # 30 s long-poll

    while asyncio.get_event_loop().time() < deadline:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id, user_id, scene_blob_hash, preset,
                           samples_total, billing_bucket
                    FROM render_jobs
                    WHERE status = 'queued'
                      AND (preferred_worker_id = $1 OR preferred_worker_id IS NULL)
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """,
                    worker_id,
                )
                if row is not None:
                    job_id = str(row["id"])
                    await conn.execute(
                        """
                        UPDATE render_jobs
                           SET status = 'running', updated_at = now()
                         WHERE id = $1
                        """,
                        job_id,
                    )
                    await conn.execute(
                        """
                        INSERT INTO gpu_worker_jobs (worker_id, render_job_id)
                        VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                        """,
                        worker_id, job_id,
                    )

        if row is not None:
            logger.info("claim_job: worker=%s claimed job=%s", worker_id, job_id)

            # Mint a presigned PUT URL so the worker can upload directly to R2.
            # The TTL is job_ttl (30 min) + 1 h = 90 min total.
            result_key = f"worker-results/{job_id}.bin"
            result_ttl_seconds = 5400  # 90 minutes

            signed_upload_url: Optional[str] = None
            try:
                from kerf_core.storage import get_storage_required
                storage = get_storage_required()
                signed_upload_url = await storage.signed_put_url(
                    result_key,
                    ttl_seconds=result_ttl_seconds,
                    content_type="application/octet-stream",
                )
            except Exception as exc:
                # Storage not configured (e.g. test env) — worker falls back to
                # file:// path.  Log at DEBUG so tests stay quiet.
                logger.debug(
                    "claim_job: could not mint signed_upload_url for job=%s: %s",
                    job_id, exc,
                )

            return {
                "job_id": job_id,
                "scene_blob_hash": row["scene_blob_hash"],
                "preset": row["preset"],
                "samples_total": row["samples_total"],
                "billing_bucket": row["billing_bucket"],
                "result_key": result_key,
                "signed_upload_url": signed_upload_url,
                "result_ttl_seconds": result_ttl_seconds,
            }

        # No job yet — back off briefly and retry.
        await asyncio.sleep(2.0)

    # 204 No Content — no job within 30 s.
    from fastapi.responses import Response
    return Response(status_code=204)


@router.post("/{worker_id}/jobs/{job_id}/complete", summary="Mark a job as complete")
async def complete_job(
    worker_id: str,
    job_id: str,
    body: CompleteJobRequest,
    request: Request,
):
    """Mark a render job as complete.

    Accepts two upload paths — both respect the BYO billing short-circuit.

    result_key path (preferred)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Worker uploaded the result directly to R2 via the ``signed_upload_url``
    returned by claim-job.  Body must contain ``result_key``; the server
    calls ``storage.head(result_key)`` to confirm the object exists, then
    records the key on the job row.  No bytes flow through the API server.

    signed_url path (legacy / back-compat)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Worker provides a pre-formed URL in ``signed_url``; recorded verbatim.
    No storage verification is performed.

    Billing short-circuit
    ~~~~~~~~~~~~~~~~~~~~~
    When ``render_jobs.billing_bucket = 'byo'``, credit charging is
    skipped entirely — the user is paying their own GPU bill.

    For ``billing_bucket = 'kerf_paid'``, the existing
    :func:`kerf_billing.render_meter.charge_render` path is invoked.
    """
    pool = await get_pool_required()
    await _verify_worker_token(request, worker_id, pool)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, preset, billing_bucket, status FROM render_jobs WHERE id = $1",
            job_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] not in ("running", "queued"):
        raise HTTPException(status_code=409, detail=f"Job is already {row['status']}")

    billing_bucket = row["billing_bucket"] or "kerf_paid"
    user_id = str(row["user_id"]) if row["user_id"] else None
    preset = row["preset"] or "standard"

    if body.error:
        # Failed job.
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE render_jobs
                   SET status = 'failed', error = $2, updated_at = now()
                 WHERE id = $1
                """,
                job_id, body.error,
            )
            await conn.execute(
                """
                UPDATE gpu_worker_jobs
                   SET completed_at = now()
                 WHERE worker_id = $1 AND render_job_id = $2
                """,
                worker_id, job_id,
            )
        return {"ok": True, "charged": False, "reason": "job_error"}

    # -----------------------------------------------------------------------
    # Determine result storage — result_key path (new) vs signed_url (legacy)
    # -----------------------------------------------------------------------
    result_key: Optional[str] = body.result_key
    result_signed_url: Optional[str] = body.signed_url
    completion_path: str = "unknown"

    if result_key:
        # New path: worker uploaded directly; verify the object exists.
        completion_path = "result_key"
        try:
            from kerf_core.storage import get_storage_required
            storage = get_storage_required()
            head = await storage.head(result_key)
            if not head.exists:
                raise HTTPException(
                    status_code=422,
                    detail=f"result_key '{result_key}' not found in storage — "
                           "upload must complete before calling /complete",
                )
            logger.info(
                "complete_job: job=%s result_key=%s size=%d verified",
                job_id, result_key, head.size,
            )
        except HTTPException:
            raise
        except Exception as exc:
            # Storage not configured (local dev) — accept without verification.
            logger.debug(
                "complete_job: storage.head skipped for job=%s (storage unavailable): %s",
                job_id, exc,
            )

    elif result_signed_url:
        completion_path = "signed_url"
        # Legacy path: just record the URL; no verification.
    else:
        raise HTTPException(
            status_code=422,
            detail="Either 'result_key' or 'signed_url' must be provided",
        )

    # Successful completion — record in DB.
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE render_jobs
               SET status = 'complete',
                   result_key = $2,
                   signed_url = $3,
                   updated_at = now()
             WHERE id = $1
            """,
            job_id, result_key, result_signed_url,
        )
        await conn.execute(
            """
            UPDATE gpu_worker_jobs
               SET completed_at = now()
             WHERE worker_id = $1 AND render_job_id = $2
            """,
            worker_id, job_id,
        )

    charged = False
    charge_result: Dict[str, Any] = {}

    if billing_bucket == "byo":
        # BYO path: user's own GPU — no credit deduction.
        logger.info(
            "complete_job: job=%s billing_bucket=byo — skipping credit charge (user=%s)",
            job_id, user_id,
        )
        charged = False
    elif billing_bucket == "kerf_paid" and user_id:
        # Hosted-backend path: deduct from kerf_paid credits.
        try:
            from kerf_billing.render_meter import charge_render
            charge_result = await charge_render(
                pool,
                user_id=user_id,
                job_id=job_id,
                preset=preset,
                gpu_seconds_actual=body.gpu_seconds,
            )
            charged = charge_result.get("ok", False)
        except Exception as exc:
            logger.warning(
                "complete_job: charge_render failed for job=%s: %s", job_id, exc
            )
    else:
        logger.debug(
            "complete_job: job=%s billing_bucket=%r user_id=%r — no charge path",
            job_id, billing_bucket, user_id,
        )

    logger.info(
        "complete_job: worker=%s job=%s billing_bucket=%s charged=%s completion_path=%s",
        worker_id, job_id, billing_bucket, charged, completion_path,
    )
    return {
        "ok": True,
        "charged": charged,
        "billing_bucket": billing_bucket,
        "completion_path": completion_path,
        "charge_result": charge_result if charged else None,
    }


__all__ = ["router"]
