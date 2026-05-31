"""Firmware RAM utilisation auditor for ARM Cortex-M and AVR microcontrollers.

Given the four section sizes that a linker/compiler toolchain produces (.data,
.bss, heap reservation, stack reservation) plus the MCU's total SRAM, this
module computes static RAM allocation, free headroom, utilisation percentage,
and whether the design is within a conservative 80 % budget (10 % safety margin
on top of a 70 % soft ceiling).

Memory layout context
---------------------
ARM Cortex-M (RM0383 STM32F411 §2 — address map overview)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  SRAM base: 0x2000_0000, size: 128 KB (STM32F411xC/E)
  Typical linker layout (stack grows DOWN from SRAM top):

    SRAM top  ──────────────────────────────  <- _estack
              │        _stack (size=N)        │  grows ↓
              ├──────────────────────────────┤  <- stack bottom
              │       heap (size=M)           │  grows ↑
              ├──────────────────────────────┤
              │   .bss  (zero-inited globals) │
              ├──────────────────────────────┤
              │   .data (init'd globals VMA)  │
    SRAM base ──────────────────────────────  <- 0x2000_0000

  .data is copied from Flash by startup code.
  .bss is zeroed by startup code.
  heap_max_bytes = max expected dynamic allocation (user estimate).
  stack_max_bytes = worst-case stack depth (user estimate or linker reservation).

ATmega328P (§8 — SRAM organisation)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  Internal SRAM: 2 KB (0x0100 – 0x08FF, §8.3 Table 8-1).
  Data memory map:
    0x0000–0x001F  32 general-purpose registers
    0x0020–0x00FF  64 I/O registers
    0x0100–0x08FF  2048 B internal SRAM
  Linker layout (avr-libc, default):
    0x0100  .data (copied from Flash)
            .bss  (zeroed by __do_clear_bss)
    …
    0x08FF  _stack (grows DOWN from RAMEND)

  For both architectures this auditor treats the four provided section sizes as
  the complete SRAM footprint and checks total_used ≤ total_ram.

Budget rule
-----------
  80 % hard budget (10 % guard against interrupt stack spikes + malloc
  fragmentation). total_used ≤ 0.80 × total_ram_bytes → within_budget=True.

HONEST CAVEATS (always reported in RamUsageReport.honest_caveat)
----------------------------------------------------------------
1. STATIC ESTIMATE ONLY — this tool does not run the actual linker or
   arm-none-eabi-size.  Feed it the arm-none-eabi-size -A output values.
2. heap_max_bytes and stack_max_bytes are user-supplied ESTIMATES — the real
   heap watermark depends on malloc call patterns; the real stack peak depends
   on call depth and interrupt nesting.  Use a stack-painting / RTOS watermark
   probe on real hardware to validate.
3. Interrupt handlers consume additional stack on top of the declared
   stack_max_bytes.  On Cortex-M a single interrupt frame is 32 bytes (8
   registers × 4 B); nested interrupts multiply this.  Add at least
   N_irq_nest × 32 B to stack_max_bytes for a conservative estimate.
4. malloc fragmentation means the effective usable heap is smaller than
   heap_max_bytes.  For general-purpose allocators, budget 20–30 % metadata
   overhead.
5. FreeRTOS / Zephyr RTOS task stacks are NOT counted unless included in
   heap_max_bytes or stack_max_bytes by the caller.

References
----------
  RM0383 Rev 3 §2  — STM32F411xC/E memory map (SRAM @ 0x2000_0000, 128 KB).
  ATmega328P §8    — SRAM organisation (internal SRAM 2 KB, 0x0100–0x08FF).
"""
from __future__ import annotations

from dataclasses import dataclass


# ──────────────────────────────────────────────────────────────────────────────
# Budget constant
# ──────────────────────────────────────────────────────────────────────────────

#: Hard budget: total_used must not exceed this fraction of total_ram_bytes.
#: 80 % leaves 20 % headroom for interrupt frames, malloc metadata, and
#: runtime growth not captured by static estimates.
BUDGET_FRACTION: float = 0.80


