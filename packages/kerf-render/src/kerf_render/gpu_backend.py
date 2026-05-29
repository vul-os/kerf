"""kerf-render: Pluggable GPU backend protocol + concrete stubs.

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
API calls (RunPod HTTP, Koyeb runner, etc.) live in the follow-on task
``RUNPOD-BACKEND`` — add them by creating a concrete subclass without
touching this file.

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

import logging
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

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
# RunPodGPUBackend — vendor stub (real API wired in RUNPOD-BACKEND follow-on)
# ---------------------------------------------------------------------------

class RunPodGPUBackend:
    """RunPod Serverless GPU backend stub.

    TODO(RUNPOD-BACKEND): replace ``raise NotImplementedError`` bodies with
    real RunPod Serverless API calls:
    - POST   https://api.runpod.io/v2/{endpoint_id}/run
    - GET    https://api.runpod.io/v2/{endpoint_id}/status/{job_id}
    - GET    https://api.runpod.io/v2/{endpoint_id}/stream/{job_id}

    Registers as a vendor option so routing logic can include it in
    backend selection before the real implementation ships.
    """

    backend_id = "runpod"
    billing_bucket = "kerf_paid"

    def __init__(
        self,
        api_key: str = "",
        endpoint_id: str = "",
        region: str = "EU",
    ) -> None:
        self._api_key = api_key
        self._endpoint_id = endpoint_id
        self._region = region

    async def submit(self, job: Dict[str, Any]) -> str:
        # TODO(RUNPOD-BACKEND): POST to RunPod Serverless /run endpoint.
        raise NotImplementedError(
            "RunPodGPUBackend.submit is not yet implemented. "
            "See follow-on task RUNPOD-BACKEND."
        )

    async def poll(self, external_id: str) -> JobStatus:
        # TODO(RUNPOD-BACKEND): GET RunPod /status/{job_id}.
        raise NotImplementedError(
            "RunPodGPUBackend.poll is not yet implemented. "
            "See follow-on task RUNPOD-BACKEND."
        )

    async def fetch_result(self, external_id: str) -> bytes:
        # TODO(RUNPOD-BACKEND): download result from RunPod /output.
        raise NotImplementedError(
            "RunPodGPUBackend.fetch_result is not yet implemented. "
            "See follow-on task RUNPOD-BACKEND."
        )

    async def capabilities(self) -> Dict[str, Any]:
        return {
            "gpu_type": "L4–H100 (RunPod fleet)",
            "vram_gb": None,  # varies by SKU; resolved at dispatch time
            "supported_workloads": ["render", "fem", "topo"],
            "max_concurrent": None,
            "backend_id": self.backend_id,
            "billing_bucket": self.billing_bucket,
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
    "SelfHostedWorkerBackend",
    "select_backend",
    "register_backend",
    "registered_backends",
]
