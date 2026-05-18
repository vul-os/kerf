"""
PlatformIO Core CLI subprocess wrapper.

Invokes `pio run` (or `platformio run`) as a child process — the subprocess
boundary keeps the hosted service MIT-compatible regardless of the target
framework's licence (Arduino, ESP-IDF, Zephyr, Mbed, etc.).

PlatformIO Core CLI shape (verified against PlatformIO Core 6.x docs):

    pio run \\
        --project-dir <dir>   \\
        --environment <env>   \\
        --target <target>     \\   # optional: 'upload', 'clean', default build-only
        --verbose

PlatformIO emits build output to stdout; artefacts land in
`<project-dir>/.pio/build/<env>/`:
  firmware.elf    — ELF binary (always produced)
  firmware.hex    — Intel HEX (produced for AVR and similar targets)
  firmware.bin    — raw binary (produced for ARM targets)

Surprising nuances:
  - The binary may be called `pio` (the pip-installed shim) or `platformio`
    (older PATH installs). We try `pio` first, then `platformio`.
  - PlatformIO Core reads `platformio.ini` from the project directory; we
    write a minimal one when the caller provides board+framework instead of
    a pre-existing INI.
  - Build times: a fresh Arduino/AVR compile is ~10 s; ESP32 from scratch
    can take 3–5 min (framework download). The 120 s timeout covers typical
    incremental builds; a first-build hint is surfaced in warnings when the
    subprocess exits with timeout.
  - The `.pio/` directory is created under a temporary working dir and
    cleaned up after the build; only artefact paths (ELF/HEX/BIN) are
    returned.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple


# ── public exceptions ─────────────────────────────────────────────────────────

class PlatformIONotInstalledError(RuntimeError):
    """Raised when neither `pio` nor `platformio` is found on PATH."""


class FirmwareBuildError(RuntimeError):
    """Raised when PlatformIO exits with a non-zero status."""


# ── result type ───────────────────────────────────────────────────────────────

class BuildResult(NamedTuple):
    elf_path: str | None    # absolute path to the ELF artefact (always present)
    hex_path: str | None    # absolute path to the HEX artefact (AVR targets)
    bin_path: str | None    # absolute path to the BIN artefact (ARM targets)
    build_log: str          # full stdout+stderr from the build
    build_log_lines: int    # total lines in build_log
    artefact_bytes: int     # size of the primary artefact (ELF if present)
    environment: str        # the PlatformIO environment built
    warnings: list[str]


# ── binary probe ──────────────────────────────────────────────────────────────

def _pio_binary() -> str | None:
    """Return the first PlatformIO CLI binary found on PATH, or None."""
    for name in ("pio", "platformio"):
        found = shutil.which(name)
        if found:
            return found
    return None


# ── minimal platformio.ini template ──────────────────────────────────────────

def _write_minimal_ini(project_dir: Path, board: str, framework: str) -> None:
    """
    Write a minimal platformio.ini for a single-board build.

    The caller provides the PlatformIO board ID (e.g. 'uno', 'esp32dev') and
    the framework name (e.g. 'arduino', 'espidf').  The platform is inferred
    from a best-effort mapping; unknown boards fall back to 'atmelavr' so the
    build still proceeds (PlatformIO will report a clear error if the board
    is genuinely unknown).
    """
    platform = _infer_platform(board)
    ini_content = (
        "[env:{env}]\n"
        "platform  = {platform}\n"
        "board     = {board}\n"
        "framework = {framework}\n"
    ).format(
        env=board,
        platform=platform,
        board=board,
        framework=framework,
    )
    (project_dir / "platformio.ini").write_text(ini_content, encoding="utf-8")


_PLATFORM_MAP: dict[str, str] = {
    # AVR
    "uno":           "atmelavr",
    "nano":          "atmelavr",
    "mega2560":      "atmelavr",
    "leonardo":      "atmelavr",
    "micro":         "atmelavr",
    "pro8MHzatmega328": "atmelavr",
    # ESP
    "esp32dev":      "espressif32",
    "esp32s2dev":    "espressif32",
    "esp32s3box":    "espressif32",
    "nodemcuv2":     "espressif8266",
    "d1_mini":       "espressif8266",
    # ARM / STM32
    "disco_f407vg":  "ststm32",
    "nucleo_f401re": "ststm32",
    "bluepill_f103c8": "ststm32",
    # Teensy
    "teensylc":      "teensy",
    "teensy31":      "teensy",
    "teensy40":      "teensy",
    # RP2040
    "pico":          "raspberrypi",
}


def _infer_platform(board: str) -> str:
    """Best-effort board-id → PlatformIO platform mapping."""
    return _PLATFORM_MAP.get(board, "atmelavr")


# ── artefact discovery ────────────────────────────────────────────────────────

def _find_artefacts(project_dir: Path, env: str) -> tuple[str | None, str | None, str | None]:
    """
    Scan `.pio/build/<env>/` for ELF, HEX, and BIN artefacts.

    Returns (elf_path, hex_path, bin_path) — each is an absolute string or
    None when not found.
    """
    build_dir = project_dir / ".pio" / "build" / env
    if not build_dir.is_dir():
        return None, None, None

    elf = None
    hex_ = None
    bin_ = None

    for candidate in build_dir.iterdir():
        name = candidate.name.lower()
        if name.endswith(".elf") and elf is None:
            elf = str(candidate)
        elif name.endswith(".hex") and hex_ is None:
            hex_ = str(candidate)
        elif name.endswith(".bin") and bin_ is None:
            bin_ = str(candidate)

    return elf, hex_, bin_


# ── main entry point ──────────────────────────────────────────────────────────

def build_firmware(
    sketch_dir: str | Path,
    board: str = "uno",
    framework: str = "arduino",
    environment: str | None = None,
    extra_flags: list[str] | None = None,
    timeout: int | None = None,
) -> BuildResult:
    """
    Compile a firmware sketch with PlatformIO Core CLI.

    Parameters
    ----------
    sketch_dir:
        Directory containing the sketch source (and optionally an existing
        `platformio.ini`).  If `platformio.ini` is absent, a minimal one is
        generated from `board` and `framework`.
    board:
        PlatformIO board ID (e.g. 'uno', 'esp32dev').  Ignored when
        `platformio.ini` is already present in `sketch_dir`.
    framework:
        PlatformIO framework name (e.g. 'arduino', 'espidf').  Ignored when
        `platformio.ini` is already present.
    environment:
        PlatformIO environment name to build.  Defaults to `board` when a
        minimal INI is generated; required when using a pre-existing INI with
        multiple environments.
    extra_flags:
        Extra CLI flags appended to the `pio run` command (e.g.
        ['--verbose']).
    timeout:
        Subprocess timeout in seconds.  Defaults to 120 (covers incremental
        builds; first-time framework downloads may exceed this).

    Raises
    ------
    PlatformIONotInstalledError
        When neither `pio` nor `platformio` is on PATH.
    FirmwareBuildError
        When PlatformIO exits with a non-zero status.
    FileNotFoundError
        When `sketch_dir` does not exist.
    """
    sketch_dir = Path(sketch_dir)
    if not sketch_dir.exists():
        raise FileNotFoundError(str(sketch_dir))

    binary = _pio_binary()
    if binary is None:
        raise PlatformIONotInstalledError(
            "PlatformIO Core CLI not found. Install it and ensure it is on PATH. "
            "pip install platformio  |  brew install platformio"
        )

    timeout = timeout or int(os.environ.get("PIO_BUILD_TIMEOUT", "120"))
    warnings: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir) / "project"
        # Copy the sketch into the temp work directory so we don't pollute the
        # caller's source tree with PlatformIO's .pio cache.
        shutil.copytree(str(sketch_dir), str(work_dir))

        # Generate a minimal platformio.ini if one is not already present.
        ini_path = work_dir / "platformio.ini"
        if not ini_path.exists():
            _write_minimal_ini(work_dir, board, framework)
            env = environment or board
        else:
            # Use the provided environment or let PlatformIO pick the default.
            env = environment or board

        cmd: list[str] = [binary, "run", "--project-dir", str(work_dir)]
        if env:
            cmd += ["--environment", env]
        if extra_flags:
            cmd.extend(extra_flags)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            warnings.append(
                f"PlatformIO build timed out after {timeout}s. "
                "First-time framework downloads may require a longer timeout — "
                "set the PIO_BUILD_TIMEOUT environment variable."
            )
            raise FirmwareBuildError(
                f"PlatformIO timed out after {timeout}s"
            )

        build_log = (proc.stdout or "") + (proc.stderr or "")

        if proc.returncode != 0:
            log_tail = build_log[-1200:]
            raise FirmwareBuildError(
                f"PlatformIO exited {proc.returncode}. log tail:\n{log_tail}"
            )

        # Discover artefacts from the temp work directory.
        elf, hex_, bin_ = _find_artefacts(work_dir, env)

        if elf is None and hex_ is None and bin_ is None:
            warnings.append("PlatformIO exited 0 but no ELF/HEX/BIN artefact was found")

        primary = elf or hex_ or bin_
        artefact_bytes = Path(primary).stat().st_size if primary else 0

        return BuildResult(
            elf_path=elf,
            hex_path=hex_,
            bin_path=bin_,
            build_log=build_log,
            build_log_lines=len(build_log.splitlines()),
            artefact_bytes=artefact_bytes,
            environment=env,
            warnings=warnings,
        )
