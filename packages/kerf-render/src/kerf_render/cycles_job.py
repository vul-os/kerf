"""kerf-render: in-memory render-job lifecycle state machine.

Provides :class:`JobLifecycle` and a module-level job registry so callers can
submit, poll, transition, and cancel render jobs without a database dependency.
This is the lightweight in-process counterpart to :mod:`kerf_render.job_lifecycle`
(which operates on a Postgres ``render_jobs`` table).

State machine
-------------
::

    queued ──► running ──► completed
                │
                ├──► failed
                └──► cancelled

Any job in *queued* or *running* state can be cancelled.  Terminal states
(``completed``, ``failed``, ``cancelled``) are immutable — subsequent
transition attempts are silently ignored and return ``False``.

Usage
-----
::

    from kerf_render.cycles_job import submit_job, get_job, transition

    job_id = submit_job(scene_glb=b"...", materials_json="{}", samples=256,
                        resolution=(1920, 1080), output_format="png")
    get_job(job_id)  # {"id": ..., "status": "queued", ...}

    transition(job_id, "running")
    transition(job_id, "completed", result_url="/tmp/out.png")
"""

from __future__ import annotations

import threading
import uuid
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    """Valid states for a render job."""

    QUEUED    = "queued"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


_TERMINAL_STATES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

# Valid forward transitions: current_state -> set of allowed next states
_TRANSITIONS: Dict[JobStatus, set] = {
    JobStatus.QUEUED:    {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING:   {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED:    set(),
    JobStatus.CANCELLED: set(),
}


# ---------------------------------------------------------------------------
# JobLifecycle — single-job state machine
# ---------------------------------------------------------------------------


class JobLifecycle:
    """State-machine wrapper for a single render job.

    Parameters
    ----------
    job_id:
        Unique identifier string (UUID is recommended; arbitrary str accepted).
    scene_glb:
        Raw GLB bytes of the scene to render.
    materials_json:
        JSON string mapping material-slot names to PBR parameter dicts.
    samples:
        Number of path-tracing samples.
    resolution:
        ``(width, height)`` tuple.
    output_format:
        ``"png"`` or ``"exr"``.
    """

    def __init__(
        self,
        *,
        job_id: str,
        scene_glb: bytes,
        materials_json: str,
        samples: int,
        resolution: tuple,
        output_format: str = "png",
    ) -> None:
        self.job_id        = job_id
        self.scene_glb     = scene_glb
        self.materials_json = materials_json
        self.samples       = int(samples)
        self.resolution    = tuple(resolution)
        self.output_format = output_format
        self._status       = JobStatus.QUEUED
        self._result_url: Optional[str] = None
        self._error: Optional[str] = None
        self._lock         = threading.Lock()

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def status(self) -> JobStatus:
        return self._status

    @property
    def result_url(self) -> Optional[str]:
        return self._result_url

    @property
    def error(self) -> Optional[str]:
        return self._error

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Transition ``queued`` → ``running``.

        Returns
        -------
        bool
            ``True`` if the transition succeeded; ``False`` when the job
            is not in ``queued`` state.
        """
        return self._transition(JobStatus.RUNNING)

    def complete(self, result_url: str) -> bool:
        """Transition ``running`` → ``completed`` and store the result URL.

        Returns
        -------
        bool
            ``True`` on success.
        """
        with self._lock:
            if JobStatus.COMPLETED not in _TRANSITIONS.get(self._status, set()):
                return False
            self._result_url = result_url
            self._status = JobStatus.COMPLETED
            return True

    def fail(self, error: str) -> bool:
        """Transition ``running`` → ``failed`` and record the error.

        Returns
        -------
        bool
            ``True`` on success.
        """
        with self._lock:
            if JobStatus.FAILED not in _TRANSITIONS.get(self._status, set()):
                return False
            self._error = error
            self._status = JobStatus.FAILED
            return True

    def cancel(self) -> bool:
        """Cancel a queued or running job.

        Returns
        -------
        bool
            ``True`` if the job was cancelled; ``False`` when already in a
            terminal state.
        """
        return self._transition(JobStatus.CANCELLED)

    def _transition(self, target: JobStatus) -> bool:
        with self._lock:
            if target not in _TRANSITIONS.get(self._status, set()):
                return False
            self._status = target
            return True

    # ------------------------------------------------------------------
    # Dict serialisation
    # ------------------------------------------------------------------

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of the job."""
        return {
            "id":            self.job_id,
            "status":        self._status.value,
            "samples":       self.samples,
            "resolution":    list(self.resolution),
            "output_format": self.output_format,
            "result_url":    self._result_url,
            "error":         self._error,
        }


# ---------------------------------------------------------------------------
# Module-level job registry
# ---------------------------------------------------------------------------

_registry: Dict[str, JobLifecycle] = {}
_registry_lock = threading.Lock()


def submit_job(
    *,
    scene_glb: bytes,
    materials_json: str,
    samples: int,
    resolution: tuple,
    output_format: str = "png",
    job_id: Optional[str] = None,
) -> str:
    """Create a new job in ``queued`` state and add it to the registry.

    Parameters
    ----------
    scene_glb:
        Raw GLB bytes produced by :mod:`kerf_render.cycles_translator`.
    materials_json:
        JSON string with the materials map (slot → PBR params).
    samples:
        Path-tracing sample count.
    resolution:
        ``(width, height)`` tuple.
    output_format:
        ``"png"`` or ``"exr"``.
    job_id:
        Optional explicit ID.  A UUID4 string is generated when omitted.

    Returns
    -------
    str
        The new job's ID.
    """
    jid = job_id or str(uuid.uuid4())
    job = JobLifecycle(
        job_id=jid,
        scene_glb=scene_glb,
        materials_json=materials_json,
        samples=samples,
        resolution=resolution,
        output_format=output_format,
    )
    with _registry_lock:
        _registry[jid] = job
    return jid


def get_job(job_id: str) -> Optional[JobLifecycle]:
    """Return the :class:`JobLifecycle` for *job_id*, or ``None``."""
    with _registry_lock:
        return _registry.get(job_id)


def transition(
    job_id: str,
    target_status: str,
    *,
    result_url: Optional[str] = None,
    error: Optional[str] = None,
) -> bool:
    """Drive a named transition on the job identified by *job_id*.

    Parameters
    ----------
    job_id:
        Registry key.
    target_status:
        One of ``"running"``, ``"completed"``, ``"failed"``, ``"cancelled"``.
    result_url:
        Required when *target_status* is ``"completed"``.
    error:
        Required when *target_status* is ``"failed"``.

    Returns
    -------
    bool
        ``True`` if the transition succeeded; ``False`` if the job was not
        found or the transition was invalid.
    """
    with _registry_lock:
        job = _registry.get(job_id)
    if job is None:
        return False

    ts = target_status.lower()
    if ts == "running":
        return job.start()
    if ts == "completed":
        url = result_url or ""
        return job.complete(url)
    if ts == "failed":
        return job.fail(error or "unknown error")
    if ts == "cancelled":
        return job.cancel()
    return False


def clear_registry() -> None:
    """Remove all jobs from the in-memory registry.  Useful in tests."""
    with _registry_lock:
        _registry.clear()


__all__ = [
    "JobStatus",
    "JobLifecycle",
    "submit_job",
    "get_job",
    "transition",
    "clear_registry",
]
