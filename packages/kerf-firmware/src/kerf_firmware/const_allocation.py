"""Firmware const-allocation analyser for ARM Cortex-M and AVR microcontrollers.

Parses a GCC linker map symbol table (as a list of :class:`SymbolEntry` objects)
and reports how ``const``-qualified data is distributed across Flash and RAM
sections.  Helps identify wasteful placement of constant arrays in RAM
(.data) instead of Flash (.rodata) — a common mistake on tight MCUs such as
STM32F411 (512 KB Flash / 128 KB RAM) and ATmega328P (32 KB Flash / 2 KB RAM).

GCC linker-map section semantics
---------------------------------
  .text
      Executable code + ARM interworking veneer.  Read-only in Flash.
      ``const`` function-scope literals sometimes land here.

  .rodata
      Read-only data constants — ``const`` arrays, string literals, vtables.
      Stored in Flash; NOT copied to RAM at startup.  Cheapest placement for
      constants.

  .data
      Initialised global/static variables.  The *LMA* (load address) lives in
      Flash (one copy); the *VMA* (runtime address) lives in RAM.  The startup
      code (Reset_Handler / __do_copy_data) copies LMA → VMA at boot.
      Both Flash AND RAM are consumed.  A ``const`` global landing here is
      wasteful: it occupies RAM unnecessarily; GCC should move it to .rodata
      unless the linker script, compiler flags, or an explicit ``__attribute__``
      force it otherwise.

  .bss
      Zero-initialised (or uninitialised) globals.  RAM only — no Flash copy.
      ``const`` symbols should not appear here; their presence implies
      zero-init was somehow forced.

  .init_array / .ARM.exidx
      Constructor tables / ARM exception index.  Flash only.  Counted toward
      Flash totals but rarely contain user constants.

Heuristic for suspect constants in .data
-----------------------------------------
  GCC places a ``const`` global into .rodata by default.  When a symbol lands
  in .data instead it usually means one of:
    (a) The linker script has ``*(.rodata*)`` inside the ``RAM`` region (bug).
    (b) The symbol was decorated with ``__attribute__((section(".data")))``.
    (c) A non-trivial constructor / C++ global with a runtime initialiser.
    (d) PlatformIO / avr-libc legacy board scripts that pull .rodata into RAM.

  This module applies a **naming-convention heuristic**: symbols matching
  ``^_*[A-Z_]+$`` (i.e. all-uppercase, with optional leading underscores)
  are conventionally constants (``SENSOR_LUT``, ``CRC_TABLE``, ``__TABLE``).
  The top-10 such symbols found in .data are reported as :attr:`suspect_data_consts`.

  This is a heuristic only — the module does NOT parse C/C++ source or
  perform AST analysis.  A symbol named ``MAX_SPEED`` in .data could be a
  mutable global that happens to follow the naming convention; conversely, a
  ``const`` array named ``lookup`` would not be flagged.

HONEST CAVEATS
--------------
1. SYMBOL-TABLE HEURISTIC — does not parse C/C++ source or object-file
   DWARF debug info; const detection is based on section placement and
   naming convention only.
2. .data costs BOTH Flash (LMA copy) AND RAM (VMA runtime copy) — both
   data_init_bytes and flash contributions are doubled in reality but only
   the RAM side is reportable from the map alone.
3. ARM Thumb mode (.text size from map) may include literal pool entries
   that are effectively const data; they are reported under .text not .rodata.
4. Symbols < 4 bytes are excluded from suspect_data_consts to filter noise
   (single scalars rarely benefit from section migration).
5. Flash utilisation thresholds (80%) are conservative guidelines, not
   hard limits; the actual bootloader + vector table overhead is not modelled.

References
----------
  GCC Internals §18 — Section Placement.
  ARM IHI 0044F AAPCS §5.4 — Data Layout.
  RM0383 Rev 3 §3 — STM32F411xC/E memory map (512 KB Flash / 128 KB SRAM).
  ATmega328P §8   — SRAM organisation; §28 — Flash self-programming.
  avr-libc §Memory sections — avr-libc reference manual.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

#: Sections that live permanently in Flash (no RAM copy at runtime).
FLASH_ONLY_SECTIONS: frozenset[str] = frozenset(
    {".text", ".rodata", ".init_array", ".ARM.exidx"}
)

#: Sections whose runtime home is RAM.  .data also has a Flash LMA copy but
#: the VMA occupies RAM — we charge it to RAM for headroom analysis.
RAM_SECTIONS: frozenset[str] = frozenset({".data", ".bss"})

#: Budget fraction: warn when Flash exceeds this fraction of mcu_flash_kib.
FLASH_BUDGET_FRACTION: float = 0.80

#: Minimum size for a .data symbol to appear in suspect_data_consts.
_SUSPECT_MIN_BYTES: int = 4

#: Naming convention pattern for likely-constant symbols (ALL_CAPS with
#: optional leading underscores).
_CONST_NAME_RE: re.Pattern = re.compile(r"^_*[A-Z][A-Z0-9_]*$")

#: Maximum number of suspects / top consumers to report.
_TOP_N: int = 10


# ──────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SymbolEntry:
    """One symbol row from a GCC linker map or ``nm --print-size`` output.

    Attributes
    ----------
    name:
        Demangled symbol name, e.g. ``"g_lookup_table"``, ``"CRC_TABLE"``.
    section:
        ELF section the symbol was assigned to.  Recognised values:
        ``".text"``, ``".rodata"``, ``".data"``, ``".bss"``,
        ``".init_array"``, ``".ARM.exidx"``.
        Unknown sections are silently treated as Flash-resident.
    size_bytes:
        Symbol size in bytes as reported by the linker (column 4 of
        ``arm-none-eabi-nm -S -l --size-sort``).
    address_hex:
        Optional load address string, e.g. ``"0x08002c40"``.  Used for
        diagnostics only; not required for analysis.
    """
    name: str
    section: str
    size_bytes: int
    address_hex: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("SymbolEntry.name must be a non-empty string")
        if not isinstance(self.section, str) or not self.section:
            raise ValueError("SymbolEntry.section must be a non-empty string")
        if not isinstance(self.size_bytes, int):
            raise TypeError(
                f"SymbolEntry.size_bytes must be int, got {type(self.size_bytes).__name__}"
            )
        if self.size_bytes < 0:
            raise ValueError(f"SymbolEntry.size_bytes must be >= 0, got {self.size_bytes}")


@dataclass
class ConstAllocationReport:
    """Result of :func:`analyze_const_allocation`.

    Attributes
    ----------
    total_flash_bytes:
        Sum of all Flash-resident sections (.text + .rodata + .init_array +
        .ARM.exidx).
    total_ram_bytes:
        Sum of all RAM sections (.data + .bss).
    rodata_bytes:
        Bytes in .rodata — the preferred home for constants.
    data_init_bytes:
        Bytes in .data — initialised at startup from a Flash LMA copy.
        Constants placed here waste RAM unnecessarily.
    suspect_data_consts:
        Up to 10 symbol names in .data matching the ALL_CAPS naming
        convention (``^_*[A-Z][A-Z0-9_]*$``) and >= 4 bytes, sorted
        descending by size.  These are likely constants that should live
        in .rodata.  HEURISTIC — see module docstring.
    top_rodata_consumers:
        Up to 10 (name, size_bytes) pairs from .rodata, sorted descending
        by size.  Identifies large constant tables to review when flash is
        tight.
    recommendations:
        Human-readable optimisation suggestions derived from thresholds.
    honest_caveat:
        Fixed caveat string explaining the heuristic limitations.
    flash_utilization_pct:
        total_flash_bytes / (mcu_flash_kib × 1024) × 100.  Informational.
    ram_utilization_pct:
        total_ram_bytes / (mcu_ram_kib × 1024) × 100.  Informational.
    """
    total_flash_bytes: int
    total_ram_bytes: int
    rodata_bytes: int
    data_init_bytes: int
    suspect_data_consts: list[str]
    top_rodata_consumers: list[tuple[str, int]]
    recommendations: list[str]
    honest_caveat: str
    flash_utilization_pct: float = 0.0
    ram_utilization_pct: float = 0.0

    def as_dict(self) -> dict:
        return {
            "total_flash_bytes": self.total_flash_bytes,
            "total_ram_bytes": self.total_ram_bytes,
            "rodata_bytes": self.rodata_bytes,
            "data_init_bytes": self.data_init_bytes,
            "suspect_data_consts": self.suspect_data_consts,
            "top_rodata_consumers": [
                {"name": n, "size_bytes": s} for n, s in self.top_rodata_consumers
            ],
            "recommendations": self.recommendations,
            "honest_caveat": self.honest_caveat,
            "flash_utilization_pct": round(self.flash_utilization_pct, 2),
            "ram_utilization_pct": round(self.ram_utilization_pct, 2),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Honest caveat
# ──────────────────────────────────────────────────────────────────────────────

_HONEST_CAVEAT: str = (
    "HEURISTIC ANALYSIS ONLY — const detection is based on ELF section "
    "placement and symbol naming convention (ALL_CAPS pattern), NOT on "
    "C/C++ source AST or DWARF type information. "
    "(1) A symbol in .data named 'MAX_SPEED' may be a mutable global that "
    "happens to follow the naming convention; this tool will still flag it. "
    "(2) A const array named 'lookup' will NOT be detected as a suspect. "
    "(3) .data symbols consume both Flash (LMA) and RAM (VMA) — this report "
    "charges them to RAM only; the Flash LMA copy is an additional overhead "
    "not separately visible from the symbol map. "
    "(4) ARM Thumb literal pools in .text contain const data but are not "
    "included in rodata_bytes. "
    "(5) Flash utilisation threshold is a guideline — actual overhead from "
    "bootloader / vector table is not modelled. "
    "Run arm-none-eabi-objdump -h or avr-objdump -h on the final ELF for "
    "authoritative section sizes. "
    "Refs: GCC Internals §18; ARM IHI 0044F AAPCS §5.4; RM0383 Rev 3 §3; "
    "ATmega328P §8."
)


# ──────────────────────────────────────────────────────────────────────────────
# Core analysis function
# ──────────────────────────────────────────────────────────────────────────────

def analyze_const_allocation(
    symbols: Sequence[SymbolEntry],
    mcu_flash_kib: int = 512,
    mcu_ram_kib: int = 128,
) -> ConstAllocationReport:
    """Analyse const-qualifier allocation across Flash and RAM sections.

    Algorithm
    ---------
    1. Sum Flash sections: .text + .rodata + .init_array + .ARM.exidx.
    2. Sum RAM sections: .data + .bss.
    3. Compute rodata_bytes (Flash constants) and data_init_bytes (RAM copy).
    4. Flag .data symbols >= 4 bytes whose names match ``^_*[A-Z][A-Z0-9_]*$``
       as suspect_data_consts (top 10 by size).
    5. Identify top 10 .rodata symbols by size as top_rodata_consumers.
    6. Emit recommendations based on data_init_bytes threshold (> 1 KB) and
       Flash utilisation threshold (> 80%).

    Parameters
    ----------
    symbols:
        List of :class:`SymbolEntry` objects from the linker map.
    mcu_flash_kib:
        MCU Flash capacity in KiB.  Default 512 (STM32F411CE, RM0383 §3).
        Use 32 for ATmega328P.
    mcu_ram_kib:
        MCU SRAM capacity in KiB.  Default 128 (STM32F411, RM0383 §2).
        Use 2 for ATmega328P.

    Returns
    -------
    ConstAllocationReport
        Full allocation report.

    Raises
    ------
    TypeError
        If symbols is not iterable or mcu_flash_kib / mcu_ram_kib are not int.
    ValueError
        If mcu_flash_kib or mcu_ram_kib are <= 0.
    """
    if not isinstance(mcu_flash_kib, int):
        raise TypeError(
            f"mcu_flash_kib must be int, got {type(mcu_flash_kib).__name__}"
        )
    if not isinstance(mcu_ram_kib, int):
        raise TypeError(
            f"mcu_ram_kib must be int, got {type(mcu_ram_kib).__name__}"
        )
    if mcu_flash_kib <= 0:
        raise ValueError(f"mcu_flash_kib must be > 0, got {mcu_flash_kib}")
    if mcu_ram_kib <= 0:
        raise ValueError(f"mcu_ram_kib must be > 0, got {mcu_ram_kib}")

    mcu_flash_bytes = mcu_flash_kib * 1024
    mcu_ram_bytes = mcu_ram_kib * 1024

    # Accumulators by section
    section_totals: dict[str, int] = {}
    # Symbols per section for detailed analysis
    data_symbols: list[tuple[str, int]] = []   # (name, size)
    rodata_symbols: list[tuple[str, int]] = []  # (name, size)

    for sym in symbols:
        section_totals[sym.section] = (
            section_totals.get(sym.section, 0) + sym.size_bytes
        )
        if sym.section == ".data":
            data_symbols.append((sym.name, sym.size_bytes))
        elif sym.section == ".rodata":
            rodata_symbols.append((sym.name, sym.size_bytes))

    # Flash total: all flash-only sections
    total_flash_bytes = sum(
        section_totals.get(s, 0) for s in FLASH_ONLY_SECTIONS
    )
    # RAM total: .data + .bss
    total_ram_bytes = sum(
        section_totals.get(s, 0) for s in RAM_SECTIONS
    )

    rodata_bytes = section_totals.get(".rodata", 0)
    data_init_bytes = section_totals.get(".data", 0)

    # Suspect constants: .data symbols with ALL_CAPS name and size >= threshold
    suspect_candidates = [
        (name, size)
        for name, size in data_symbols
        if size >= _SUSPECT_MIN_BYTES and _CONST_NAME_RE.match(name)
    ]
    suspect_candidates.sort(key=lambda t: t[1], reverse=True)
    suspect_data_consts = [name for name, _ in suspect_candidates[:_TOP_N]]

    # Top rodata consumers
    rodata_symbols.sort(key=lambda t: t[1], reverse=True)
    top_rodata_consumers: list[tuple[str, int]] = rodata_symbols[:_TOP_N]

    # Utilisation
    flash_utilization_pct = (total_flash_bytes / mcu_flash_bytes) * 100.0
    ram_utilization_pct = (total_ram_bytes / mcu_ram_bytes) * 100.0

    # Recommendations
    recommendations: list[str] = []

    if data_init_bytes > 1024:
        recommendations.append(
            f"move large `const` arrays from RAM to flash via const-qualifier: "
            f"{data_init_bytes:,} B found in .data (initialised RAM section) "
            f"— confirm symbols are declared `const` and add "
            f"`__attribute__((section(\".rodata\")))` if GCC still places them "
            f"in .data; or pass -fdata-sections + --gc-sections and verify "
            f"linker script places .rodata in FLASH region."
        )

    if flash_utilization_pct > FLASH_BUDGET_FRACTION * 100:
        recommendations.append(
            f"enable -Os: flash utilisation is {flash_utilization_pct:.1f}% "
            f"({total_flash_bytes:,} / {mcu_flash_bytes:,} B) — "
            f"exceeds 80% guideline; compile with -Os (optimize for size) and "
            f"consider -ffunction-sections -fdata-sections + --gc-sections to "
            f"strip unused code and data."
        )

    if not recommendations:
        recommendations.append(
            "No immediate const-allocation issues detected. "
            f"Flash: {flash_utilization_pct:.1f}%, "
            f"RAM: {ram_utilization_pct:.1f}%, "
            f"data_init_bytes: {data_init_bytes:,} B (within 1 KB threshold)."
        )

    return ConstAllocationReport(
        total_flash_bytes=total_flash_bytes,
        total_ram_bytes=total_ram_bytes,
        rodata_bytes=rodata_bytes,
        data_init_bytes=data_init_bytes,
        suspect_data_consts=suspect_data_consts,
        top_rodata_consumers=top_rodata_consumers,
        recommendations=recommendations,
        honest_caveat=_HONEST_CAVEAT,
        flash_utilization_pct=flash_utilization_pct,
        ram_utilization_pct=ram_utilization_pct,
    )
