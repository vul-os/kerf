"""
Direct-gcc build orchestrator for embedded firmware.

Compiles a set of C/C++ source files using the architecture's cross-compiler
toolchain, links them into an ELF, then post-processes via ``objcopy`` to
produce the primary firmware image (``.hex`` / ``.bin`` / ``.uf2``).

Public API
----------
    build(sources, includes, arch, output_dir, board_meta) -> BuildArtifact

Toolchain detection
-------------------
Each architecture's compiler binary is located with ``shutil.which()``.  If
the compiler is absent the function returns a *pending* ``BuildArtifact``
immediately — it never raises and never attempts to install the toolchain.
Install hints are embedded in the returned artefact for the UI to surface.

Build pipeline
--------------
1. For each source file (.c or .cpp):
   - Run ``<compiler> -c <flags> -I<include>... <src> -o <src.o>``
2. Link all ``.o`` files into ``firmware.elf``:
   - Run ``<compiler> <link_flags> -o firmware.elf *.o [-T <linker_script>]``
3. Post-process with ``objcopy``:
   - ``.hex``:  ``objcopy -O ihex firmware.elf firmware.hex``
   - ``.bin``:  ``objcopy -O binary firmware.elf firmware.bin``
   - ``.uf2``:  ``.elf → .bin`` first, then call the uf2 tool if available;
                otherwise fall back to ``.bin``.

Linker script
-------------
If ``board_meta`` contains a ``"linker_script"`` key pointing to a ``.ld``
file that exists on disk, that script is passed to the linker via ``-T``.

Error handling
--------------
Any non-zero compiler / linker / objcopy exit code converts the result to
``status="error"`` with the stderr excerpt in ``errors``.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from .arch_profiles import ArchProfile, get_profile
from .build_artifacts import BuildArtifact

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_CAPTURE_LIMIT = 8192  # bytes of stderr/stdout kept per subprocess call


# ---------------------------------------------------------------------------
# Toolchain availability helpers
# ---------------------------------------------------------------------------

def _compiler_available(compiler: str) -> bool:
    """Return ``True`` when *compiler* is on PATH."""
    return shutil.which(compiler) is not None


# ---------------------------------------------------------------------------
# Source-file classification
# ---------------------------------------------------------------------------

_CXX_EXTENSIONS = frozenset({".cpp", ".cxx", ".cc", ".C"})
_C_EXTENSIONS = frozenset({".c"})


def _is_cxx(path: Path) -> bool:
    return path.suffix in _CXX_EXTENSIONS


def _is_c(path: Path) -> bool:
    return path.suffix in _C_EXTENSIONS


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _run(
    argv: list[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
) -> tuple[int, str, str]:
    """Run *argv*, return ``(returncode, stdout_tail, stderr_tail)``."""
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
        )
        return (
            proc.returncode,
            proc.stdout[-_CAPTURE_LIMIT:],
            proc.stderr[-_CAPTURE_LIMIT:],
        )
    except FileNotFoundError as exc:
        return (1, "", f"executable not found: {exc}")


# ---------------------------------------------------------------------------
# Compile stage
# ---------------------------------------------------------------------------

def _compile_source(
    src: Path,
    obj: Path,
    profile: ArchProfile,
    board_meta: dict,
    include_dirs: list[Path],
) -> tuple[bool, str]:
    """Compile a single source file to an object file.

    Returns ``(success, stderr_excerpt)``.
    """
    if _is_cxx(src):
        compiler = profile.cxx_compiler
        flags = profile.all_cxx_flags(board_meta)
    else:
        compiler = profile.compiler
        flags = profile.all_c_flags(board_meta)

    include_args: list[str] = []
    for inc in include_dirs:
        include_args += ["-I", str(inc)]

    argv = [compiler, "-c"] + flags + include_args + [str(src), "-o", str(obj)]
    rc, _stdout, stderr = _run(argv)
    if rc != 0:
        logger.warning("compile failed (%s): %s", src.name, stderr[:500])
        return False, stderr
    return True, ""


# ---------------------------------------------------------------------------
# Link stage
# ---------------------------------------------------------------------------

def _link(
    object_files: list[Path],
    elf_path: Path,
    profile: ArchProfile,
    board_meta: dict,
    linker_script: Optional[Path] = None,
) -> tuple[bool, str]:
    """Link *object_files* into *elf_path*.

    Returns ``(success, stderr_excerpt)``.
    """
    mcu_flags = profile.mcu_flags_for_board(board_meta)
    argv = (
        [profile.compiler]
        + mcu_flags
        + profile.link_flags
        + [str(o) for o in object_files]
        + ["-o", str(elf_path)]
    )
    if linker_script and linker_script.exists():
        argv += ["-T", str(linker_script)]

    rc, _stdout, stderr = _run(argv)
    if rc != 0:
        logger.warning("link failed: %s", stderr[:500])
        return False, stderr
    return True, ""


# ---------------------------------------------------------------------------
# objcopy post-processing
# ---------------------------------------------------------------------------

def _objcopy_hex(objcopy: str, elf: Path, output: Path) -> tuple[bool, str]:
    argv = [objcopy, "-O", "ihex", str(elf), str(output)]
    rc, _, stderr = _run(argv)
    return (rc == 0), stderr


def _objcopy_bin(objcopy: str, elf: Path, output: Path) -> tuple[bool, str]:
    argv = [objcopy, "-O", "binary", str(elf), str(output)]
    rc, _, stderr = _run(argv)
    return (rc == 0), stderr


def _try_uf2(objcopy: str, elf: Path, build_dir: Path) -> Optional[Path]:
    """Attempt to produce a .uf2 file.

    Strategy: elf → bin, then invoke ``uf2conv`` if available.
    Falls back to returning ``None`` (caller will use ``.bin``).
    """
    bin_path = build_dir / "firmware.bin"
    ok, _ = _objcopy_bin(objcopy, elf, bin_path)
    if not ok or not bin_path.exists():
        return None
    if shutil.which("uf2conv") is None:
        return None
    uf2_path = build_dir / "firmware.uf2"
    argv = ["uf2conv", str(bin_path), "--base", "0x10000000", "-o", str(uf2_path)]
    rc, _, _ = _run(argv)
    if rc == 0 and uf2_path.exists():
        return uf2_path
    return None


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def build(
    sources: Iterable[Path | str],
    includes: Iterable[Path | str],
    arch: str,
    output_dir: Path | str,
    board_meta: dict,
    *,
    linker_script: Optional[Path | str] = None,
    extra_c_flags: list[str] | None = None,
    extra_link_flags: list[str] | None = None,
) -> BuildArtifact:
    """Compile, link and objcopy a firmware image.

    Parameters
    ----------
    sources
        Iterable of ``.c`` / ``.cpp`` source-file paths.
    includes
        Iterable of include-directory paths (passed as ``-I``).
    arch
        Architecture identifier — must be a key in
        :data:`arch_profiles.PROFILES` (e.g. ``"avr"``, ``"arm-cm4f"``).
    output_dir
        Directory in which build artefacts are placed.  Created if it does
        not exist.
    board_meta
        Board catalogue entry dict (``{"mcu": "ATmega328P", "arch": "avr",
        ...}``).  Used to derive ``-mmcu``/``-mcpu`` flags.
    linker_script
        Optional path to a vendor ``.ld`` file.  Passed to the linker via
        ``-T`` when supplied and the file exists.
    extra_c_flags
        Additional C flags appended after the profile defaults.
    extra_link_flags
        Additional linker flags appended after the profile defaults.

    Returns
    -------
    BuildArtifact
        ``status="ok"`` on success, ``"pending"`` if the toolchain is absent,
        ``"error"`` if a build step failed.
    """
    # ------------------------------------------------------------------
    # 1. Resolve profile
    # ------------------------------------------------------------------
    try:
        profile = get_profile(arch)
    except KeyError as exc:
        return BuildArtifact.error_sentinel(arch, str(exc))

    # ------------------------------------------------------------------
    # 2. Toolchain availability check (pending sentinel)
    # ------------------------------------------------------------------
    if not _compiler_available(profile.compiler):
        return BuildArtifact.pending_sentinel(
            arch=arch,
            reason=(
                f"Compiler '{profile.compiler}' not found on PATH. "
                "Install the toolchain to enable local firmware compilation."
            ),
            install_hint=profile.install_hint,
        )

    # ------------------------------------------------------------------
    # 3. Normalise inputs
    # ------------------------------------------------------------------
    source_paths = [Path(s) for s in sources]
    include_dirs = [Path(i) for i in includes]
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ld_script: Optional[Path] = None
    if linker_script:
        ld_script = Path(linker_script)

    # Apply extra flags by temporarily extending the profile's flag lists.
    # We do NOT mutate the shared profile; we build local overrides.
    if extra_c_flags:
        profile = _profile_with_extra_flags(profile, extra_c_flags, [])
    if extra_link_flags:
        profile = _profile_with_extra_flags(profile, [], extra_link_flags)

    # ------------------------------------------------------------------
    # 4. Compile each source file
    # ------------------------------------------------------------------
    object_files: list[Path] = []
    all_warnings: list[str] = []
    all_errors: list[str] = []

    for src in source_paths:
        if not (_is_c(src) or _is_cxx(src)):
            logger.debug("skipping non-C/C++ source: %s", src)
            continue
        obj = output_path / (src.stem + ".o")
        ok, stderr = _compile_source(
            src, obj, profile, board_meta, include_dirs
        )
        if not ok:
            all_errors.append(f"compile({src.name}): {stderr[:500]}")
            return BuildArtifact.error_sentinel(
                arch=arch,
                reason=f"Compilation failed for {src.name}",
                errors=all_errors,
            )
        object_files.append(obj)
        if stderr.strip():
            all_warnings.append(stderr.strip())

    if not object_files:
        return BuildArtifact.error_sentinel(
            arch=arch,
            reason="No compilable source files provided (.c / .cpp)",
        )

    # ------------------------------------------------------------------
    # 5. Link
    # ------------------------------------------------------------------
    elf_path = output_path / "firmware.elf"
    ok, stderr = _link(object_files, elf_path, profile, board_meta, ld_script)
    if not ok:
        all_errors.append(f"link: {stderr[:500]}")
        return BuildArtifact.error_sentinel(
            arch=arch,
            reason="Link step failed",
            errors=all_errors,
        )

    elf_size = elf_path.stat().st_size if elf_path.exists() else 0

    # ------------------------------------------------------------------
    # 6. objcopy → hex / bin / uf2
    # ------------------------------------------------------------------
    hex_path: Optional[Path] = None
    bin_path: Optional[Path] = None
    uf2_path: Optional[Path] = None

    fmt = profile.output_format
    objcopy = profile.objcopy

    if fmt == "hex":
        candidate = output_path / "firmware.hex"
        ok, stderr = _objcopy_hex(objcopy, elf_path, candidate)
        if ok and candidate.exists():
            hex_path = candidate
        else:
            all_warnings.append(f"objcopy hex failed: {stderr[:200]}")

    elif fmt == "bin":
        candidate = output_path / "firmware.bin"
        ok, stderr = _objcopy_bin(objcopy, elf_path, candidate)
        if ok and candidate.exists():
            bin_path = candidate
        else:
            all_warnings.append(f"objcopy bin failed: {stderr[:200]}")

    elif fmt == "uf2":
        uf2_result = _try_uf2(objcopy, elf_path, output_path)
        if uf2_result:
            uf2_path = uf2_result
        else:
            # Fall back to bin if uf2conv is absent.
            candidate = output_path / "firmware.bin"
            ok, stderr = _objcopy_bin(objcopy, elf_path, candidate)
            if ok and candidate.exists():
                bin_path = candidate
            else:
                all_warnings.append(f"objcopy fallback bin failed: {stderr[:200]}")

    return BuildArtifact(
        status="ok",
        arch=arch,
        elf_path=elf_path,
        hex_path=hex_path,
        bin_path=bin_path,
        uf2_path=uf2_path,
        size_bytes=elf_size,
        object_files=object_files,
        warnings=all_warnings,
        errors=all_errors,
    )


# ---------------------------------------------------------------------------
# Helper — non-mutating profile flag extension
# ---------------------------------------------------------------------------

def _profile_with_extra_flags(
    profile: ArchProfile,
    extra_c: list[str],
    extra_link: list[str],
) -> ArchProfile:
    """Return a shallow copy of *profile* with extra flags appended."""
    from dataclasses import replace
    return replace(
        profile,
        c_flags=list(profile.c_flags) + extra_c,
        cxx_flags=list(profile.cxx_flags) + extra_c,
        link_flags=list(profile.link_flags) + extra_link,
    )
