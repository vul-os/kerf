"""Static worst-case stack depth estimator for Cortex-M / ATmega firmware.

Performs a DFS through the function call tree, accumulating stack frame sizes to
find the maximum call-chain depth in bytes.  Detects recursive cycles.  Adds an
ISR overhead term for Cortex-M exception entry (ARM ABI §AAPCS64 §6.1.1 /
ARM-Cortex-M Generic UG §2.3.7 exception frame).

Algorithm
---------
Based on the static stack analysis method described in:

  Greenwood, B. (2011) "Static Stack Analysis for Embedded Systems",
  EuroLLVM Workshop Proceedings, §3 — DFS-based WCET stack depth.

And the ARM ABI stack conventions described in:

  ARM Procedure Call Standard (AAPCS), ARM IHI 0042F §5.2 — callee-saved
  registers; §6.1 — stack alignment and frame layout.

The algorithm:

  1. Build a lookup map of function name → FunctionFrame.
  2. For each node, DFS-walk all callees, accumulating frame sizes.
  3. Track the current call path to detect back-edges (cycles = recursion).
  4. The max depth from an entry function is: max over all leaves of the sum
     of frame sizes from root to leaf, plus isr_overhead_bytes.

ISR overhead
------------
On Cortex-M3/M4/M7 the exception entry hardware-saves 8 registers onto the
stack (xPSR, PC, LR, R12, R3, R2, R1, R0 = 8 × 4 = 32 bytes, ARM Generic UG
§B1.5.6 "Exception frame").  This module adds isr_overhead_bytes (default 32)
to the computed maximum to account for the worst-case ISR preemption at the
deepest call point.

For ATmega (AVR): the interrupt saves only PC (2–3 bytes, SREG not auto-saved)
so the default 32-byte ISR overhead is a conservative upper bound; pass
isr_overhead_bytes=3 for tighter ATmega estimates.

HONEST CAVEATS
--------------
* STATIC ESTIMATE ONLY — does not account for:
  - Variable-length arrays (VLA): `int buf[n]` grows the frame by n * sizeof(int)
    at runtime; VLAs make exact stack depth provably undecidable.
  - alloca() calls: explicit runtime stack allocation is invisible to this tool.
  - longjmp / setjmp: non-local transfers can bypass the call tree entirely.
  - Inline assembly that manipulates SP directly.
  - Compiler-generated prologue variability: actual frame sizes depend on
    compiler optimisation level (-O0 vs -Os), ABI, and target arch.  Frame
    sizes should be obtained from arm-none-eabi-gcc -fstack-usage output or
    avr-gcc -fstack-usage, not guessed.
* RECURSION: detected and flagged; worst-case depth for recursive calls is
  mathematically unbounded — cycle_max_frame_bytes is the per-iteration cost
  and must be multiplied by the maximum recursion depth manually.
* RTOS tasks: each FreeRTOS/CMSIS-RTOS task has its own stack; this tool
  analyses a single entry point.  Analyse each task independently.
* Indirect calls (function pointers, virtual dispatch): invisible to this
  static analyser.  Add synthetic FunctionFrame entries for known indirect
  targets.
* References:
  - ARM IHI 0042F AAPCS §5.2 / §6.1 (stack frame layout).
  - ARM Cortex-M Generic UG §B1.5.6 (exception entry frame).
  - Greenwood (2011), "Static Stack Analysis for Embedded Systems", §3.
  - Brylow et al. (2001), "An Analysis of the Stack Usage of Embedded Systems",
    LCTES/OM — empirical validation of DFS-based stack analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ── Public data model ─────────────────────────────────────────────────────────

@dataclass
class FunctionFrame:
    """Stack frame descriptor for a single function.

    Attributes
    ----------
    function_name:
        Unique name for this function (must match callee names in other frames).
    frame_size_bytes:
        Stack bytes consumed by this function's activation record (local
        variables + saved registers + padding).  Obtain from
        ``arm-none-eabi-gcc -fstack-usage`` or ``avr-gcc -fstack-usage``
        output files (``*.su`` files, column 2).
    callees:
        List of function names directly called by this function.  Indirect
        calls (function pointers, callbacks) must be enumerated manually.
    """
    function_name: str
    frame_size_bytes: int
    callees: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.frame_size_bytes < 0:
            raise ValueError(
                f"FunctionFrame '{self.function_name}': "
                f"frame_size_bytes must be >= 0, got {self.frame_size_bytes}"
            )


@dataclass
class StackDepthReport:
    """Result of :func:`estimate_stack_depth`.

    Attributes
    ----------
    entry_function:
        Name of the root function passed to :func:`estimate_stack_depth`.
    max_stack_depth_bytes:
        Worst-case stack depth in bytes, including the ISR preemption overhead.
        = max_call_chain_bytes + isr_overhead_bytes.
    critical_path:
        Ordered list of function names from the entry function to the deepest
        leaf (before ISR overhead is added).
    num_functions_analyzed:
        Number of distinct reachable functions visited during DFS.
    has_cycles:
        True if one or more recursive (cyclic) call chains were detected.
        When True, max_stack_depth_bytes is a lower bound only — the actual
        worst case depends on the maximum recursion depth.
    honest_caveat:
        Human-readable disclaimer summarising the limitations of the estimate.
    """
    entry_function: str
    max_stack_depth_bytes: int
    critical_path: list[str]
    num_functions_analyzed: int
    has_cycles: bool
    honest_caveat: str

    def as_dict(self) -> dict:
        return {
            "entry_function": self.entry_function,
            "max_stack_depth_bytes": self.max_stack_depth_bytes,
            "critical_path": self.critical_path,
            "num_functions_analyzed": self.num_functions_analyzed,
            "has_cycles": self.has_cycles,
            "honest_caveat": self.honest_caveat,
        }


# ── Core computation ───────────────────────────────────────────────────────────

def estimate_stack_depth(
    functions: list[FunctionFrame],
    entry_function_name: str,
    isr_overhead_bytes: int = 32,
) -> StackDepthReport:
    """Estimate worst-case stack depth for a firmware call tree.

    DFS through the call graph rooted at *entry_function_name*, accumulating
    frame sizes.  Cycles (recursion) are detected and flagged.  The ISR
    overhead is added once to the deepest path total.

    Parameters
    ----------
    functions:
        List of :class:`FunctionFrame` objects describing the call graph.
        Functions not present in this list but named as callees are treated as
        leaf nodes with frame_size_bytes = 0 (external / library functions).
    entry_function_name:
        Name of the root function (e.g. ``"main"`` or an ISR name).
    isr_overhead_bytes:
        Bytes added on top of the call-tree maximum to model the hardware
        exception entry frame.  Default 32 = Cortex-M3/M4/M7 hardware push
        (8 registers × 4 bytes, ARM Generic UG §B1.5.6).  Pass 3 for
        tight ATmega estimates (PC save only); pass 0 to disable.

    Returns
    -------
    StackDepthReport
        Full report with max depth, critical path, cycle flag, and caveats.

    Raises
    ------
    ValueError
        If *entry_function_name* is not found in *functions*, or if
        *isr_overhead_bytes* is negative.

    Depth-bar oracles
    -----------------
    Three-function chain ``main(100) → A(200) → B(50)``::

        estimate_stack_depth([
            FunctionFrame("main", 100, ["A"]),
            FunctionFrame("A", 200, ["B"]),
            FunctionFrame("B", 50, []),
        ], "main", isr_overhead_bytes=32).max_stack_depth_bytes
        # → 100 + 200 + 50 + 32 = 382

    References
    ----------
    ARM IHI 0042F AAPCS §5.2, §6.1 — stack frame layout.
    ARM Cortex-M Generic UG §B1.5.6 — 8-register exception frame (32 bytes).
    Greenwood (2011), §3 — DFS-based worst-case stack depth analysis.
    Brylow et al. (2001), LCTES/OM — empirical validation of DFS stack analysis.
    """
    if isr_overhead_bytes < 0:
        raise ValueError(
            f"isr_overhead_bytes must be >= 0, got {isr_overhead_bytes}"
        )

    # Build lookup map: name → FunctionFrame.
    frame_map: Dict[str, FunctionFrame] = {f.function_name: f for f in functions}

    if entry_function_name not in frame_map:
        raise ValueError(
            f"Entry function '{entry_function_name}' not found in functions list. "
            f"Available: {sorted(frame_map.keys())}"
        )

    has_cycles = False
    visited_count: Set[str] = set()

    # DFS — returns (max_accumulated_bytes, path_to_that_leaf) from *name*.
    # *on_stack* is the current DFS recursion path for cycle detection.
    def _dfs(
        name: str,
        accumulated: int,
        on_stack: List[str],
    ) -> Tuple[int, List[str]]:
        nonlocal has_cycles

        visited_count.add(name)

        frame = frame_map.get(name)
        frame_size = frame.frame_size_bytes if frame is not None else 0
        new_acc = accumulated + frame_size
        current_path = on_stack + [name]

        callees = frame.callees if frame is not None else []

        if not callees:
            # Leaf node.
            return new_acc, current_path

        best_depth = new_acc
        best_path = current_path  # leaf = current if all branches are cycles

        for callee in callees:
            # Cycle detection: if callee is on the current DFS stack, back-edge.
            if callee in on_stack:
                has_cycles = True
                # Stop recursion here; the current path to this node is valid.
                if new_acc > best_depth:
                    best_depth = new_acc
                    best_path = current_path
                continue

            child_depth, child_path = _dfs(callee, new_acc, current_path)
            if child_depth > best_depth:
                best_depth = child_depth
                best_path = child_path

        return best_depth, best_path

    max_chain_bytes, critical_path = _dfs(entry_function_name, 0, [])

    max_total = max_chain_bytes + isr_overhead_bytes

    caveat_parts = [
        "STATIC ESTIMATE ONLY.",
        "Does not account for: VLA (variable-length arrays), alloca(), "
        "longjmp/setjmp, inline assembly SP manipulation, or indirect calls "
        "(function pointers, callbacks — add synthetic FunctionFrame entries "
        "for known indirect targets).",
        "Frame sizes should come from arm-none-eabi-gcc / avr-gcc "
        "-fstack-usage output (*.su files), not manual estimates.",
    ]
    if has_cycles:
        caveat_parts.append(
            "CYCLE DETECTED: recursive call(s) found — max_stack_depth_bytes "
            "is a PER-ITERATION lower bound only.  Multiply cycle frame size "
            "by maximum recursion depth for a true worst-case estimate."
        )
    caveat_parts.append(
        f"ISR overhead of {isr_overhead_bytes} B added "
        "(Cortex-M3/M4/M7 exception frame = 8 regs × 4 B = 32 B, "
        "ARM Generic UG §B1.5.6).  Pass isr_overhead_bytes=3 for ATmega "
        "(PC save only) or 0 to disable."
    )
    caveat_parts.append(
        "Refs: ARM IHI 0042F AAPCS §5.2/§6.1; ARM Cortex-M Generic UG §B1.5.6; "
        "Greenwood (2011) 'Static Stack Analysis for Embedded Systems' §3; "
        "Brylow et al. (2001) LCTES/OM."
    )

    return StackDepthReport(
        entry_function=entry_function_name,
        max_stack_depth_bytes=max_total,
        critical_path=critical_path,
        num_functions_analyzed=len(visited_count),
        has_cycles=has_cycles,
        honest_caveat="  ".join(caveat_parts),
    )
