"""GPU capability probing — NVIDIA, AMD ROCm, and Apple Silicon Metal.

``probe_gpus()`` is the top-level entry-point.  It tries all three probe
paths in order and returns ALL GPUs found (multi-GPU support).  Returns an
empty list when no GPU is detected, not an error — the worker can still
handle CPU-only jobs.

Returned dict shape per GPU
----------------------------
NVIDIA::

    {
        "gpu_type": "nvidia",
        "gpu_name": "NVIDIA GeForce RTX 4090",
        "memory_total_bytes": 25769803776,   # 24576 MiB -> bytes
        "memory_total_mib": 24576,
    }

AMD ROCm::

    {
        "gpu_type": "amd_rocm",
        "gpu_name": "AMD Instinct MI300X",
        "memory_total_bytes": 196608000000,
        "memory_total_mib": 188416,
    }

Apple Silicon Metal::

    {
        "gpu_type": "apple_metal",
        "gpu_name": "Apple M2 Pro",
        "unified_memory_bytes": 17179869184,   # 16 GB
        "unified_memory_mib": 16384,
        "metal": True,
    }

``probe()`` (legacy shim) wraps ``probe_gpus()`` and returns the old dict
shape used by the ``enroll`` command before the multi-platform refactor.
"""
from __future__ import annotations

import platform
import subprocess
import sys
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# NVIDIA
# ---------------------------------------------------------------------------

def probe_nvidia() -> List[Dict[str, Any]]:
    """Query ``nvidia-smi`` for NVIDIA GPU name + memory.

    Returns a list of GPU dicts (may be empty if nvidia-smi is not found or
    returns no output).
    """
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
        gpus.append(
            {
                "gpu_type": "nvidia",
                "gpu_name": name,
                "memory_total_mib": memory_total_mib,
                "memory_total_bytes": memory_total_mib * 1024 * 1024,
            }
        )

    return gpus


# ---------------------------------------------------------------------------
# AMD ROCm
# ---------------------------------------------------------------------------

def probe_amd_rocm() -> List[Dict[str, Any]]:
    """Probe AMD GPUs via ``rocm-smi`` on Linux.

    Tries ``rocm-smi --showproductname --showmeminfo vram --csv``.  Falls
    back to a sysfs walk under ``/sys/class/drm/card*/device/`` when
    ``rocm-smi`` is absent but the DRM entries are present (e.g. bare amdgpu
    without the full ROCm stack).

    Returns a list of GPU dicts (may be empty).
    """
    if platform.system().lower() != "linux":
        return []

    gpus = _probe_rocm_smi()
    if gpus:
        return gpus

    return _probe_amd_sysfs()


def _probe_rocm_smi() -> List[Dict[str, Any]]:
    """Parse ``rocm-smi --showproductname --showmeminfo vram --csv``."""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--csv"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    # CSV header looks like:
    #   device,Card series,Card model,Card vendor,...,VRAM Total Memory (B),...
    # We need "Card model" (or "Card series") and "VRAM Total Memory (B)".
    lines = result.stdout.strip().splitlines()
    if len(lines) < 2:
        return []

    header = [h.strip() for h in lines[0].split(",")]

    # Prefer "Card model", fall back to "Card series".
    name_col: Optional[int] = None
    for candidate in ("Card model", "Card series", "card model", "card series"):
        if candidate in header:
            name_col = header.index(candidate)
            break

    vram_col: Optional[int] = None
    for candidate in ("VRAM Total Memory (B)", "VRAM Total Memory(B)", "vram_total"):
        if candidate in header:
            vram_col = header.index(candidate)
            break

    gpus: List[Dict[str, Any]] = []
    for row_line in lines[1:]:
        row_line = row_line.strip()
        if not row_line:
            continue
        cols = [c.strip() for c in row_line.split(",")]

        name = cols[name_col].strip('"') if name_col is not None and name_col < len(cols) else "AMD GPU"
        if not name:
            name = "AMD GPU"

        vram_bytes = 0
        if vram_col is not None and vram_col < len(cols):
            try:
                vram_bytes = int(cols[vram_col])
            except ValueError:
                pass

        vram_mib = vram_bytes // (1024 * 1024) if vram_bytes else 0

        gpus.append(
            {
                "gpu_type": "amd_rocm",
                "gpu_name": name,
                "memory_total_bytes": vram_bytes,
                "memory_total_mib": vram_mib,
            }
        )

    return gpus


