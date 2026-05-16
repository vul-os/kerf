# Tolerance Stack-Up Analysis

Pure-Python 1D dimensional tolerance stack-up analysis. No OCC dependency.
Stateless — no DB write. Supports WC, RSS, MRSS (Benderized), and Monte-Carlo
methods. All inputs use consistent length units (typically mm).

References: Drake, "Dimensioning and Tolerancing Handbook" (1999);
Bender, SAE 680490 (1968).

---

## When to use

Trigger on: tolerance stack, stack-up, gap analysis, assembly clearance,
worst-case tolerance, RSS tolerance, statistical tolerance, Cp, Cpk, defect
PPM, yield, tolerance chain, dimensional loop, fit analysis, clearance/
interference, part-to-part variation, tolerance budget.

---

## Tools

### `tolstack_analyze`

Run a 1D tolerance stack-up analysis on a list of dimensional contributors.

**Key inputs:**
- `contributors` — list of `{nominal, plus_tol, minus_tol, direction (+1/-1),
  distribution}` dicts.
- `method` — `'worst-case'`, `'rss'` (default), `'mrss'`, or `'monte-carlo'`.
- `n_samples` — Monte-Carlo sample count (default 100 000).
- `bender_cf` — Bender correction factor for MRSS (default 1.5).

**Computes:** gap_nominal, gap_min/max (method bounds), sigma_gap, Cp, Cpk,
defect_ppm, yield_pct. Asymmetric tolerances are auto-symmetrised with a
nominal shift.

**Returns:** `{ok, gap_nominal, gap_min_wc, gap_max_wc, gap_min, gap_max,
sigma_gap, cp, cpk, defect_ppm, yield_pct, warnings:[]}`.

---

### `tolstack_methods`

List all available stack-up methods with descriptions and typical use cases.

**Key inputs:** none.

**Returns:** `{ok, methods: {worst-case:{...}, rss:{...}, mrss:{...}, monte-carlo:{...}}}`.

Use this first to choose the right method before calling `tolstack_analyze`.

---

## Example

**User:** "My assembly has three parts contributing to a gap. Part A: 50 ± 0.05 mm
(+dir), Part B: 30 ± 0.03 mm (-dir), Part C: 15 ± 0.02 mm (-dir). What's the
gap and process capability?"

**Tool:** `tolstack_analyze` with contributors for the three parts and
`method:'rss'`.

Returns gap_nominal = 5.0 mm, ±3σ gap ≈ 4.93–5.07 mm, Cpk and defect PPM.
