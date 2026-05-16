# jewelry_findings — Parametric Findings Generator

Parametric small functional components (findings) required by every real piece of jewellery: jump rings, bails, ear findings, pin findings, end caps, clasps, and connectors.

## When to use

Use these tools whenever a jeweller needs to add the functional hardware that makes a piece wearable:
- Jump rings to link components (open/closed, round/oval, with wire gauge + inner diameter)
- Pendant bails (pinch, snap/clip, glue-on, classic loop)
- Earring findings (fish-hook, lever-back, post+butterfly, screw-back, huggie, kidney wire, ear nut)
- Pin findings for brooches/stick pins (pin stem, joint, rotating catch, roller catch)
- End caps for chain, cord, or ribbon (glue-in, crimp, cord end, ribbon clamp, connector link)
- Clasps (lobster claw, spring ring, toggle/T-bar, box clasp, slide lock, magnetic)

Keywords: finding, jump ring, bail, pendant bail, ear wire, fish hook, lever back, earring post, butterfly back, screw back, pin stem, joint, catch, clasp, lobster clasp, toggle clasp, box clasp, end cap, crimp, cord end.

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_list_findings` | Read-only: lists all valid `family` names and their `kind` values; pass a `family` to filter (e.g. `ear_finding`); no file write |
| `jewelry_create_finding` | Appends a `finding` node to a `.feature` file; inputs: `family` (jump_ring/bail/ear_finding/pin_finding/end_cap/clasp), `kind` (specific type within family), and family-specific dimension params; returns node id |

### Finding families and kinds

| Family | Kinds |
|--------|-------|
| `jump_ring` | round, oval (open or closed) |
| `bail` | pinch, snap, glue_on, loop |
| `ear_finding` | fish_hook, lever_back, post_butterfly, screw_back, huggie, kidney, ear_nut |
| `pin_finding` | pin_stem, joint, catch_rotating, catch_roller, nail_pin |
| `end_cap` | glue_in, crimp, cord_end, ribbon_clamp, connector_link |
| `clasp` | lobster, spring_ring, toggle, box_clasp, slide_lock, magnetic |

## Example

Jeweller: "Add a lobster-claw clasp to a necklace and a loop bail to a pendant."

1. `jewelry_list_findings` — family=`clasp` → confirms `lobster` is a valid kind
2. `jewelry_create_finding` — family=`clasp`, kind=`lobster`, wire_gauge_mm=1.0 → clasp node
3. `jewelry_create_finding` — family=`bail`, kind=`loop`, inner_diameter_mm=4.0 → bail node on pendant
