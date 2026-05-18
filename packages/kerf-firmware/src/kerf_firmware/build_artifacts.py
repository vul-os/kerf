"""
Build artifact dataclasses for the gcc orchestrator.

``BuildArtifact`` captures every output path produced by a compile+link+objcopy
run together with build metadata.  When the toolchain is absent the orchestrator
returns a *pending* sentinel encoded as a ``BuildArtifact`` with
``status="pending"`` and ``elf_path=None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class BuildArtifact:
    """Result of a single gcc orchestrator build run.

    Fields
    ------
    status
        ``"ok"`` — build succeeded and all requested artefact paths are set.
        ``"pending"`` — toolchain not on PATH; no compilation attempted.
        ``"error"`` — build was attempted but failed.
    arch
        Architecture identifier string, e.g. ``"avr"``, ``"arm-cm4f"``.
    elf_path
        Path to the linked ELF file, or ``None`` when the build did not reach
        the link stage.
    hex_path
        Path to the Intel-HEX file produced by ``objcopy``, or ``None``.
    bin_path
        Path to the raw binary file produced by ``objcopy``, or ``None``.
    uf2_path
        Path to the UF2 drag-and-drop firmware image, or ``None``.
    size_bytes
        Size of the primary artefact in bytes (``elf_path`` when present),
        or ``0`` when the build did not succeed.
    reason
        Human-readable string explaining a ``"pending"`` or ``"error"``
        condition.  Empty for successful builds.
    install_hint
        Optional install command the user can run to obtain the missing
        toolchain (e.g. ``"brew install avr-gcc"``).
    object_files
        List of ``.o`` files produced during compilation, kept for
        incremental-build support.
    warnings
        Compiler / linker warning lines captured from stderr.
    errors
        Compiler / linker error lines captured from stderr.
    """

    status: str  # "ok" | "pending" | "error"
    arch: str

    elf_path: Optional[Path] = None
    hex_path: Optional[Path] = None
    bin_path: Optional[Path] = None
    uf2_path: Optional[Path] = None

    size_bytes: int = 0
    reason: str = ""
    install_hint: str = ""

    object_files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def ok(self) -> bool:
        """``True`` when status is ``"ok"``."""
        return self.status == "ok"

    @property
    def pending(self) -> bool:
        """``True`` when the toolchain was absent (status is ``"pending"``)."""
        return self.status == "pending"

    def primary_path(self) -> Optional[Path]:
        """Return the most useful single artefact path (hex > bin > uf2 > elf)."""
        for p in (self.hex_path, self.bin_path, self.uf2_path, self.elf_path):
            if p is not None:
                return p
        return None

    # ------------------------------------------------------------------
    # Sentinel constructors
    # ------------------------------------------------------------------

    @classmethod
    def pending_sentinel(
        cls,
        arch: str,
        reason: str,
        install_hint: str = "",
    ) -> "BuildArtifact":
        """Return a ``status="pending"`` sentinel without running any build."""
        return cls(
            status="pending",
            arch=arch,
            reason=reason,
            install_hint=install_hint,
        )

    @classmethod
    def error_sentinel(
        cls,
        arch: str,
        reason: str,
        errors: list[str] | None = None,
    ) -> "BuildArtifact":
        """Return a ``status="error"`` sentinel."""
        return cls(
            status="error",
            arch=arch,
            reason=reason,
            errors=errors or [],
        )
