# GD&T Callouts and Tolerance Analysis

*Domain: Mechanical · Module: `packages/kerf-cad-core/src/kerf_cad_core/gdt_callouts/` · Shipped: Wave 8*

## Overview

ASME Y14.5-2018 geometric dimensioning and tolerancing (GD&T) callout generation and tolerance stack-up analysis. Generates valid GD&T feature control frames for common applications (flatness, cylindricity, position, true position, perpendicularity, angularity, profile of a surface), computes virtual condition and resultant condition for mating parts, and runs worst-case and statistical (RSS) 1-D tolerance stack-ups.

## When to use

- Annotating a drawing with GD&T callouts that meet ASME Y14.5 formatting requirements.
- Checking whether a tolerance stack-up closes within an assembly gap specification.
- Computing bonus tolerance from maximum material condition (MMC) modifiers.

## API

```python
from kerf_cad_core.gdt_callouts.tools import (
    feature_control_frame,
    true_position_tolerance,
    tolerance_stack_rss,
    tolerance_stack_worst_case,
)

fcf = feature_control_frame(
    characteristic="position",
    tolerance=0.5,
    modifier="MMC",
    datums=["A", "B", "C"],
)
print(fcf["symbol_string"])   # "⌖ ⌀0.5 (M) | A | B | C"

result = tolerance_stack_worst_case(
    contributions=[
        {"nominal": 10.0, "tolerance": 0.1},
        {"nominal":  5.0, "tolerance": 0.05},
    ],
    gap_target=4.5,
)
print(result["worst_case_gap"], result["closes"])
```

## LLM tools

`feature_gdt_callout`, `feature_tolerance_stack`

## References

- ASME Y14.5-2018, *Dimensioning and Tolerancing*.
- Krulikowski, *Fundamentals of GD&T Using the Compliant Parts Method* (2012).

## Honest caveats

GD&T callout generation follows ASME Y14.5-2018. ISO GPS (ISO 1101) uses different notation for some characteristics — verify if the drawing is for an ISO-market customer. Tolerance stack-up is 1-D only; 2-D and 3-D tolerance analyses (DCS, MonteCarlo 3-D) are not implemented in this module.