def _probe_amd_sysfs() -> List[Dict[str, Any]]:
    """Walk ``/sys/class/drm/cardN/device/`` to find AMD GPUs without ROCm tools.

    Reads ``vendor`` (0x1002 = AMD) and ``mem_info_vram_total`` to get VRAM.
    """
    import pathlib

    drm = pathlib.Path("/sys/class/drm")
    if not drm.exists():
        return []

    gpus: List[Dict[str, Any]] = []

    for card_link in sorted(drm.glob("card*")):
        # Skip renderD* and connectors.
        if not card_link.name.startswith("card") or not card_link.name[4:].isdigit():
            continue

        dev = card_link / "device"
        vendor_file = dev / "vendor"
        if not vendor_file.exists():
            continue

        try:
            vendor = vendor_file.read_text().strip().lower()
        except OSError:
            continue

        # AMD vendor IDs: 0x1002
        if vendor not in ("0x1002",):
            continue

        # Try to read a human-readable name.
        name = "AMD GPU"
        uevent = dev / "uevent"
        if uevent.exists():
            try:
                for line in uevent.read_text().splitlines():
                    if line.startswith("PCI_ID="):
                        pci_id = line.split("=", 1)[1].strip()
                        name = f"AMD GPU ({pci_id})"
                        break
            except OSError:
                pass

        # VRAM size.
        vram_bytes = 0
        vram_file = dev / "mem_info_vram_total"
        if vram_file.exists():
            try:
                vram_bytes = int(vram_file.read_text().strip())
            except (ValueError, OSError):
                pass

        gpus.append(
            {
                "gpu_type": "amd_rocm",
                "gpu_name": name,
                "memory_total_bytes": vram_bytes,
                "memory_total_mib": vram_bytes // (1024 * 1024) if vram_bytes else 0,
            }
        )

    return gpus


# ---------------------------------------------------------------------------
# Apple Silicon Metal
# ---------------------------------------------------------------------------

def probe_apple_silicon() -> Optional[Dict[str, Any]]:
    """Detect Apple Silicon (M-series) on macOS via ``sysctl`` + ``system_profiler``.

    Returns a single GPU dict or ``None`` if not on Apple Silicon or macOS.

    The GPU and system RAM share the same unified memory pool; we report the
    total physical RAM as ``unified_memory_bytes`` (same as VRAM for
    scheduling purposes).
    """
    if platform.system().lower() != "darwin":
        return None

    # 1. Check that this is an Apple Silicon chip (not Intel Mac).
    chip_name = _apple_chip_name()
    if chip_name is None:
        return None

    # 2. Read unified memory size.
    mem_bytes = _apple_unified_memory_bytes()
    mem_mib = mem_bytes // (1024 * 1024) if mem_bytes else 0

    return {
        "gpu_type": "apple_metal",
        "gpu_name": chip_name,
        "unified_memory_bytes": mem_bytes,
        "unified_memory_mib": mem_mib,
        "metal": True,
    }


def _apple_chip_name() -> Optional[str]:
    """Return the M-series chip name via ``sysctl machdep.cpu.brand_string``.

    Returns ``None`` on Intel Macs or on any error.
    """
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    brand = result.stdout.strip()
    # Apple Silicon reports e.g. "Apple M2 Pro" or "Apple M3 Max".
    # Intel Macs report e.g. "Intel(R) Core(TM) i9-9980HK CPU @ 2.40GHz".
    if brand.startswith("Apple") and any(
        f" M{n}" in brand for n in ("1", "2", "3", "4")
    ):
        return brand

    # Fallback: use system_profiler to get the GPU renderer string.
    return _apple_chip_name_from_system_profiler()