# ──────────────────────────────────────────────────────────────────────────────
# Input dataclass
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class MemorySectionSizes:
    """Input specification for a firmware RAM audit.

    Attributes
    ----------
    data_bytes:
        Size of the .data section (initialised globals) as reported by
        ``arm-none-eabi-size -A`` or ``avr-size``.  This section is copied
        from Flash to SRAM at startup.
    bss_bytes:
        Size of the .bss section (zero-initialised globals / static locals).
        No Flash copy; the startup code zeroes this region.
    heap_max_bytes:
        Worst-case heap allocation estimate in bytes.  This is a user-supplied
        upper bound — if no dynamic allocation is used, pass 0.  For systems
        using ``malloc`` / ``pvPortMalloc``, estimate the peak allocated bytes
        from code review or Valgrind/heap-trace output.
    stack_max_bytes:
        Worst-case stack depth estimate in bytes.  For Cortex-M systems using
        the linker _stack section, pass the reserved _stack size.  For FreeRTOS,
        include the sum of all task stack sizes plus the main/ISR stack.
    total_ram_bytes:
        Total SRAM in bytes for the target MCU.
        Examples: STM32F411 → 128 × 1024 = 131072; ATmega328P → 2048.
    mcu_label:
        Human-readable MCU identifier, e.g. ``"STM32F411"`` or
        ``"ATmega328P"``.  Used in report text only; not validated.
    """
    data_bytes: int
    bss_bytes: int
    heap_max_bytes: int
    stack_max_bytes: int
    total_ram_bytes: int
    mcu_label: str

    def __post_init__(self) -> None:
        for field_name, value in [
            ("data_bytes", self.data_bytes),
            ("bss_bytes", self.bss_bytes),
            ("heap_max_bytes", self.heap_max_bytes),
            ("stack_max_bytes", self.stack_max_bytes),
            ("total_ram_bytes", self.total_ram_bytes),
        ]:
            if not isinstance(value, int):
                raise TypeError(f"{field_name} must be int, got {type(value).__name__}")
            if value < 0:
                raise ValueError(f"{field_name} must be >= 0, got {value}")
        if self.total_ram_bytes == 0:
            raise ValueError("total_ram_bytes must be > 0")


