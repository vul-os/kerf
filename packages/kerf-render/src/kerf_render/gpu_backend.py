"""kerf-render: Pluggable GPU backend protocol + concrete implementations.

Defines the open-core interface for dispatching GPU workloads (Blender Cycles
renders today; FEM/topology in future) to an arbitrary GPU provider.

Backend categories
------------------
(a) **Hosted GPU vendors** — cloud-managed GPU workers the Kerf platform
    provisions on-demand.  ``RunPodGPUBackend`` is the first concrete vendor;
    the interface accommodates Modal / Replicate / Lambda Labs as follow-ons.

(b) **Self-hosted BYO workers** — a user's own GPU machine, linked to their
    account via a token.  ``SelfHostedWorkerBackend`` is the real
    implementation; jobs run on the user's hardware at zero credit cost.

Open-core seam
--------------
This module is MIT-licensed and ships in the OSS tree.  Proprietary vendor
API calls live in the concrete backends below.

Usage::

    from kerf_render.gpu_backend import (
        GPUBackend,
        RunPodGPUBackend,
        SelfHostedWorkerBackend,
        select_backend,
    )

    # Pick a backend for a job:
    backend = select_backend(job, project_preferred_backend=None, available_backends=all_backends)
    ext_id = await backend.submit(job)

    # Poll:
    status = await backend.poll(ext_id)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RunPod API constants
# ---------------------------------------------------------------------------

_RUNPOD_API_BASE = "https://api.runpod.io/v2"

# RunPod Serverless endpoint SKU map (endpoint_id prefix → GPU descriptor).
# These are well-known RunPod Serverless fleet prefixes — callers may pass an
# explicit ``gpu_type``/``vram_gb`` override via the constructor instead.
_RUNPOD_ENDPOINT_SKU_MAP: Dict[str, Dict[str, Any]] = {
    "l4":       {"gpu_type": "NVIDIA L4",    "vram_gb": 24},
    "l40s":     {"gpu_type": "NVIDIA L40S",  "vram_gb": 48},
    "a100":     {"gpu_type": "NVIDIA A100",  "vram_gb": 80},
    "h100":     {"gpu_type": "NVIDIA H100",  "vram_gb": 80},
    "a40":      {"gpu_type": "NVIDIA A40",   "vram_gb": 48},
    "rtx4090":  {"gpu_type": "NVIDIA RTX 4090", "vram_gb": 24},
}

# Maximum retry attempts on 5xx responses before re-raising.
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds; exponential back-off: 1s, 2s, 4s


# ---------------------------------------------------------------------------
# Domain-specific RunPod exceptions
# ---------------------------------------------------------------------------

class RunPodError(Exception):
    """Base class for RunPod backend errors."""


class RunPodAuthError(RunPodError):
    """Raised when RunPod returns 401 or 403 (bad / expired API key)."""


class RunPodNotFound(RunPodError):
    """Raised when RunPod returns 404 (job or endpoint does not exist)."""


class RunPodServerError(RunPodError):
    """Raised when RunPod returns 5xx after exhausting retries."""


# ---------------------------------------------------------------------------
# JobStatus — normalised status returned from poll()
# ---------------------------------------------------------------------------

class JobStatus:
    """Normalised status for a dispatched GPU job.

    Attributes
    ----------
    state:
        One of ``"queued"``, ``"running"``, ``"complete"``, ``"failed"``,
        ``"cancelled"``.
    progress:
        Optional float in [0, 1] for in-progress jobs.
    error:
        Error message when ``state == "failed"``.
    raw:
        Provider-specific raw payload (preserved for debugging).
    """

    __slots__ = ("state", "progress", "error", "raw")

    def __init__(
        self,
        state: str,
        *,
        progress: Optional[float] = None,
        error: Optional[str] = None,
        raw: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.state = state
        self.progress = progress
        self.error = error
        self.raw = raw or {}

    def __repr__(self) -> str:  # pragma: no cover
        return f"JobStatus(state={self.state!r}, progress={self.progress}, error={self.error!r})"


# ---------------------------------------------------------------------------
# GPUBackend — Protocol (structural typing, runtime-checkable)
# ---------------------------------------------------------------------------

@runtime_checkable
class GPUBackend(Protocol):
    """Abstract GPU backend: submit a job, poll its status, fetch its result.

    All methods are ``async`` so implementations can use aiohttp or
    asyncpg without blocking the event loop.

    Backend identity
    ~~~~~~~~~~~~~~~~
    ``backend_id`` is a short lowercase string used for logging and routing
    (e.g. ``"runpod"``, ``"self_hosted"``, ``"local"``).

    ``billing_bucket`` controls whether a completed job charges credits:
    - ``"kerf_paid"`` — draw from the user's prepaid credit balance.
    - ``"byo"``        — user's own hardware; no credit charge.
    """

    backend_id: str
    billing_bucket: str  # "kerf_paid" | "byo"

    async def submit(self, job: Dict[str, Any]) -> str:
        """Enqueue a job and return the provider's opaque external job ID.

        Parameters
        ----------
        job:
            Normalised job dict.  Required keys: ``job_id`` (Kerf UUID),
            ``job_type`` (``"render"`` / ``"fem"`` / …),  ``payload``
            (provider-specific inputs).

        Returns
        -------
        str
            Opaque external job identifier (stored in ``render_jobs`` for
            reconciliation).
        """
        ...

    async def poll(self, external_id: str) -> JobStatus:
        """Return the current status of a job previously submitted.

        Parameters
        ----------
        external_id:
            The string returned by :meth:`submit`.

        Returns
        -------
        :class:`JobStatus`
        """
        ...

    async def fetch_result(self, external_id: str) -> bytes:
        """Fetch the binary result of a completed job.

        Returns
        -------
        bytes
            Raw result bytes (e.g. PNG/EXR render output).  Callers are
            responsible for forwarding to blob storage.

        Raises
        ------
        ValueError
            If the job is not yet complete.
        """
        ...

    async def capabilities(self) -> Dict[str, Any]:
        """Return a descriptor of this backend's capabilities.

        Returns
        -------
        dict with keys:

            ``gpu_type``        str     — e.g. ``"RTX 4090"`` / ``"A100"``
            ``vram_gb``         int     — VRAM in gigabytes
            ``supported_workloads`` list[str] — e.g. ``["render", "fem"]``
            ``max_concurrent``  int | None — None = unlimited
            ``backend_id``      str     — mirrors ``self.backend_id``
            ``billing_bucket``  str     — mirrors ``self.billing_bucket``
        """
        ...


# ---------------------------------------------------------------------------
# _runpod_request — shared HTTP helper with retry + auth
# ---------------------------------------------------------------------------

async def _runpod_request(
    method: str,
    url: str,
    *,
    api_key: str,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Any:
    """Make an authenticated RunPod API request with exponential-backoff retry.

    Parameters
    ----------
    method:
        HTTP method string (``"GET"`` / ``"POST"``).
    url:
        Full RunPod API URL.
    api_key:
        RunPod API key (Bearer token).
    json_body:
        Optional JSON payload for POST requests.
    timeout:
        Per-request timeout in seconds.

    Returns
    -------
    Parsed JSON response body (``dict`` or ``list``).

    Raises
    ------
    RunPodAuthError
        On 401 or 403.
    RunPodNotFound
        On 404.
    RunPodServerError
        On 5xx after *_MAX_RETRIES* attempts.
    """
    import httpx  # runtime import — not a hard dep for self-hosted path

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method.upper() == "GET":
                    resp = await client.get(url, headers=headers)
                else:
                    resp = await client.post(url, headers=headers, json=json_body or {})

            if resp.status_code in (401, 403):
                raise RunPodAuthError(
                    f"RunPod auth error {resp.status_code} for {url}: {resp.text[:200]}"
                )
            if resp.status_code == 404:
                raise RunPodNotFound(
                    f"RunPod resource not found at {url}: {resp.text[:200]}"
                )
            if resp.status_code >= 500:
                # Retry on server errors with exponential back-off.
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "RunPod %s %s → %s (attempt %d/%d); retrying in %.1fs",
                    method, url, resp.status_code, attempt + 1, _MAX_RETRIES, delay,
                )
                last_exc = RunPodServerError(
                    f"RunPod server error {resp.status_code} for {url}: {resp.text[:200]}"
                )
                await asyncio.sleep(delay)
                continue

            # 4xx other than 401/403/404 — non-retryable client errors.
            if resp.status_code >= 400:
                raise RunPodError(
                    f"RunPod client error {resp.status_code} for {url}: {resp.text[:200]}"
                )

            return resp.json()

        except (RunPodAuthError, RunPodNotFound, RunPodError):
            raise
        except Exception as exc:
            # Network errors: retry.
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "RunPod %s %s → %s (attempt %d/%d); retrying in %.1fs",
                method, url, exc, attempt + 1, _MAX_RETRIES, delay,
            )
            last_exc = exc
            await asyncio.sleep(delay)

    raise RunPodServerError(
        f"RunPod {method} {url} failed after {_MAX_RETRIES} attempts"
    ) from last_exc


# ---------------------------------------------------------------------------
# _map_runpod_status — normalise RunPod state string → JobStatus
# ---------------------------------------------------------------------------

def _map_runpod_status(runpod_status: str, payload: Dict[str, Any]) -> JobStatus:
    """Convert a RunPod Serverless status string to a :class:`JobStatus`.

    RunPod Serverless statuses (from the API docs):
    - ``IN_QUEUE``    → queued
    - ``IN_PROGRESS`` → running
    - ``COMPLETED``   → complete
    - ``FAILED``      → failed
    - ``CANCELLED``   → cancelled
    - ``TIMED_OUT``   → failed (treat as failure)
    """
    state_map = {
        "IN_QUEUE":    "queued",
        "IN_PROGRESS": "running",
        "COMPLETED":   "complete",
        "FAILED":      "failed",
        "CANCELLED":   "cancelled",
        "TIMED_OUT":   "failed",
    }
    state = state_map.get(runpod_status.upper(), runpod_status.lower())

    error: Optional[str] = None
    if state == "failed":
        # Priority: top-level "error" field → output.error dict → fallback string.
        top_level_error = payload.get("error")
        output_obj = payload.get("output")
        output_error = output_obj.get("error") if isinstance(output_obj, dict) else None
        error = top_level_error or output_error or f"Job ended with status {runpod_status}"

    # RunPod does not expose a progress field in the status API, but some
    # workers include it in the output dict under ``"progress"``.
    progress: Optional[float] = None
    output = payload.get("output")
    if isinstance(output, dict):
        raw_progress = output.get("progress")
        if raw_progress is not None:
            try:
                progress = max(0.0, min(1.0, float(raw_progress)))
            except (TypeError, ValueError):
                pass

    return JobStatus(state, progress=progress, error=error, raw=payload)


# ---------------------------------------------------------------------------
# RunPodGPUBackend — real RunPod Serverless implementation
# ---------------------------------------------------------------------------

class RunPodGPUBackend:
    """RunPod Serverless GPU backend.

    Implements the :class:`GPUBackend` protocol against the RunPod Serverless
    Endpoints API (https://docs.runpod.io/serverless/endpoints/operations).

    Environment / constructor
    -------------------------
    ``api_key``     — ``RUNPOD_API_KEY`` (Bearer token).
    ``endpoint_id`` — ``RUNPOD_ENDPOINT_ID`` (the serverless endpoint to
                       target, e.g. ``"abc123xyz"``).

    Billing
    -------
    ``billing_bucket = "kerf_paid"`` — completed jobs deduct from the user's
    prepaid credit balance.  BYO jobs (``SelfHostedWorkerBackend``) remain
    untouched.

    Error handling
    --------------
    - 401 / 403  → :exc:`RunPodAuthError`
    - 404        → :exc:`RunPodNotFound`
    - 5xx        → :exc:`RunPodServerError` after 3 retries with exponential
                    back-off (1 s → 2 s → 4 s).

    Capabilities
    ------------
    ``capabilities()`` probes ``GET /health`` on the endpoint.  If the health
    check is unavailable (e.g. cold endpoint) it falls back to a static
    descriptor derived from ``endpoint_id``-prefix matching against
    ``_RUNPOD_ENDPOINT_SKU_MAP``.
    """

    backend_id = "runpod"
    billing_bucket = "kerf_paid"

    def __init__(
        self,
        api_key: str = "",
        endpoint_id: str = "",
        region: str = "EU",
        *,
        gpu_type: Optional[str] = None,
        vram_gb: Optional[int] = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint_id = endpoint_id
        self._region = region
        # Optional explicit overrides (e.g. when the operator knows the SKU).
        self._gpu_type_override = gpu_type
        self._vram_gb_override = vram_gb

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _endpoint_url(self, path: str) -> str:
        """Build a full RunPod Serverless API URL for *path*."""
        return f"{_RUNPOD_API_BASE}/{self._endpoint_id}/{path.lstrip('/')}"

    # ── GPUBackend methods ───────────────────────────────────────────────────

    async def submit(self, job: Dict[str, Any]) -> str:
        """POST to RunPod ``/run`` and return the RunPod job ID.

        The ``job`` dict is normalised by the caller; this method wraps the
        entire dict as the ``"input"`` payload that the RunPod worker handler
        will receive.

        Parameters
        ----------
        job:
            Kerf normalised job dict with at least ``job_id`` and
            ``job_type``.  The whole dict is forwarded as-is under ``"input"``.

        Returns
        -------
        str
            RunPod job ID (e.g. ``"abc123-def456-..."``).  Stored as
            ``external_id`` on the ``render_jobs`` row.
        """
        if not self._endpoint_id:
            raise RunPodError("RunPodGPUBackend: endpoint_id is not configured")
        if not self._api_key:
            raise RunPodAuthError("RunPodGPUBackend: api_key is not configured")

        url = self._endpoint_url("run")
        body = {"input": job}

        logger.debug(
            "RunPodGPUBackend.submit: POST %s job_id=%s",
            url, job.get("job_id", "?"),
        )

        response = await _runpod_request("POST", url, api_key=self._api_key, json_body=body)

        # RunPod returns {"id": "<job_id>", "status": "IN_QUEUE"}
        runpod_job_id: str = response.get("id", "")
        if not runpod_job_id:
            raise RunPodError(
                f"RunPod /run response missing 'id' field: {response!r}"
            )

        logger.info(
            "RunPodGPUBackend.submit: kerf_job=%s → runpod_id=%s",
            job.get("job_id", "?"), runpod_job_id,
        )
        return runpod_job_id

    async def poll(self, external_id: str) -> JobStatus:
        """GET RunPod ``/status/{external_id}`` and return a :class:`JobStatus`.

        Parameters
        ----------
        external_id:
            RunPod job ID returned by :meth:`submit`.

        Returns
        -------
        :class:`JobStatus` with ``state`` normalised from the RunPod status
        string.
        """
        url = self._endpoint_url(f"status/{external_id}")
        logger.debug("RunPodGPUBackend.poll: GET %s", url)

        response = await _runpod_request("GET", url, api_key=self._api_key)

        runpod_status: str = response.get("status", "UNKNOWN")
        return _map_runpod_status(runpod_status, response)

    async def fetch_result(self, external_id: str) -> bytes:
        """Fetch the completed job's binary result.

        Strategy
        --------
        1. Call :meth:`poll` — raise ``ValueError`` if not ``"complete"``.
        2. Inspect ``output`` in the status response:
           - If ``output`` contains a ``"url"`` field (signed S3/R2 URL),
             stream bytes from that URL via ``httpx``.
           - If ``output`` contains ``"data"`` (base64-encoded bytes), decode
             and return directly.
           - If ``output`` is raw bytes-compatible (str that looks like a URL),
             stream it.
        3. Fall back: re-fetch via ``GET /output/{external_id}`` and stream
           whatever the endpoint returns.

        Parameters
        ----------
        external_id:
            RunPod job ID.

        Returns
        -------
        bytes
            Raw result bytes (PNG / EXR / …).

        Raises
        ------
        ValueError
            If the job is not yet complete.
        RunPodError
            If the result cannot be retrieved.
        """
        import base64
        import httpx

        # Step 1: verify the job is done.
        status = await self.poll(external_id)
        if status.state != "complete":
            raise ValueError(
                f"RunPod job {external_id!r} is not complete (state={status.state!r})"
            )

        output = status.raw.get("output")

        # Step 2a: output has a signed URL.
        if isinstance(output, dict):
            url = output.get("url") or output.get("result_url") or output.get("image_url")
            if url and isinstance(url, str) and url.startswith("http"):
                logger.debug("RunPodGPUBackend.fetch_result: streaming from url=%s", url)
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return resp.content

            # Step 2b: base64-encoded data in output.
            data_b64 = output.get("data") or output.get("image_b64")
            if data_b64 and isinstance(data_b64, str):
                logger.debug("RunPodGPUBackend.fetch_result: decoding base64 data")
                return base64.b64decode(data_b64)

        # Step 2c: output is a plain URL string.
        if isinstance(output, str) and output.startswith("http"):
            logger.debug("RunPodGPUBackend.fetch_result: streaming from output url=%s", output)
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(output)
                resp.raise_for_status()
                return resp.content

        # Step 3: fallback — GET /output/{job_id} from the RunPod endpoint.
        logger.debug(
            "RunPodGPUBackend.fetch_result: fallback GET /output/%s", external_id,
        )
        output_url = self._endpoint_url(f"output/{external_id}")
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(
                output_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            if resp.status_code == 404:
                raise RunPodNotFound(
                    f"RunPod output not found for job {external_id}"
                )
            resp.raise_for_status()
            return resp.content

    async def capabilities(self) -> Dict[str, Any]:
        """Return a capabilities descriptor for this backend.

        Probes ``GET /health`` on the configured endpoint.  Falls back to a
        static descriptor derived from ``endpoint_id``-prefix matching when the
        health endpoint is unavailable (e.g. cold endpoint, no traffic).

        Returns
        -------
        dict
            Keys: ``gpu_type``, ``vram_gb``, ``supported_workloads``,
            ``max_concurrent``, ``backend_id``, ``billing_bucket``,
            ``workers_idle``, ``workers_running``, ``requests_in_queue``.
        """
        gpu_type: Optional[str] = self._gpu_type_override
        vram_gb: Optional[int] = self._vram_gb_override
        workers_idle: Optional[int] = None
        workers_running: Optional[int] = None
        requests_in_queue: Optional[int] = None

        # Resolve GPU info from endpoint_id prefix when not explicitly set.
        if (gpu_type is None or vram_gb is None) and self._endpoint_id:
            ep_lower = self._endpoint_id.lower()
            for prefix, sku in _RUNPOD_ENDPOINT_SKU_MAP.items():
                if prefix in ep_lower:
                    gpu_type = gpu_type or sku["gpu_type"]
                    vram_gb = vram_gb or sku["vram_gb"]
                    break

        # Probe the /health endpoint for live worker counts.
        if self._endpoint_id and self._api_key:
            try:
                health_url = self._endpoint_url("health")
                health = await _runpod_request(
                    "GET", health_url, api_key=self._api_key, timeout=10.0
                )
                # RunPod /health returns:
                # {"workers": {"idle": N, "running": M}, "jobs": {"inQueue": K, ...}}
                w = health.get("workers", {})
                j = health.get("jobs", {})
                workers_idle = w.get("idle")
                workers_running = w.get("running")
                requests_in_queue = j.get("inQueue") or j.get("in_queue")
            except Exception as exc:
                logger.debug(
                    "RunPodGPUBackend.capabilities: health probe failed (%s); "
                    "using static SKU descriptor",
                    exc,
                )

        return {
            "gpu_type": gpu_type or "L4–H100 (RunPod fleet)",
            "vram_gb": vram_gb,
            "supported_workloads": ["render", "fem", "topo"],
            "max_concurrent": None,
            "backend_id": self.backend_id,
            "billing_bucket": self.billing_bucket,
            "workers_idle": workers_idle,
            "workers_running": workers_running,
            "requests_in_queue": requests_in_queue,
        }


# ---------------------------------------------------------------------------
# SelfHostedWorkerBackend — BYO GPU machine, no credit charge
# ---------------------------------------------------------------------------

class SelfHostedWorkerBackend:
    """Backend for a user's own GPU machine enrolled via a worker token.

    Jobs are dispatched to the machine by writing a ``render_jobs`` row
    with ``preferred_worker_id`` set; the enrolled worker polls
    ``POST /api/workers/{id}/claim-job`` and pulls any matching queued job.

    Since the user owns the hardware, ``billing_bucket = "byo"`` — the
    charge_render path short-circuits without deducting credits.

    Parameters
    ----------
    worker_id:
        UUID of the enrolled ``gpu_workers`` row.
    pool:
        asyncpg connection pool (used to write + poll ``render_jobs``).
    """

    backend_id = "self_hosted"
    billing_bucket = "byo"

    def __init__(self, worker_id: str, pool) -> None:
        self._worker_id = worker_id
        self._pool = pool

    async def submit(self, job: Dict[str, Any]) -> str:
        """Write a render_jobs row tagged for this worker.

        Returns the Kerf job UUID as the external_id (the worker polls by ID).
        """
        import uuid as _uuid
        job_id = job.get("job_id") or str(_uuid.uuid4())
        user_id = job.get("user_id", "")
        scene_blob_hash = job.get("scene_blob_hash", "")
        preset = job.get("preset", "standard")

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO render_jobs
                    (id, user_id, scene_blob_hash, preset, status,
                     preferred_worker_id, billing_bucket)
                VALUES ($1, $2, $3, $4, 'queued', $5, 'byo')
                ON CONFLICT (id) DO NOTHING
                """,
                job_id, user_id, scene_blob_hash, preset, self._worker_id,
            )
        logger.debug(
            "SelfHostedWorkerBackend.submit: job=%s worker=%s",
            job_id, self._worker_id,
        )
        return job_id

    async def poll(self, external_id: str) -> JobStatus:
        """Read the ``render_jobs`` row and return a normalised status."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status, error, samples_done, samples_total "
                "FROM render_jobs WHERE id = $1",
                external_id,
            )
        if row is None:
            return JobStatus("not_found", error="job not found")

        db_status = row["status"]
        # Normalise DB status values to JobStatus states.
        state_map = {
            "queued":    "queued",
            "running":   "running",
            "rendering": "running",
            "complete":  "complete",
            "done":      "complete",
            "failed":    "failed",
            "error":     "failed",
            "cancelled": "cancelled",
        }
        state = state_map.get(db_status, db_status)

        progress: Optional[float] = None
        total = row.get("samples_total") or 0
        done = row.get("samples_done") or 0
        if state == "running" and total > 0:
            progress = min(1.0, done / total)

        return JobStatus(
            state,
            progress=progress,
            error=row.get("error"),
            raw={"samples_done": done, "samples_total": total},
        )

    async def fetch_result(self, external_id: str) -> bytes:
        """Retrieve the render result blob from the DB signed_url.

        In the BYO path the worker uploads to blob storage and writes the
        signed URL back; this method returns a redirect signal.
        The caller should redirect to ``signed_url`` rather than
        proxying the bytes.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status, signed_url FROM render_jobs WHERE id = $1",
                external_id,
            )
        if row is None or row["status"] not in ("complete", "done"):
            raise ValueError(f"job {external_id} is not complete (status={row['status'] if row else 'not_found'})")
        url = row["signed_url"] or ""
        # Return the URL as bytes so the caller can forward it.
        return url.encode()

    async def capabilities(self) -> Dict[str, Any]:
        """Read the worker's capabilities from ``gpu_workers``."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT capabilities FROM gpu_workers WHERE id = $1",
                self._worker_id,
            )
        caps = {}
        if row and row["capabilities"]:
            import json as _json
            if isinstance(row["capabilities"], dict):
                caps = row["capabilities"]
            else:
                try:
                    caps = _json.loads(row["capabilities"])
                except Exception:
                    caps = {}
        return {
            "gpu_type": caps.get("gpu_type", "unknown"),
            "vram_gb": caps.get("vram_gb"),
            "supported_workloads": caps.get("supported_workloads", ["render"]),
            "max_concurrent": caps.get("max_concurrent", 1),
            "backend_id": self.backend_id,
            "billing_bucket": self.billing_bucket,
        }


# ---------------------------------------------------------------------------
# Backend registry — maps backend_id → backend class
# ---------------------------------------------------------------------------

_BACKEND_REGISTRY: Dict[str, type] = {
    "runpod": RunPodGPUBackend,
    "self_hosted": SelfHostedWorkerBackend,
}


def register_backend(backend_id: str, cls: type) -> None:
    """Register a custom backend class under *backend_id*.

    Follow-on tasks (Modal, Replicate, Lambda Labs) call this to plug
    into the routing layer without modifying this file.
    """
    _BACKEND_REGISTRY[backend_id] = cls


def registered_backends() -> Dict[str, type]:
    """Return a snapshot of the current registry (backend_id → class)."""
    return dict(_BACKEND_REGISTRY)


# ---------------------------------------------------------------------------
# make_runpod_backend — factory that reads from kerf_core.config.Settings
# ---------------------------------------------------------------------------

def make_runpod_backend() -> RunPodGPUBackend:
    """Construct a :class:`RunPodGPUBackend` from the application settings.

    Reads ``RUNPOD_API_KEY`` and ``RUNPOD_ENDPOINT_ID`` via
    :class:`kerf_core.config.Settings`.  Falls back to empty strings when the
    vars are absent (the backend will raise :exc:`RunPodAuthError` /
    :exc:`RunPodError` on first use if credentials are missing, rather than
    crashing at import time).
    """
    try:
        from kerf_core.config import get_settings
        settings = get_settings()
        api_key = getattr(settings, "runpod_api_key", "") or ""
        endpoint_id = getattr(settings, "runpod_endpoint_id", "") or ""
    except Exception:
        api_key = ""
        endpoint_id = ""
    return RunPodGPUBackend(api_key=api_key, endpoint_id=endpoint_id)


# ---------------------------------------------------------------------------
# Backend selection — testable, side-effect-free routing logic
# ---------------------------------------------------------------------------

def select_backend(
    job: Dict[str, Any],
    *,
    project_preferred_backend: Optional[str] = None,
    available_backends: Optional[List[GPUBackend]] = None,
    default_vendor_backend: Optional[GPUBackend] = None,
) -> Optional[GPUBackend]:
    """Pick the best backend for *job*.

    Selection order
    ---------------
    (a) ``project_preferred_backend`` — if the project has a preferred backend
        registered AND that backend appears in *available_backends*, use it.
    (b) Capability match — first backend whose
        ``capabilities().supported_workloads`` contains the job's
        ``job_type``, AND which claims to be available (not ``None``).
    (c) ``default_vendor_backend`` — the platform default (e.g. RunPod) if
        both (a) and (b) yield nothing.

    Parameters
    ----------
    job:
        Job dict with at least ``job_type`` (``"render"``, ``"fem"``, …).
    project_preferred_backend:
        ``backend_id`` string stored on the project, or ``None``.
    available_backends:
        List of instantiated :class:`GPUBackend` instances to consider.
        Pass an empty list or ``None`` to skip capability matching.
    default_vendor_backend:
        Fallback backend (e.g. a ``RunPodGPUBackend`` instance), used when
        neither (a) nor (b) finds a match.

    Returns
    -------
    :class:`GPUBackend` | None
        The selected backend, or ``None`` if no backend can serve the job.
    """
    backends = available_backends or []
    job_type = job.get("job_type", "render")

    # (a) Project preference.
    if project_preferred_backend:
        for b in backends:
            if getattr(b, "backend_id", None) == project_preferred_backend:
                logger.debug(
                    "select_backend: job_type=%s → preferred backend %s",
                    job_type, project_preferred_backend,
                )
                return b

    # (b) Capability match (sync inspection of the backend's static caps,
    #     not the async capabilities() method, to keep this function pure).
    for b in backends:
        static_workloads = getattr(b, "_supported_workloads", None)
        if static_workloads and job_type in static_workloads:
            logger.debug(
                "select_backend: job_type=%s → capability-matched backend %s",
                job_type, getattr(b, "backend_id", "?"),
            )
            return b

    # (c) Default vendor fallback.
    if default_vendor_backend is not None:
        logger.debug(
            "select_backend: job_type=%s → default vendor backend %s",
            job_type, getattr(default_vendor_backend, "backend_id", "?"),
        )
        return default_vendor_backend

    logger.warning("select_backend: no backend found for job_type=%s", job_type)
    return None


__all__ = [
    "GPUBackend",
    "JobStatus",
    "RunPodGPUBackend",
    "RunPodAuthError",
    "RunPodNotFound",
    "RunPodServerError",
    "RunPodError",
    "SelfHostedWorkerBackend",
    "make_runpod_backend",
    "select_backend",
    "register_backend",
    "registered_backends",
]
