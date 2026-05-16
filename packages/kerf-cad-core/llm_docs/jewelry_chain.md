# jewelry_chain — Parametric Chain, Bracelet, and Necklace Builders

Fully parametric chain and linked-jewelry builders covering sixteen link styles, standard jewellery lengths, tennis bracelets, station necklaces, lariats, charm bracelets, multi-strand designs, and extender chains.

## When to use

Use these tools whenever a jeweller needs to:
- Build a chain in any standard link style (cable, curb, figaro, rope, box, snake, byzantine, mariner/anchor, rolo, bismark, wheat, herringbone, omega, popcorn, ball, singapore)
- Convert between total chain length and link count for a given wire gauge and link style
- Look up standard length names (bracelet 7"/18 cm, necklace 16/18/20/24", anklet 9–11", choker/collar)
- Design a tennis bracelet (continuous stone line) or riviera necklace
- Build a station necklace (periodic stones along a carrier chain)
- Create a lariat / Y-necklace (open-end with sliding drop pendant)
- Design a charm bracelet with evenly spaced jump-ring attach points
- Generate a multi-strand layered chain joined at a connector
- Add an adjustable extender chain with multiple end loops

Keywords: chain, necklace, bracelet, anklet, tennis bracelet, station necklace, lariat, Y-necklace, charm bracelet, multi-strand, extender chain, cable chain, curb chain, figaro, rope chain, box chain, byzantine, link count, chain length, clasp, lobster clasp, toggle clasp.

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_chain_length` | Read-only: converts total_length_mm ↔ link_count for a given link style and wire gauge; or looks up a standard length by name (e.g. `necklace_18in`); no file write |
| `jewelry_create_chain` | Appends a `chain_assembly` node; builds a fully parametric chain from one of 16 link styles with clasp choice; inputs: `link_style`, `wire_gauge_mm`, `link_length_mm`, `link_count` or `total_length_mm` or `standard_length`, `clasp` |
| `jewelry_create_tennis_bracelet` | Appends a tennis-bracelet node; continuous equal round stones in flexible link mounts; inputs: `stone_diameter_mm`, `stone_count` or `total_length_mm` or `standard_length`, `link_style` |
| `jewelry_create_station_necklace` | Appends a station-necklace node; periodic stone stations spaced along a thin carrier chain; inputs: `stone_diameter_mm`, `station_spacing_mm`, chain length |
| `jewelry_create_lariat` | Appends a lariat/Y-necklace node; open-ended body chain + sliding drop pendant, no clasp; inputs: body chain spec + drop chain spec + terminal stone hint |
| `jewelry_create_charm_bracelet` | Appends a charm-bracelet node; base chain with N evenly-spaced jump-ring attach points; inputs: `attach_point_count`, `link_style`, chain length |
| `jewelry_create_multi_strand` | Appends a multi-strand node; 2–5 parallel chains joined at a connector and clasp; inputs: per-strand spec array, connector style |
| `jewelry_create_extender_chain` | Appends an extender-chain node; short chain with a series of end loops for adjustable-length attachment; inputs: `length_mm`, `loop_count`, `loop_spacing_mm` |

## Example

Jeweller: "Build a 7-inch cable-chain tennis bracelet with 0.25 ct round stones."

1. `jewelry_chain_length` — link_style=`cable`, standard_length=`bracelet_7in` → link count for the chosen wire gauge
2. `jewelry_create_tennis_bracelet` — stone_diameter_mm=4.1 (0.25 ct ≈ 4.1 mm), standard_length=`bracelet_7in`, link_style=`cable`