def _apple_chip_name_from_system_profiler() -> Optional[str]:
    """Parse ``system_profiler SPDisplaysDataType`` for Metal renderer name."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    # Look for "Chipset Model:" or "Chip:" lines.
    for line in result.stdout.splitlines():
        line_stripped = line.strip()
        for key in ("Chip:", "Chipset Model:"):
            if line_stripped.startswith(key):
                value = line_stripped[len(key):].strip()
                if value.lower().startswith("apple"):
                    return value

    return None


def _apple_unified_memory_bytes() -> int:
    """Return total physical RAM bytes via ``sysctl hw.memsize``."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0

    if result.returncode != 0:
        return 0

    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Top-level multi-GPU probe
# ---------------------------------------------------------------------------

def probe_gpus() -> List[Dict[str, Any]]:
    """Probe all GPU types and return every GPU found.

    Tries NVIDIA -> AMD ROCm -> Apple Metal in order.  NVIDIA and AMD can
    coexist on the same Linux machine (e.g. workstations with a mixed card
    set), so both are accumulated.  Apple Metal is exclusive to macOS and
    returns at most one entry (unified GPU).

    Returns an empty list when no GPU is detected — not an error.
    """
    gpus: List[Dict[str, Any]] = []
    gpus.extend(probe_nvidia())
    gpus.extend(probe_amd_rocm())
    metal = probe_apple_silicon()
    if metal is not None:
        gpus.append(metal)
    return gpus


# ---------------------------------------------------------------------------
# Legacy shim — keeps the ``enroll`` CLI path unchanged
# ---------------------------------------------------------------------------

def probe() -> Dict[str, Any]:
    """Legacy probe shim used by ``kerf-worker enroll``.

    Wraps ``probe_gpus()`` and returns the old capabilities dict shape.
    """
    gpus = probe_gpus()

    if not gpus:
        plat = platform.system().lower()
        note = {
            "darwin": (
                "No Apple Silicon GPU detected. "
                "If this is an Intel Mac or an M-series without Metal drivers, "
                "the worker enrolls with empty GPU capabilities."
            ),
            "linux": (
                "No NVIDIA or AMD ROCm GPU detected. "
                "If you have a GPU, ensure nvidia-smi or rocm-smi is in PATH."
            ),
        }.get(plat, f"GPU probing not supported on {platform.system()}.")

        print(f"[kerf-worker] WARNING: {note}", file=sys.stderr)

        return {
            "gpus": [],
            "supported_workloads": ["cycles_render", "fem_solve"],
            "platform": f"{plat}-unknown",
            "probe_note": note,
        }

    # Determine a platform tag from the first GPU.
    first = gpus[0]
    gpu_type = first.get("gpu_type", "unknown")
    plat_tag = {
        "nvidia": "linux-nvidia",
        "amd_rocm": "linux-amd-rocm",
        "apple_metal": "darwin-metal",
    }.get(gpu_type, f"{platform.system().lower()}-{gpu_type}")

    # Normalise to the legacy "gpus" list shape expected by the server.
    legacy_gpus = []
    for g in gpus:
        if g["gpu_type"] == "apple_metal":
            legacy_gpus.append(
                {
                    "name": g["gpu_name"],
                    "memory_total_mib": g.get("unified_memory_mib", 0),
                    "gpu_type": g["gpu_type"],
                    "metal": True,
                }
            )
        else:
            legacy_gpus.append(
                {
                    "name": g["gpu_name"],
                    "memory_total_mib": g.get("memory_total_mib", 0),
                    "gpu_type": g["gpu_type"],
                }
            )

    return {
        "gpus": legacy_gpus,
        "supported_workloads": ["cycles_render", "fem_solve"],
        "platform": plat_tag,
    }