# ──────────────────────────────────────────────────────────────────────────────
# Output dataclass
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RamUsageReport:
    """Result of :func:`audit_ram_usage`.

    Attributes
    ----------
    static_alloc_bytes:
        Sum of .data + .bss (static allocations placed at link time).
    dynamic_alloc_bytes:
        Sum of heap_max_bytes + stack_max_bytes (runtime allocations).
    total_used_bytes:
        static_alloc_bytes + dynamic_alloc_bytes.
    free_bytes:
        total_ram_bytes − total_used_bytes.  Clamped to 0 if over-allocated.
    utilization_pct:
        total_used_bytes / total_ram_bytes × 100.  May exceed 100 % when
        over-allocated.
    within_budget:
        True iff total_used_bytes ≤ BUDGET_FRACTION × total_ram_bytes (80 %).
    recommendation:
        Short human-readable string indicating what to reduce if over budget.
    honest_caveat:
        Fixed caveat string reminding the caller that this is a static
        estimate and does not account for malloc fragmentation or
        interrupt-driven stack growth.
    """
    static_alloc_bytes: int
    dynamic_alloc_bytes: int
    total_used_bytes: int
    free_bytes: int
    utilization_pct: float
    within_budget: bool
    recommendation: str
    honest_caveat: str

    def as_dict(self) -> dict:
        return {
            "static_alloc_bytes": self.static_alloc_bytes,
            "dynamic_alloc_bytes": self.dynamic_alloc_bytes,
            "total_used_bytes": self.total_used_bytes,
            "free_bytes": self.free_bytes,
            "utilization_pct": round(self.utilization_pct, 2),
            "within_budget": self.within_budget,
            "recommendation": self.recommendation,
            "honest_caveat": self.honest_caveat,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Core audit function
# ──────────────────────────────────────────────────────────────────────────────

#: Honest caveat always attached to every report.
_HONEST_CAVEAT: str = (
    "STATIC ESTIMATE ONLY — does not account for: "
    "(1) malloc fragmentation (budget 20–30 % overhead for general-purpose allocators); "
    "(2) interrupt-driven stack growth (each Cortex-M interrupt frame = 32 B; "
    "nested ISRs multiply this — add N_irq_nest × 32 B to stack_max_bytes); "
    "(3) FreeRTOS / RTOS task stacks unless included in heap_max_bytes or "
    "stack_max_bytes; "
    "(4) linker alignment padding between sections. "
    "Validate stack peak with stack-painting (fill SRAM with 0xDEADBEEF and "
    "read watermark after stress test) or RTOS uxTaskGetStackHighWaterMark()."
)


def audit_ram_usage(sizes: MemorySectionSizes) -> RamUsageReport:
    """Audit firmware RAM utilisation and return a :class:`RamUsageReport`.

    Algorithm
    ---------
    * static_alloc_bytes = data_bytes + bss_bytes
    * dynamic_alloc_bytes = heap_max_bytes + stack_max_bytes
    * total_used_bytes = static_alloc_bytes + dynamic_alloc_bytes
    * free_bytes = max(0, total_ram_bytes − total_used_bytes)
    * utilization_pct = total_used_bytes / total_ram_bytes × 100
    * within_budget = total_used_bytes ≤ 0.80 × total_ram_bytes

    The 80 % budget (BUDGET_FRACTION) provides a 20 % guard band for:
      - Interrupt stack frames not captured by static stack_max_bytes.
      - malloc metadata / fragmentation overhead.
      - Runtime allocations post-init not visible to the linker.

    References
    ----------
    RM0383 Rev 3 §2  — STM32F411xC/E memory map.
    ATmega328P §8    — SRAM organisation (internal SRAM 2 KB).

    Parameters
    ----------
    sizes:
        :class:`MemorySectionSizes` instance describing the MCU and section
        sizes.

    Returns
    -------
    RamUsageReport
        Full audit report.
    """
    static_alloc = sizes.data_bytes + sizes.bss_bytes
    dynamic_alloc = sizes.heap_max_bytes + sizes.stack_max_bytes
    total_used = static_alloc + dynamic_alloc
    free_bytes = max(0, sizes.total_ram_bytes - total_used)
    utilization_pct = (total_used / sizes.total_ram_bytes) * 100.0
    budget_ceiling = sizes.total_ram_bytes * BUDGET_FRACTION
    within_budget = total_used <= budget_ceiling

    # Build recommendation
    if within_budget:
        if utilization_pct < 50.0:
            recommendation = (
                f"{sizes.mcu_label}: RAM utilisation {utilization_pct:.1f}% — "
                f"adequate headroom ({free_bytes:,} B free). "
                f"No action required."
            )
        else:
            recommendation = (
                f"{sizes.mcu_label}: RAM utilisation {utilization_pct:.1f}% — "
                f"within budget but approaching the 80% ceiling. "
                f"Monitor stack watermark on real hardware."
            )
    else:
        # Over budget — identify the largest contributor
        contributors = [
            ("stack (stack_max_bytes)", sizes.stack_max_bytes),
            ("heap (heap_max_bytes)", sizes.heap_max_bytes),
            (".bss (bss_bytes)", sizes.bss_bytes),
            (".data (data_bytes)", sizes.data_bytes),
        ]
        contributors_sorted = sorted(contributors, key=lambda t: t[1], reverse=True)
        largest_name, largest_val = contributors_sorted[0]
        second_name, second_val = contributors_sorted[1]
        overage = total_used - int(budget_ceiling)
        recommendation = (
            f"{sizes.mcu_label}: RAM over 80% budget by {overage:,} B "
            f"({utilization_pct:.1f}% used, {free_bytes:,} B free). "
            f"Largest contributor: {largest_name} = {largest_val:,} B. "
            f"Second: {second_name} = {second_val:,} B. "
            f"Options: reduce {largest_name.split()[0]} by shrinking buffers / "
            f"using smaller data types; use __attribute__((section(\".rodata\"))) "
            f"to move constant tables to Flash (.rodata); "
            f"decrease stack reservation if call depth analysis shows headroom; "
            f"replace dynamic allocation with static pools to eliminate heap."
        )

    return RamUsageReport(
        static_alloc_bytes=static_alloc,
        dynamic_alloc_bytes=dynamic_alloc,
        total_used_bytes=total_used,
        free_bytes=free_bytes,
        utilization_pct=utilization_pct,
        within_budget=within_budget,
        recommendation=recommendation,
        honest_caveat=_HONEST_CAVEAT,
    )
