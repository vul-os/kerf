# kerf-worker

BYO GPU worker companion CLI for [Kerf](https://kerf.sh).

Run Kerf render and simulation jobs on **your own GPU hardware** — zero credit consumption,
billed at your hardware cost only.

---

## Prerequisites

- Python 3.11+
- **For `cycles_render` jobs:** [Blender](https://www.blender.org/download/) 3.6+ in `PATH`
  (or set `BLENDER_PATH=/path/to/blender`).
- **For `fem_solve` jobs:** [CalculiX](https://www.calculix.de/) `ccx` in `PATH`
  (or set `CCX_PATH=/path/to/ccx`).
- GPU hardware (NVIDIA, AMD, or Apple Silicon) — see [GPU support](#gpu-support) below.
  CPU-only machines can also enroll; they just run fewer workloads.

---

## Install

```bash
pip install kerf-worker
```

---

## Enrolling

1. Log in to [kerf.sh](https://kerf.sh) → **Settings → Workers → Enroll new worker**.
2. Copy the one-time token shown (begins with `kerf_wk_`).
3. On your GPU machine:

```bash
kerf-worker enroll kerf_wk_<token>
```

Optional flags:

| Flag | Default | Description |
|---|---|---|
| `--name` | hostname | Human-readable worker name shown in the dashboard |
| `--api-url` | `https://kerf.sh` | Override API base (self-hosted installs) |

Credentials are stored in `~/.config/kerf/worker.json` (mode 0600).

---

## Running the worker loop

```bash
kerf-worker run
```

The loop:
- Sends a **heartbeat** every 30 s so the dashboard shows the worker as online.
- **Long-polls** for queued jobs (30 s window).
- On a `cycles_render` job: downloads the `.blend` scene, runs `blender -b -F PNG -f 1`,
  uploads the resulting PNG to the server.
- On a `fem_solve` job: downloads the `.inp` file, runs `ccx`, uploads the `.frd` result.

Stop with `Ctrl-C` or `SIGTERM`.

---

## Status

```bash
kerf-worker status
```

Prints:

```
=== kerf-worker status ===
Worker ID      : <uuid>
Name           : rtx-4090-box
API base       : https://kerf.sh
Last heartbeat : 2026-05-29T14:01:23+00:00
Current job    : (none)
GPUs:
  NVIDIA GeForce RTX 4090 (24576 MiB)
Workloads      : cycles_render, fem_solve
Config path    : /home/user/.config/kerf/worker.json
```

---

## Revoking

```bash
kerf-worker revoke
```

Calls `DELETE /api/workers/{id}` to invalidate the token on the server, then removes
`~/.config/kerf/worker.json`. Use `--yes` to skip the confirmation prompt.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `KERF_API_URL` | `https://kerf.sh` | API base URL (overrides stored value) |
| `KERF_WORKER_CONFIG` | `~/.config/kerf/worker.json` | Config file path (useful in tests) |
| `BLENDER_PATH` | `blender` | Path to the Blender binary |
| `CCX_PATH` | `ccx` | Path to the CalculiX binary |

---

## GPU support

`kerf-worker enroll` probes all available GPU types automatically and reports
them to the server.  Probe order: NVIDIA → AMD ROCm → Apple Metal.  Multi-GPU
machines are fully supported — all detected GPUs are reported.

| Platform | Detection method | What is reported |
|---|---|---|
| **NVIDIA (Linux)** | `nvidia-smi --query-gpu=name,memory.total` | GPU name + VRAM (MiB) |
| **AMD ROCm (Linux)** | `rocm-smi --showproductname --showmeminfo vram --csv` | GPU name + VRAM (bytes) |
| **AMD (Linux, no ROCm tools)** | `/sys/class/drm/card*/device/vendor` + `mem_info_vram_total` | GPU name + VRAM from sysfs |
| **Apple Silicon (macOS)** | `sysctl machdep.cpu.brand_string` + `sysctl hw.memsize` | Chip name + unified memory size, `metal: true` |
| **Intel Mac / Windows / other** | — | Enrolls with empty GPU list; CPU jobs still run |

No extra Python packages are required — all probing uses subprocesses (`nvidia-smi`,
`rocm-smi`, `sysctl`, `system_profiler`) that are present when the GPU drivers
are installed.

---

## Billing

BYO workers run under the `byo` billing bucket — **no Kerf credits are charged**
regardless of job duration or GPU type. You pay only your own electricity / cloud GPU bill.

This is enforced server-side: `render_jobs.billing_bucket = 'byo'` short-circuits
the credit meter in `POST /api/workers/{id}/jobs/{job_id}/complete`.

---

## Development

```bash
cd packages/kerf-worker
pip install -e ".[dev]"
pytest tests/ -v
```
