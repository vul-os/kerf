"""Cortex-M firmware memory-layout verifier for STM32 microcontrollers.

Verifies that linker-script section sizes fit within the chip's physical Flash and
SRAM regions, that the stack fits inside SRAM without overflowing into the heap, and
that the vector-table placement and ISR count are consistent with the chip's NVIC.

Violation classes
-----------------
1. **FLASH_OVERFLOW** — sum of all Flash sections (.text + .rodata + .data LMA copy +
   .ARM.extab + .ARM.exidx + ...) exceeds the chip's Flash size.
   Source: RM0383 §3 (STM32F411: 512 KB Flash @ 0x0800_0000).

2. **SRAM_OVERFLOW** — sum of all SRAM-resident sections (.data VMA + .bss + _stack) +
   heap exceeds the chip's SRAM size.
   Source: RM0383 §3 (STM32F411: 128 KB SRAM @ 0x2000_0000).

3. **STACK_OVERFLOW_INTO_BSS** — stack top (stack start + stack size) reaches into or
   past the end of the .bss section, meaning a stack growth event could corrupt .bss
   data.  Detected when stack_end > sram_end − bss_size (approximate; conservative).

4. **VECTOR_TABLE_MISPLACED** — the declared vector-table base address is not at the
   start of Flash (0x0800_0000 default) and no VTOR remapping flag is supplied.
   ARM Cortex-M UG (ARM DUI 0553B) §B3.2.4: SCB->VTOR must be written if the vector
   table is relocated.  We do not model VTOR writes but warn when the address deviates.

5. **ISR_COUNT_MISMATCH** — number of entries in the user-provided vector table does not
   match the chip's NVIC IRQ count (from interrupt_specs).  STM32F411: 62 maskable IRQs
   + 16 Cortex-M system exceptions = 78 entries total.  Extra entries are waste; fewer
   entries leave exception vectors unhandled.

HONEST DISCLAIMER
-----------------
STATIC SECTION-SIZE CHECK ONLY.  This tool does NOT:
  * Run the actual ARM linker (arm-none-eabi-ld / lld).
  * Validate linker-script symbol expressions (ALIGN, KEEP, ENTRY, OVERLAY).
  * Trace actual LMA→VMA copy by the startup code.
  * Model runtime stack growth beyond the declared _stack section.
  * Check CCMRAM, ITCM, DTCM, or backup-SRAM regions.
  * Verify cache / MPU region constraints.
Use arm-none-eabi-size + a map-file parser for production audits.

Supported chips
---------------
  "STM32F411"  (aliases: stm32f411ce, stm32f411re, stm32f411ve)
  "STM32F407"  (aliases: stm32f407vg, stm32f407ig)

STM32F411 memory regions (RM0383 §3)
--------------------------------------
  Flash : 512 KB  @ 0x0800_0000 – 0x0807_FFFF
  SRAM  : 128 KB  @ 0x2000_0000 – 0x2001_FFFF

STM32F407 memory regions (RM0090 §3)
--------------------------------------
  Flash : 1024 KB @ 0x0800_0000 – 0x080F_FFFF
  SRAM1 : 112 KB  @ 0x2000_0000 – 0x2001_BFFF   (modelled as SRAM here)
  SRAM2 :  16 KB  @ 0x2001_C000 – 0x2001_FFFF   (included in 128 KB total)
  Total SRAM = 128 KB

References
----------
  RM0383 Rev 3 §3          — STM32F411xC/E memory map.
  RM0090 Rev 19 §3         — STM32F407/417 memory map.
  ARM Cortex-M Generic User Guide (ARM DUI 0553B) §B3.2.4 — SCB->VTOR.
  ARM Cortex-M Generic User Guide §B1.3.2                 — System exception table.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ──────────────────────────────────────────────────────────────────────────────
# Chip memory region database
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChipMemorySpec:
    """Physical memory regions for one chip family.

    Attributes
    ----------
    chip_id:
        Canonical chip identifier, e.g. ``"STM32F411"``.
    flash_start:
        First byte of Flash, e.g. ``0x0800_0000``.
    flash_size:
        Flash size in bytes.
    sram_start:
        First byte of SRAM, e.g. ``0x2000_0000``.
    sram_size:
        SRAM size in bytes.
    nvic_irq_count:
        Number of maskable (peripheral) IRQs as listed in the datasheet.
        The total vector table size = nvic_irq_count + 16 Cortex-M system
        exceptions (ARM Cortex-M Generic UG §B1.3.2).
    cortex_m_exceptions:
        Number of system exception slots (always 16 for Cortex-M).
    """
    chip_id: str
    flash_start: int
    flash_size: int
    sram_start: int
    sram_size: int
    nvic_irq_count: int
    cortex_m_exceptions: int = 16

    @property
    def flash_end(self) -> int:
        """Exclusive end address of Flash."""
        return self.flash_start + self.flash_size

    @property
    def sram_end(self) -> int:
        """Exclusive end address of SRAM."""
        return self.sram_start + self.sram_size

    @property
    def total_vector_entries(self) -> int:
        """Total number of vector table entries (system exceptions + IRQs)."""
        return self.cortex_m_exceptions + self.nvic_irq_count


# STM32F411xC/E — RM0383 §3 + RM0383 §10 (62 maskable IRQs)
STM32F411_MEM = ChipMemorySpec(
    chip_id="STM32F411",
    flash_start=0x08000000,
    flash_size=512 * 1024,       # 512 KB
    sram_start=0x20000000,
    sram_size=128 * 1024,        # 128 KB
    nvic_irq_count=62,
)

# STM32F407/417 — RM0090 §3 + RM0090 §10 (82 maskable IRQs)
STM32F407_MEM = ChipMemorySpec(
    chip_id="STM32F407",
    flash_start=0x08000000,
    flash_size=1024 * 1024,      # 1024 KB
    sram_start=0x20000000,
    sram_size=128 * 1024,        # 128 KB (SRAM1 112 KB + SRAM2 16 KB)
    nvic_irq_count=82,
)

_MEM_REGISTRY: dict[str, ChipMemorySpec] = {
    "stm32f411":    STM32F411_MEM,
    "stm32f411ce":  STM32F411_MEM,
    "stm32f411re":  STM32F411_MEM,
    "stm32f411ve":  STM32F411_MEM,
    "stm32f407":    STM32F407_MEM,
    "stm32f407vg":  STM32F407_MEM,
    "stm32f407ig":  STM32F407_MEM,
    "stm32f417":    STM32F407_MEM,
    "stm32f417vg":  STM32F407_MEM,
}


def get_memory_spec(chip_id: str) -> ChipMemorySpec:
    """Return :class:`ChipMemorySpec` for *chip_id* (case-insensitive).

    Raises :exc:`KeyError` for unknown chips.
    """
    key = chip_id.lower().replace("-", "_").replace(" ", "_")
    if key in _MEM_REGISTRY:
        return _MEM_REGISTRY[key]
    known = sorted({v.chip_id for v in _MEM_REGISTRY.values()})
    raise KeyError(f"Unknown chip: {chip_id!r}.  Known: {known}")


def list_memory_chip_ids() -> list[str]:
    """Return canonical chip IDs with memory specs."""
    return sorted({v.chip_id for v in _MEM_REGISTRY.values()})


# ──────────────────────────────────────────────────────────────────────────────
# Public input / output data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class LinkerSection:
    """One linker-script output section.

    Attributes
    ----------
    name:
        Section name, e.g. ``".text"``, ``".data"``, ``".bss"``, ``"_stack"``.
    size:
        Section size in bytes.
    region:
        Memory region: ``"flash"`` or ``"sram"``.
        Use ``"flash"`` for sections that live in Flash (LMA) even if they are
        copied to SRAM at startup (i.e. .data initialisation image in Flash).
        Use ``"sram"`` for sections resident in SRAM at runtime (.data VMA,
        .bss, _stack, heap).
    lma_size:
        Bytes consumed at the Flash LMA (load-memory address).  Usually equals
        *size* for flash sections; equals *size* for .data (the initialisation
        copy lives in Flash); equals 0 for .bss and _stack (no Flash copy).
        If ``None``, inferred as *size* for flash region and ``0`` for .bss /
        _stack sections when region == "sram".
    is_stack:
        True if this section represents the initial stack allocation (i.e. the
        region the startup code sets SP to top-of).
    is_bss:
        True if this section is zero-initialised (no Flash copy; LMA size = 0).
    is_heap:
        True if this section is the heap.
    """
    name: str
    size: int
    region: str          # "flash" | "sram"
    lma_size: Optional[int] = None
    is_stack: bool = False
    is_bss: bool = False
    is_heap: bool = False

    def __post_init__(self):
        if self.region not in ("flash", "sram"):
            raise ValueError(f"region must be 'flash' or 'sram', got {self.region!r}")
        if self.lma_size is None:
            # Default: .bss and _stack have no Flash copy; everything else does
            if self.is_bss or self.is_stack:
                self.lma_size = 0
            else:
                self.lma_size = self.size


@dataclass
class MemoryViolation:
    """A single memory-layout violation.

    Attributes
    ----------
    kind:
        Violation code.  One of:
        ``"FLASH_OVERFLOW"``         — Flash sections exceed chip Flash size.
        ``"SRAM_OVERFLOW"``          — SRAM sections exceed chip SRAM size.
        ``"STACK_OVERFLOW_INTO_BSS"`` — stack top reaches into .bss region.
        ``"VECTOR_TABLE_MISPLACED"`` — vector table not at Flash start.
        ``"ISR_COUNT_MISMATCH"``     — vector table entry count != chip NVIC.
    detail:
        Human-readable explanation.
    used_bytes:
        Bytes consumed (relevant region), if applicable.
    available_bytes:
        Region capacity, if applicable.
    suggestion:
        Remediation advice.
    """
    kind: str
    detail: str
    used_bytes: int = 0
    available_bytes: int = 0
    suggestion: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "used_bytes": self.used_bytes,
            "available_bytes": self.available_bytes,
            "suggestion": self.suggestion,
        }


@dataclass
class MemoryMapReport:
    """Result of :func:`verify_memory_layout`.

    Attributes
    ----------
    ok:
        True iff no violations were found.
    chip:
        Canonical chip identifier.
    flash_used:
        Total Flash bytes consumed by the layout.
    flash_available:
        Chip Flash capacity.
    flash_free_pct:
        Percentage of Flash free (0.0 – 100.0).
    sram_used:
        Total SRAM bytes consumed (runtime sections).
    sram_available:
        Chip SRAM capacity.
    sram_free_pct:
        Percentage of SRAM free.
    violations:
        List of :class:`MemoryViolation` objects.
    notes:
        Advisory notes.
    """
    ok: bool
    chip: str
    flash_used: int
    flash_available: int
    flash_free_pct: float
    sram_used: int
    sram_available: int
    sram_free_pct: float
    violations: List[MemoryViolation]
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "chip": self.chip,
            "flash_used": self.flash_used,
            "flash_available": self.flash_available,
            "flash_free_pct": round(self.flash_free_pct, 1),
            "sram_used": self.sram_used,
            "sram_available": self.sram_available,
            "sram_free_pct": round(self.sram_free_pct, 1),
            "violations": [v.as_dict() for v in self.violations],
            "notes": self.notes,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Core verifier
# ──────────────────────────────────────────────────────────────────────────────

def verify_memory_layout(
    chip: str | ChipMemorySpec,
    sections: Sequence[LinkerSection],
    *,
    vector_table_addr: Optional[int] = None,
    isr_vector_count: Optional[int] = None,
) -> MemoryMapReport:
    """Verify that linker sections fit within the chip's physical memory regions.

    Parameters
    ----------
    chip:
        Chip family string (e.g. ``"STM32F411"``, ``"stm32f411ce"``,
        ``"STM32F407"``) or a :class:`ChipMemorySpec` instance.
    sections:
        Sequence of :class:`LinkerSection` objects describing all output
        sections from the linker map.  Each section must declare its *region*
        (``"flash"`` or ``"sram"``) and *size*.

        Flash usage = sum of ``lma_size`` for ALL sections (the initialisation
        image of .data lives in Flash, plus .text, .rodata, etc.).

        SRAM usage = sum of ``size`` for all ``region == "sram"`` sections
        (.data VMA runtime copy + .bss zero region + _stack + heap).

    vector_table_addr:
        Optional.  Base address of the vector table.  Defaults to
        ``chip.flash_start`` (0x0800_0000 for STM32).  If provided and it
        differs from Flash start, a ``VECTOR_TABLE_MISPLACED`` violation is
        raised unless the address is in SRAM (VTOR remapping to 0x2000_0000
        is valid but must be explicit).
        (ARM Cortex-M Generic UG §B3.2.4)

    isr_vector_count:
        Optional.  Total number of entries in the application's vector table
        (including the initial SP and all exception + IRQ handlers).  If
        provided, compared against ``chip.total_vector_entries``; a mismatch
        raises ``ISR_COUNT_MISMATCH``.

    Returns
    -------
    MemoryMapReport
        Full report with utilisation figures and all violations.

    Violation rules
    ---------------
    1. **FLASH_OVERFLOW** — total LMA Flash bytes > chip.flash_size.
    2. **SRAM_OVERFLOW** — total SRAM runtime bytes > chip.sram_size.
    3. **STACK_OVERFLOW_INTO_BSS** — estimated stack top encroaches on .bss.
    4. **VECTOR_TABLE_MISPLACED** — vector_table_addr not at flash_start and
       not explicitly in SRAM (VTOR remap).
    5. **ISR_COUNT_MISMATCH** — isr_vector_count != chip.total_vector_entries.

    Usage example (STM32F411, valid layout)
    ----------------------------------------
    >>> spec = get_memory_spec("STM32F411")
    >>> sects = [
    ...     LinkerSection(".text",  70*1024, "flash"),
    ...     LinkerSection(".data",   8*1024, "sram", lma_size=8*1024),
    ...     LinkerSection(".bss",    4*1024, "sram", lma_size=0, is_bss=True),
    ...     LinkerSection("_stack",  4*1024, "sram", lma_size=0, is_stack=True),
    ... ]
    >>> report = verify_memory_layout(spec, sects)
    >>> report.ok
    True
    >>> report.sram_free_pct   # 16 KB used of 128 KB
    87.5

    References
    ----------
    RM0383 Rev 3 §3      — STM32F411xC/E memory map (Flash + SRAM addresses).
    RM0090 Rev 19 §3     — STM32F407/417 memory map.
    ARM Cortex-M Generic User Guide (ARM DUI 0553B) §B3.2.4 — SCB->VTOR.
    ARM Cortex-M Generic User Guide §B1.3.2              — System exception table.
    """
    if isinstance(chip, str):
        mem: ChipMemorySpec = get_memory_spec(chip)
    else:
        mem = chip

    violations: list[MemoryViolation] = []
    notes: list[str] = []

    # ── Tally Flash LMA usage ─────────────────────────────────────────────────
    # Every section contributes its lma_size to Flash (even SRAM sections whose
    # initialisation image is stored in Flash, e.g. .data).  .bss and _stack
    # have lma_size=0 (no Flash copy).
    flash_used = sum(s.lma_size for s in sections if s.lma_size is not None)
    # Also count pure Flash sections directly
    flash_pure = sum(s.size for s in sections if s.region == "flash")
    # Use whichever accounting is larger (belt-and-suspenders; typically equal
    # when the caller sets lma_size correctly).
    flash_total = max(flash_used, flash_pure)

    # ── Tally SRAM runtime usage ──────────────────────────────────────────────
    sram_total = sum(s.size for s in sections if s.region == "sram")

    flash_free_pct = max(0.0, (mem.flash_size - flash_total) / mem.flash_size * 100)
    sram_free_pct = max(0.0, (mem.sram_size - sram_total) / mem.sram_size * 100)

    # ── 1. FLASH_OVERFLOW ────────────────────────────────────────────────────
    if flash_total > mem.flash_size:
        overflow = flash_total - mem.flash_size
        violations.append(MemoryViolation(
            kind="FLASH_OVERFLOW",
            detail=(
                f"Flash sections total {flash_total:,} B ({flash_total // 1024} KB) "
                f"which exceeds the {mem.chip_id} Flash capacity of "
                f"{mem.flash_size:,} B ({mem.flash_size // 1024} KB) by "
                f"{overflow:,} B ({overflow // 1024} KB). "
                f"(RM0383 §3 — {mem.chip_id} Flash: {mem.flash_size // 1024} KB "
                f"@ 0x{mem.flash_start:08X})"
            ),
            used_bytes=flash_total,
            available_bytes=mem.flash_size,
            suggestion=(
                "Enable -Os / LTO in your build system. "
                "Audit large .rodata tables. "
                "Consider moving constant data to external QSPI Flash. "
                f"Remaining unused space: 0 B (overflowed by {overflow:,} B)."
            ),
        ))

    # ── 2. SRAM_OVERFLOW ─────────────────────────────────────────────────────
    if sram_total > mem.sram_size:
        overflow = sram_total - mem.sram_size
        violations.append(MemoryViolation(
            kind="SRAM_OVERFLOW",
            detail=(
                f"SRAM sections total {sram_total:,} B ({sram_total // 1024} KB) "
                f"which exceeds the {mem.chip_id} SRAM capacity of "
                f"{mem.sram_size:,} B ({mem.sram_size // 1024} KB) by "
                f"{overflow:,} B ({overflow // 1024} KB). "
                f"(RM0383 §3 — {mem.chip_id} SRAM: {mem.sram_size // 1024} KB "
                f"@ 0x{mem.sram_start:08X})"
            ),
            used_bytes=sram_total,
            available_bytes=mem.sram_size,
            suggestion=(
                "Reduce .bss / .data: move large buffers to Flash (const). "
                "Decrease stack size if oversized (typical embedded stack: 1–4 KB). "
                "Use heap pooling instead of static allocations. "
                f"Overflowed by {overflow:,} B."
            ),
        ))

    # ── 3. STACK_OVERFLOW_INTO_BSS ────────────────────────────────────────────
    # Conservative model: on most Cortex-M linker scripts the stack grows DOWN
    # from SRAM top, and .bss + .data sit at the bottom.  A stack that is
    # larger than (sram_size - bss_size - data_size) will overlap .bss on
    # stack overflow.
    #
    # We detect the degenerate static case where the declared sizes already
    # imply the stack region touches or overlaps .bss without any runtime
    # growth — i.e. the combined footprint leaves no guard gap.
    bss_size = sum(s.size for s in sections if s.is_bss)
    stack_size = sum(s.size for s in sections if s.is_stack)
    data_size = sum(
        s.size for s in sections
        if s.region == "sram" and not s.is_bss and not s.is_stack and not s.is_heap
    )

    if stack_size > 0 and bss_size > 0:
        # Remaining SRAM after .data + .bss
        remaining_for_stack = mem.sram_size - data_size - bss_size
        if stack_size > remaining_for_stack:
            over = stack_size - remaining_for_stack
            violations.append(MemoryViolation(
                kind="STACK_OVERFLOW_INTO_BSS",
                detail=(
                    f"Stack ({stack_size:,} B) + .data ({data_size:,} B) + "
                    f".bss ({bss_size:,} B) = "
                    f"{stack_size + data_size + bss_size:,} B, which exceeds "
                    f"SRAM size ({mem.sram_size:,} B) by {over:,} B. "
                    f"On a stack-grows-down layout the stack top would collide "
                    f"with .bss, causing silent .bss corruption on the first "
                    f"stack overflow event."
                ),
                used_bytes=stack_size + data_size + bss_size,
                available_bytes=mem.sram_size,
                suggestion=(
                    "Reduce stack size (current: "
                    f"{stack_size // 1024} KB). "
                    "Typical Cortex-M bare-metal minimum: 512 B – 1 KB; "
                    "FreeRTOS tasks get their own stacks so the primary stack "
                    "can be smaller. "
                    "Add a stack-overflow hook or MPU guard region."
                ),
            ))

    # ── 4. VECTOR_TABLE_MISPLACED ─────────────────────────────────────────────
    if vector_table_addr is not None:
        vtor = vector_table_addr
        at_flash_start = (vtor == mem.flash_start)
        at_sram_start = (mem.sram_start <= vtor < mem.sram_end)
        if not at_flash_start and not at_sram_start:
            violations.append(MemoryViolation(
                kind="VECTOR_TABLE_MISPLACED",
                detail=(
                    f"Vector table address 0x{vtor:08X} is neither at the "
                    f"{mem.chip_id} Flash start (0x{mem.flash_start:08X}) "
                    f"nor in SRAM (0x{mem.sram_start:08X}–0x{mem.sram_end - 1:08X}). "
                    f"SCB->VTOR must be written to the actual vector table "
                    f"address before any interrupt can be handled. "
                    f"(ARM Cortex-M Generic UG §B3.2.4)"
                ),
                suggestion=(
                    "Set vector_table_addr to 0x{:08X} (Flash start) for "
                    "the default layout, or to a SRAM address if using "
                    "SCB->VTOR remapping (ensure 512-byte alignment per §B3.2.4).".format(
                        mem.flash_start
                    )
                ),
            ))
        elif at_sram_start and vtor != mem.sram_start:
            notes.append(
                f"Vector table at 0x{vtor:08X} is in SRAM (VTOR remapped). "
                f"Ensure SCB->VTOR is written before the first interrupt fires and "
                f"that the address is 512-byte aligned (ARM Cortex-M Generic UG §B3.2.4)."
            )
        elif at_flash_start:
            notes.append(
                f"Vector table at Flash start 0x{vtor:08X} — default Cortex-M layout."
            )

    # ── 5. ISR_COUNT_MISMATCH ────────────────────────────────────────────────
    if isr_vector_count is not None:
        expected = mem.total_vector_entries
        if isr_vector_count != expected:
            diff = isr_vector_count - expected
            qualifier = "extra" if diff > 0 else "missing"
            violations.append(MemoryViolation(
                kind="ISR_COUNT_MISMATCH",
                detail=(
                    f"Vector table has {isr_vector_count} entries but "
                    f"{mem.chip_id} expects {expected} "
                    f"({mem.cortex_m_exceptions} Cortex-M system exceptions + "
                    f"{mem.nvic_irq_count} peripheral IRQs per RM0383 §10). "
                    f"There are {abs(diff)} {qualifier} entries."
                ),
                used_bytes=isr_vector_count,
                available_bytes=expected,
                suggestion=(
                    "Use the ST-provided startup_stm32f411xe.s (or equivalent) "
                    "vector table as a reference. "
                    f"Expected total: {expected} entries "
                    f"({mem.cortex_m_exceptions} system + {mem.nvic_irq_count} IRQs)."
                ),
            ))

    # ── Advisory notes ────────────────────────────────────────────────────────
    notes.append(
        f"{mem.chip_id} Flash: {flash_total:,} B used / "
        f"{mem.flash_size:,} B total "
        f"({100 - flash_free_pct:.1f}% used, {flash_free_pct:.1f}% free). "
        f"RM0383 §3: Flash @ 0x{mem.flash_start:08X}."
    )
    notes.append(
        f"{mem.chip_id} SRAM: {sram_total:,} B used / "
        f"{mem.sram_size:,} B total "
        f"({100 - sram_free_pct:.1f}% used, {sram_free_pct:.1f}% free). "
        f"RM0383 §3: SRAM @ 0x{mem.sram_start:08X}."
    )
    notes.append(
        "STATIC SECTION-SIZE CHECK ONLY — does not run the linker; "
        "use arm-none-eabi-size + map-file for production audits."
    )

    return MemoryMapReport(
        ok=len(violations) == 0,
        chip=mem.chip_id,
        flash_used=flash_total,
        flash_available=mem.flash_size,
        flash_free_pct=flash_free_pct,
        sram_used=sram_total,
        sram_available=mem.sram_size,
        sram_free_pct=sram_free_pct,
        violations=violations,
        notes=notes,
    )
