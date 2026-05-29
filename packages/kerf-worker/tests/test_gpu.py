"""Tests for GPU probing — NVIDIA, AMD ROCm, Apple Silicon Metal, and multi-GPU.

All tests are hermetic: subprocess calls and platform.system are mocked.
No real GPU hardware required.

Test matrix
-----------
1. probe_nvidia — nvidia-smi output parsed correctly.
2. probe_amd_rocm — rocm-smi CSV output parsed correctly.
3. probe_apple_silicon — M2 Mac sysctl output returns Metal info.
4. probe_gpus — mocked Mac with M2 returns Metal info.
5. probe_gpus — mocked Linux with both NVIDIA and AMD returns both.
6. probe_gpus — Windows / unknown platform returns [].
7. probe() legacy shim — NVIDIA path returns old caps shape.
8. probe() legacy shim — Apple Metal path returns old caps shape.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

# sys.path bootstrap so tests work without installing the package.
_HERE = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_HERE / "src"))

import kerf_worker.gpu as gpu_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run_result(stdout: str = "", returncode: int = 0) -> MagicMock:
    r = MagicMock()
    r.stdout = stdout
    r.stderr = ""
    r.returncode = returncode
    return r


# ---------------------------------------------------------------------------
# 1. probe_nvidia
# ---------------------------------------------------------------------------

class TestProbeNvidia:
    def test_parses_two_gpus(self):
        fake_out = "NVIDIA GeForce RTX 4090, 24576 MiB\nNVIDIA Tesla T4, 16384 MiB\n"
        with patch("subprocess.run", return_value=_make_run_result(fake_out)):
            gpus = gpu_mod.probe_nvidia()

        assert len(gpus) == 2
        assert gpus[0]["gpu_type"] == "nvidia"
        assert gpus[0]["gpu_name"] == "NVIDIA GeForce RTX 4090"
        assert gpus[0]["memory_total_mib"] == 24576
        assert gpus[0]["memory_total_bytes"] == 24576 * 1024 * 1024
        assert gpus[1]["gpu_name"] == "NVIDIA Tesla T4"
        assert gpus[1]["memory_total_mib"] == 16384

    def test_absent_returns_empty(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            gpus = gpu_mod.probe_nvidia()
        assert gpus == []

    def test_nonzero_returncode_returns_empty(self):
        with patch("subprocess.run", return_value=_make_run_result("", returncode=1)):
            gpus = gpu_mod.probe_nvidia()
        assert gpus == []


# ---------------------------------------------------------------------------
# 2. probe_amd_rocm
# ---------------------------------------------------------------------------

ROCM_SMI_CSV = (
    "device,Card series,Card model,Card vendor,VRAM Total Memory (B),VRAM Total Used Memory (B)\n"
    "0,Instinct,AMD Instinct MI300X,Advanced Micro Devices Inc.,196608000000,1048576\n"
    "1,RX 7900,AMD Radeon RX 7900 XTX,Advanced Micro Devices Inc.,26843545600,512000\n"
)


class TestProbeAmdRocm:
    def test_rocm_smi_csv_parsed(self):
        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.run", return_value=_make_run_result(ROCM_SMI_CSV)),
        ):
            gpus = gpu_mod.probe_amd_rocm()

        assert len(gpus) == 2
        assert gpus[0]["gpu_type"] == "amd_rocm"
        assert gpus[0]["gpu_name"] == "AMD Instinct MI300X"
        assert gpus[0]["memory_total_bytes"] == 196608000000
        assert gpus[0]["memory_total_mib"] == 196608000000 // (1024 * 1024)
        assert gpus[1]["gpu_name"] == "AMD Radeon RX 7900 XTX"

    def test_rocm_smi_absent_returns_empty_on_linux_no_sysfs(self, tmp_path):
        """rocm-smi missing + no /sys/class/drm → empty list."""
        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.run", side_effect=FileNotFoundError),
            patch("pathlib.Path.exists", return_value=False),
        ):
            gpus = gpu_mod.probe_amd_rocm()
        assert gpus == []

    def test_not_linux_returns_empty(self):
        with patch("platform.system", return_value="Darwin"):
            gpus = gpu_mod.probe_amd_rocm()
        assert gpus == []

    def test_windows_returns_empty(self):
        with patch("platform.system", return_value="Windows"):
            gpus = gpu_mod.probe_amd_rocm()
        assert gpus == []


# ---------------------------------------------------------------------------
# 3. probe_apple_silicon
# ---------------------------------------------------------------------------

class TestProbeAppleSilicon:
    def _patch_sysctl(self, brand: str, memsize: str = "17179869184"):
        """Return a subprocess.run mock that answers sysctl calls."""
        def _run(cmd, **kwargs):
            if "machdep.cpu.brand_string" in cmd:
                return _make_run_result(brand)
            if "hw.memsize" in cmd:
                return _make_run_result(memsize)
            return _make_run_result("", returncode=1)
        return _run

    def test_m2_pro_returns_metal_info(self):
        with (
            patch("platform.system", return_value="Darwin"),
            patch("subprocess.run", side_effect=self._patch_sysctl("Apple M2 Pro")),
        ):
            result = gpu_mod.probe_apple_silicon()

        assert result is not None
        assert result["gpu_type"] == "apple_metal"
        assert result["gpu_name"] == "Apple M2 Pro"
        assert result["metal"] is True
        assert result["unified_memory_bytes"] == 17179869184
        assert result["unified_memory_mib"] == 17179869184 // (1024 * 1024)

    def test_m1_detected(self):
        with (
            patch("platform.system", return_value="Darwin"),
            patch("subprocess.run", side_effect=self._patch_sysctl("Apple M1 Max", "34359738368")),
        ):
            result = gpu_mod.probe_apple_silicon()

        assert result is not None
        assert result["gpu_name"] == "Apple M1 Max"
        assert result["unified_memory_bytes"] == 34359738368

    def test_intel_mac_returns_none(self):
        with (
            patch("platform.system", return_value="Darwin"),
            patch("subprocess.run", side_effect=self._patch_sysctl("Intel(R) Core(TM) i9-9980HK CPU @ 2.40GHz")),
        ):
            # system_profiler fallback also returns no Apple GPU
            with patch.object(gpu_mod, "_apple_chip_name_from_system_profiler", return_value=None):
                result = gpu_mod.probe_apple_silicon()
        assert result is None

    def test_non_darwin_returns_none(self):
        with patch("platform.system", return_value="Linux"):
            result = gpu_mod.probe_apple_silicon()
        assert result is None


# ---------------------------------------------------------------------------
# 4. probe_gpus — mocked Mac with M2
# ---------------------------------------------------------------------------

class TestProbeGpusMac:
    def test_m2_mac_returns_metal(self):
        metal_gpu = {
            "gpu_type": "apple_metal",
            "gpu_name": "Apple M2",
            "unified_memory_bytes": 8589934592,
            "unified_memory_mib": 8192,
            "metal": True,
        }
        with (
            patch.object(gpu_mod, "probe_nvidia", return_value=[]),
            patch.object(gpu_mod, "probe_amd_rocm", return_value=[]),
            patch.object(gpu_mod, "probe_apple_silicon", return_value=metal_gpu),
        ):
            gpus = gpu_mod.probe_gpus()

        assert len(gpus) == 1
        assert gpus[0]["gpu_type"] == "apple_metal"
        assert gpus[0]["gpu_name"] == "Apple M2"
        assert gpus[0]["metal"] is True


# ---------------------------------------------------------------------------
# 5. probe_gpus — mocked Linux with NVIDIA + AMD
# ---------------------------------------------------------------------------

class TestProbeGpusLinuxMixed:
    def test_nvidia_and_amd_both_returned(self):
        nvidia_gpu = {
            "gpu_type": "nvidia",
            "gpu_name": "NVIDIA GeForce RTX 4090",
            "memory_total_mib": 24576,
            "memory_total_bytes": 24576 * 1024 * 1024,
        }
        amd_gpu = {
            "gpu_type": "amd_rocm",
            "gpu_name": "AMD Radeon RX 7900 XTX",
            "memory_total_bytes": 26843545600,
            "memory_total_mib": 25600,
        }
        with (
            patch.object(gpu_mod, "probe_nvidia", return_value=[nvidia_gpu]),
            patch.object(gpu_mod, "probe_amd_rocm", return_value=[amd_gpu]),
            patch.object(gpu_mod, "probe_apple_silicon", return_value=None),
        ):
            gpus = gpu_mod.probe_gpus()

        assert len(gpus) == 2
        types = {g["gpu_type"] for g in gpus}
        assert types == {"nvidia", "amd_rocm"}
        names = {g["gpu_name"] for g in gpus}
        assert "NVIDIA GeForce RTX 4090" in names
        assert "AMD Radeon RX 7900 XTX" in names


# ---------------------------------------------------------------------------
# 6. probe_gpus — Windows / unknown platform returns []
# ---------------------------------------------------------------------------

class TestProbeGpusUnknown:
    def test_windows_returns_empty(self):
        with (
            patch.object(gpu_mod, "probe_nvidia", return_value=[]),
            patch.object(gpu_mod, "probe_amd_rocm", return_value=[]),
            patch.object(gpu_mod, "probe_apple_silicon", return_value=None),
        ):
            gpus = gpu_mod.probe_gpus()
        assert gpus == []

    def test_no_gpus_returns_empty_list(self):
        with (
            patch.object(gpu_mod, "probe_nvidia", return_value=[]),
            patch.object(gpu_mod, "probe_amd_rocm", return_value=[]),
            patch.object(gpu_mod, "probe_apple_silicon", return_value=None),
            patch("platform.system", return_value="Windows"),
        ):
            gpus = gpu_mod.probe_gpus()
        assert gpus == []


# ---------------------------------------------------------------------------
# 7 & 8. probe() legacy shim
# ---------------------------------------------------------------------------

class TestLegacyProbe:
    def test_nvidia_returns_legacy_caps_shape(self):
        nvidia_gpu = {
            "gpu_type": "nvidia",
            "gpu_name": "NVIDIA GeForce RTX 4090",
            "memory_total_mib": 24576,
            "memory_total_bytes": 24576 * 1024 * 1024,
        }
        with patch.object(gpu_mod, "probe_gpus", return_value=[nvidia_gpu]):
            caps = gpu_mod.probe()

        assert caps["platform"] == "linux-nvidia"
        assert len(caps["gpus"]) == 1
        assert caps["gpus"][0]["name"] == "NVIDIA GeForce RTX 4090"
        assert caps["gpus"][0]["memory_total_mib"] == 24576
        assert "cycles_render" in caps["supported_workloads"]
        assert "fem_solve" in caps["supported_workloads"]

    def test_apple_metal_returns_legacy_caps_shape(self):
        metal_gpu = {
            "gpu_type": "apple_metal",
            "gpu_name": "Apple M2 Pro",
            "unified_memory_bytes": 17179869184,
            "unified_memory_mib": 16384,
            "metal": True,
        }
        with patch.object(gpu_mod, "probe_gpus", return_value=[metal_gpu]):
            caps = gpu_mod.probe()

        assert caps["platform"] == "darwin-metal"
        assert len(caps["gpus"]) == 1
        assert caps["gpus"][0]["name"] == "Apple M2 Pro"
        assert caps["gpus"][0]["memory_total_mib"] == 16384
        assert caps["gpus"][0]["metal"] is True

    def test_no_gpus_returns_empty_with_note(self):
        with (
            patch.object(gpu_mod, "probe_gpus", return_value=[]),
            patch("platform.system", return_value="Linux"),
        ):
            caps = gpu_mod.probe()

        assert caps["gpus"] == []
        assert "probe_note" in caps
        assert caps["platform"].endswith("-unknown")
