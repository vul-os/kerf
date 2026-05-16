# jewelry_pieces — Whole-Piece Builders

Composite whole-piece builders for pendants, earrings, brooches, cufflinks, and bangles/cuffs. Each builder outputs a fully parametric node with attach-points for downstream gem-seat, setting, and finding nodes.

## When to use

Use these tools to create complete jewelry pieces beyond rings and chains:
- Drop, solitaire, halo, bar, or locket pendants with integrated bail and stone mount
- Stud, drop, hoop, huggie, chandelier, or threader earring pairs
- Oval/round/shield brooches with pin-stem mount hints
- Toggle, T-bar, chain-link, or chain-reaction cufflink pairs
- Closed bangles or open C-shaped cuff bracelets sized by wrist circumference

Keywords: pendant, earring, stud earrings, drop earrings, hoop earrings, huggie earrings, chandelier earrings, brooch, cufflink, bangle, cuff bracelet, solitaire drop, halo pendant, locket, bar pendant, post butterfly, lever back, wrist size, bangle size.

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_create_pendant` | Appends a `pendant` composite node; styles: `solitaire_drop`, `halo`, `bar`, `locket`, `geometric`; includes integrated bail + stone mount attach_points; inputs: `file_id`, `style`, stone size, bail type |
| `jewelry_create_earrings` | Appends an `earrings` composite node (matched pair); styles: `stud`, `drop`, `hoop`, `huggie`, `chandelier`, `threader`; includes ear-finding attach-point for downstream `jewelry_create_finding` |
| `jewelry_create_brooch` | Appends a `brooch` composite node; frame + stone attach_points + pin-finding mount hints (joint/pin_stem/catch); inputs: `file_id`, frame style, stone positions |
| `jewelry_create_cufflink` | Appends a `cufflink` composite node (matched pair); decorative face + post stem + back element; back styles: `toggle` (hinged T-bar), `t_bar` (fixed), `chain`, `bullet`, `whale_tail` |
| `jewelry_create_bangle` | Appends a `bangle` composite node; closed full-circle or open C-shaped cuff; sized by wrist circumference (mm/inches) or US size (XS/S/M/L/XL/XXL); cross-sections: round, flat, oval, half-round; optional hinge and clasp |

## Example

Jeweller: "Make a pair of 6 mm round brilliant diamond stud earrings in 18k white gold."

1. `jewelry_create_earrings` — style=`stud`, stone_diameter_mm=6.0
2. `jewelry_create_gemstone` (×2) — cut=`round_brilliant`, diameter_mm=6.0, position from attach_points
3. `jewelry_create_prong_head` (×2) — stone_diameter=6.0, prong_count=4 → attach to each stud face
4. `jewelry_create_finding` (×2) — family=`ear_finding`, kind=`post_butterfly`
