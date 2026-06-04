# Cut-List Optimisation

> Optimise a list of boards against stock lengths using First-Fit Decreasing bin-packing.

**Module**: `packages/kerf-woodworking/src/kerf_woodworking/cut_list.py`
**Shipped**: Wave 10
**LLM tools**: `woodworking_cut_list`

---

## What it is

The cut-list optimiser takes a list of required board pieces (label, length) and a set of available stock boards, then assigns pieces to boards to minimise waste using a First-Fit Decreasing heuristic. Unlike the cabinet cut-list module, this operates on 1-D linear cuts (dimensional lumber, aluminium extrusions, pipe).

## How to use it

### From chat

> "Optimise my cut list: 4× 1200 mm, 6× 800 mm, 2× 600 mm from 2400 mm stock boards."

### From Python

```python
from kerf_woodworking.cut_list import BoardPiece, StockBoard, optimise_cut_list

pieces = [
    BoardPiece(label="shelf", length_mm=1200, qty=4),
    BoardPiece(label="divider", length_mm=800, qty=6),
    BoardPiece(label="base", length_mm=600, qty=2),
]
stock = StockBoard(length_mm=2400, qty=10)
result = optimise_cut_list(pieces, stock, kerf_mm=3)

print(result.n_boards_used, result.waste_pct)
for assignment in result.assignments:
    print(assignment.board_index, assignment.cuts)
```

### From an LLM tool spec

```json
{"tool": "woodworking_cut_list", "input": {"pieces": [{"label": "shelf", "length_mm": 1200, "qty": 4}], "board_length_mm": 2400, "kerf_mm": 3}}
```

## How it works

`_ffd_sort` sorts all required cuts by decreasing length. `_pack` iterates through sorted cuts: for each cut, it attempts to fit it into the first existing board that has sufficient remaining length (after kerf deduction). If none fits, a new stock board is opened. This is the classic First-Fit Decreasing bin-packing approach, known to use at most 11/9 × OPT + 4 boards for the 1-D case.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `optimise_cut_list(pieces, stock, kerf_mm)` | `CutListResult` | Board assignments and waste stats |
| `cut_list_to_dict(result)` | `dict` | Serialisable summary for export |
| `BoardPiece(label, length_mm, qty)` | instance | Required piece specification |
| `StockBoard(length_mm, qty)` | instance | Available stock board |

## Example

```python
result = optimise_cut_list(pieces, stock, kerf_mm=3)
# CutListResult(n_boards_used=5, waste_pct=8.3,
#               assignments=[...])
```

## Honest caveats

FFD is a heuristic; it does not guarantee the globally optimal solution. For short runs (< 20 pieces) the gap is negligible; for large jobs consider an ILP solver. The module handles linear (1-D) cuts only; panel sheet nesting is in `mozaik-cabinet`. Defect zones, wane, and moisture content are not modelled.

## References

- Johnson, *Near-Optimal Bin Packing Algorithms*, MIT PhD Thesis (1973).
