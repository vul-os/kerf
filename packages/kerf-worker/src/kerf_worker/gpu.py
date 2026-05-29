"""GPU capability probing.

Currently supports NVIDIA GPUs via ``nvidia-smi``.
Apple Silicon Metal and AMD ROCm support is a follow-on; those paths raise
a descriptive error today rather than silently returning empty capabilities.

Returns a dict suitable for the ``capabilities`` field in the enroll request:

    {
        "gpus": [
            {"name": "NVIDIA GeForce RTX 4090", "memory_total_mib": 24576},
            ...
        ],
        "supported_workloads": ["cycles_render", "fem_solve"],
        "platform": "linux-nvidia"
    }
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict, List


def _probe_nvidia() -> List[Dict[str, Any]]:
    """Query ``nvidia-smi`` for GPU name + memory.  Returns [] if not found."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    gpus: List[Dict[str, Any]] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",", 1)
        name = parts[0].strip()
        memory_total_mib = 0
        if len(parts) == 2:
            mem_str = parts[1].strip()  # e.g. "24576 MiB"
            try:
                memory_total_mib = int(mem_str.split()[0])
            except (ValueError, IndexError):
                pass
        gpus.append({"name": name, "memory_total_mib": memory_total_mib})

    return gpus


def probe() -> Dict[str, Any]:
    """Probe GPU capabilities on this machine.

    On Linux with NVIDIA drivers installed, returns full GPU info.
    On other platforms, returns a minimal stub and logs a notice.
    """
    gpus = _probe_nvidia()

    if gpus:
        return {
            "gpus": gpus,
            "supported_workloads": ["cycles_render", "fem_solve"],
            "platform": "linux-nvidia",
        }

    # No NVIDIA GPUs found — still usable but capabilities are limited.
    import platform

    plat = platform.system().lower()
    if plat == "darwin":
        note = (
            "Apple Silicon Metal probing is not yet supported. "
            "Worker enrolled with empty GPU capabilities — "
            "follow-on: add Metal/Core ML detection."
        )
    elif plat == "linux":
        note = (
            "nvidia-smi not found or returned no GPUs. "
            "If you have AMD/ROCm GPUs, ROCm probing is not yet supported — follow-on."
        )
    else:
        note = f"GPU probing not supported on {platform.system()}."

    import sys
    print(f"[kerf-worker] WARNING: {note}", file=sys.stderr)

    return {
        "gpus": [],
        "supported_workloads": ["cycles_render", "fem_solve"],
        "platform": f"{plat}-unknown",
        "probe_note": note,
    }
