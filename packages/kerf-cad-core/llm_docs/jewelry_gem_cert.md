# jewelry_gem_cert — Gem Certificate Metadata and Traceability

Link a gemstone instance to its laboratory grading certificate (GIA, IGI, AGS, EGL, GCAL, HRD), validate certificate fields, and build supply-chain traceability manifests for finished jewelry pieces.

## When to use

Use these tools when a jeweller or gemologist needs to:
- Attach a GIA / IGI / AGS grading certificate reference to a gemstone node
- Validate certificate field values (colour grade, clarity grade, cut quality, fluorescence, origin)
- Generate a supply-chain traceability manifest listing all stones, certificates, and origins in a piece
- Produce a one-string human-readable summary of a certificate for display or printing

Keywords: gem certificate, GIA certificate, IGI certificate, AGS, EGL, GCAL, HRD, grading report, colour grade, clarity grade, cut grade, fluorescence, polish, symmetry, traceability, supply chain, lab grown, natural, treated, CVD diamond, HPHT.

## Grading scales

**Colour (GIA / universal):** D E F G H I J K L M N O P Q R S T U V W X Y Z  
**Clarity (GIA):** FL IF VVS1 VVS2 VS1 VS2 SI1 SI2 I1 I2 I3  
**Cut quality (GIA):** Excellent Very Good Good Fair Poor  
**Cut quality (AGS numeric, lower = better):** 0 (Ideal) 1 2 3 4 5 6 7 8 9 10  
**Polish / Symmetry (GIA / IGI / AGS):** Excellent Very Good Good Fair Poor  
**Fluorescence (GIA):** None Faint Medium Strong Very Strong  

**Origin:**
- `natural` — mined, earth-origin
- `lab_grown` — laboratory-grown (CVD, HPHT, flux, hydrothermal)
- `treated` — natural with significant enhancement (fracture-fill, HPHT colour treatment, irradiation, coating)

## Certificate reference fields (CertificateRef)

```
{
  "lab":           str,    // GIA | IGI | AGS | EGL | GCAL | HRD
  "report_number": str,    // lab report number
  "shape":         str,    // round_brilliant | princess | oval | ...
  "weight_ct":     float,  // carat weight
  "color":         str,    // D...Z or fancy color description
  "clarity":       str,    // FL...I3
  "cut":           str,    // Excellent | Very Good | Good | Fair | Poor
  "polish":        str,    // Excellent | Very Good | Good | Fair | Poor
  "symmetry":      str,
  "fluorescence":  str,    // None | Faint | Medium | Strong | Very Strong
  "measurements":  str,    // e.g. "6.50-6.53×4.01 mm"
  "depth_pct":     float,
  "table_pct":     float,
  "origin":        str,    // natural | lab_grown | treated
  "cert_url":      str | None,
}
```

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_gem_cert_validate` | Read-only: sanity-check all certificate fields against valid grade scales; returns `issues` list (empty = valid) |
| `jewelry_gem_cert_attach` | Read-only (annotates in-memory): attach a `CertificateRef` to a gemstone dict from `gem_studio` / `gemstones`; adds `cert` key to the gemstone dict |
| `jewelry_gem_cert_traceability` | Read-only: build a supply-chain traceability manifest for a multi-stone piece dict; returns manifest with per-stone `{stone_id, lab, report_number, origin, carat}` |
| `jewelry_gem_cert_report` | Read-only: return a human-readable one-string summary of a certificate; e.g. "GIA#1234567890 — 1.01 ct Round Brilliant, D/IF/Excellent, None fluor., Natural" |

## Example

Jeweller: "Attach a GIA cert to our 1.01 ct round brilliant and check the traceability chain for the piece."

1. `jewelry_gem_cert_validate` — cert={lab:"GIA", report_number:"1234567890", shape:"round_brilliant", weight_ct:1.01, color:"D", clarity:"IF", cut:"Excellent", polish:"Excellent", symmetry:"Excellent", fluorescence:"None", origin:"natural"} → issues=[]
2. `jewelry_gem_cert_attach` — gemstone=`<gem dict>`, cert=`<from step 1>` → gemstone dict with cert annotation
3. `jewelry_gem_cert_traceability` — piece={stones:[{stone_id:"centre", ...with cert attached}]} → manifest with cert + origin for all stones
4. `jewelry_gem_cert_report` — cert=`<from step 1>` → "GIA#1234567890 — 1.01 ct Round Brilliant, D/IF/Excellent, None fluor., Natural"
