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
- **For `firmware_flash` jobs:** one or more of the flash tools listed in
  [Enabling firmware flash](#enabling-firmware-flash) below.
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
- On a `firmware_flash` job: downloads the firmware artifact, selects the right flash
  tool based on `board_target`, shells out to the tool, and uploads the flash log
  via the job's `signed_upload_url`.

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
| `FIRMWARE_FLASH_POLL_INTERVAL` | `5` | Seconds between firmware_flash queue polls (server-side worker) |

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

---

## Enabling firmware flash

`kerf-worker` can claim `firmware_flash` jobs and execute them on
boards physically attached to the worker machine via USB/JTAG.

At `enroll` time the CLI probes `PATH` for flash tools and advertises what it
finds to the server.  The server only dispatches `firmware_flash` jobs to workers
that have the required tool for the requested `board_target`.

### Supported flash tools

| Tool | Install command | Supported boards |
|---|---|---|
| **esptool** | `pip install esptool` | ESP32, ESP8266 |
| **avrdude** | `brew install avrdude` / `sudo apt install avrdude` | Arduino AVR, ATmega |
| **openocd** | `brew install openocd` / `sudo apt install openocd` | STM32, ARM Cortex-M |
| **picotool** | See [raspberrypi/picotool](https://github.com/raspberrypi/picotool) | RP2040 |

None of these tools are hard dependencies of `kerf-worker` itself — they are
external system tools detected at enroll time.  Install only the ones you need.

### Re-enroll after installing new tools

```bash
kerf-worker revoke --yes
kerf-worker enroll kerf_wk_<new-token>
```

Re-enrollment re-probes capabilities including newly installed flash tools.

### Board-target routing

The job payload's `board_target` field controls tool selection:

| board_target prefix | Tool used |
|---|---|
| `esp32*`, `esp8266*` | esptool |
| `avr*` | avrdude |
| `stm32*`, `arm*` | openocd |
| `rp2040` | picotool |
| *(default)* | avrdude |

### Billing

`firmware_flash` jobs always carry `billing_bucket='byo'` — **no Kerf credits
are consumed**.  The worker is expected to be a workshop machine the user
controls directly.

---

## Development

```bash
cd packages/kerf-worker
pip install -e ".[dev]"
pytest tests/ -v
```
