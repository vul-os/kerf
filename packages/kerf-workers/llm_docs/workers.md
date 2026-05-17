# kerf-workers — background worker harness

`kerf-workers` provides the generic worker harness: `BaseWorker`, `JobMixin`, and the `runner` glue. Concrete workers for specific domains (FEM, CAM, SPICE, STEP tessellation) live in their respective plugin packages and self-register via `ctx.workers.register(...)`.

---

## Plugin registration

```python
async def register(app, ctx) -> PluginManifest:
    ctx.workers.registry = WorkerRegistry
    return PluginManifest(name="workers", provides=["workers.harness"], depends=[])
```

The plugin attaches `WorkerRegistry` to the shared context so other plugins can register worker classes.

---

## BaseWorker (`kerf_workers.base.BaseWorker`)

Abstract base class for all polling workers.

```python
class BaseWorker(ABC):
    def __init__(self, name, pool, poll_interval=5.0, error_delay=2.0): ...

    async def _loop(self):
        while not self._shutdown:
            ran = await self.run_one()
            if not ran:
                await asyncio.sleep(self.poll_interval)

    @abstractmethod
    async def run_one(self) -> bool:
        """Process one queued job. Return True if a job was found and processed."""
```

The loop calls `run_one()` repeatedly. When `run_one()` returns `False` (no queued work), it sleeps `poll_interval` seconds before trying again. Errors are caught, logged, and the loop restarts after `error_delay` seconds.

### Job claiming pattern

```python
async def claim_job(self, tx, table, file_ref_table, status_col="status"):
    # SELECT … FROM {table} WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
    # UPDATE {table} SET status='running', started_at=now()
```

Uses `FOR UPDATE SKIP LOCKED` to safely dequeue jobs across multiple worker processes.

### Completion helpers

```python
await self.mark_done(table, job_id, result_json)
await self.mark_error(table, job_id, error_message)
```

---

## JobMixin (`kerf_workers.job_mixin.JobMixin`)

A composable mixin with the same claim/complete pattern, returning a typed `ClaimedJob` dataclass. Preferred for new workers.

```python
class ClaimedJob:
    id: str
    file_id: str
    project_id: str
    storage_key: str
    input_spec: dict

class MyWorker(BaseWorker, JobMixin):
    async def run_one(self) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction() as tx:
                job = await self.claim_next_job(tx, "cam_jobs", "files")
                if job is None:
                    return False
                try:
                    result = await self._process(job)
                    await self.update_job_status(tx, "cam_jobs", job.id, "done", result)
                except Exception as exc:
                    await self.update_job_status(tx, "cam_jobs", job.id, "error", error=str(exc))
        return True
```

---

## Long-running job pattern

All compute-heavy operations (STEP tessellation, FEM, CAM, SPICE simulation, topology optimisation) follow the same DB-backed job queue:

1. **Client** calls a tool or REST endpoint that inserts a row into `{domain}_jobs` with `status='queued'`
2. **Worker** claims the row with `FOR UPDATE SKIP LOCKED`, sets `status='running'`
3. **Worker** calls pyworker (subprocess or HTTP RPC) for the heavy compute
4. **Worker** writes result JSON back to the DB (`status='done', result_json=…`) or (`status='error', error=…`)
5. **Client** polls `/api/projects/{id}/jobs/{jid}` or the tool `cam_job_status` for completion

Job status values: `queued → running → done | error`

The error message is capped at 800 characters in the DB to avoid large text columns.

---

## SPICE worker (`kerf_workers.spice_worker`)

A concrete worker for SPICE simulation jobs. Processes rows from `sim_jobs`, calls the pyworker SPICE endpoint, stores netlists + waveform results as derived artifacts.

---

## Worker registration from other plugins

Plugins register workers as async factories:

```python
# In kerf_cam/plugin.py
cam_worker = CAMWorker(pool=ctx.pool, ...)

async def _cam_factory():
    return cam_worker

ctx.workers.register("cam", _cam_factory)
```

`WorkerRegistry.start_all()` is called by `kerf_core.app` after all plugins load. It invokes every registered factory and starts the returned worker objects.

---

## Pyworker dispatch

Compute-intensive operations dispatch to a separate `pyworker` process (typically `http://localhost:8090` or `PYWORKER_URL`). The pyworker runs in a Docker sidecar and has access to heavy dependencies (OpenCASCADE, FEniCS, openCAMlib, Blender) that are not imported in the main FastAPI process.

The pyworker endpoint contract: `POST /run-{domain}` with a JSON payload; response is `{"status": "ok", ...result...}` or `{"status": "error", "error": "..."}`.
