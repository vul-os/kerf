# fibre_link

*Module: `kerf_electronics.photonics.fibre_link` · Domain: electronics*

This module registers **3** LLM tool(s):

- [`photonics_fibre_coupling`](#photonics-fibre-coupling)
- [`photonics_link_budget`](#photonics-link-budget)
- [`photonics_dispersion_penalty`](#photonics-dispersion-penalty)

---

## `photonics_fibre_coupling`

Marcuse (1977) fibre-to-fibre mode-coupling efficiency.

Accounts for MFD mismatch, lateral offset, and angular misalignment.

η_overlap = [2·w₁·w₂/(w₁²+w₂²)]²
η_offset  = exp(-d²/((w₁²+w₂²)/2))
η_tilt    = exp(-(π·n·w_avg·θ/λ)²)
η_total   = η_overlap · η_offset · η_tilt

Typical values:
  SMF-28 fusion (same fibre): η ≈ 1.0, loss < 0.05 dB
  5 µm lateral offset, 10 µm MFD: η ≈ 0.46, loss ≈ 3.4 dB

Input: { mfd1_um, mfd2_um, lateral_offset_um?, angular_mrad?, lambda_nm?, n_core? }
Returns: { ok, eta_total, coupling_loss_db, eta_overlap, eta_offset, eta_tilt, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "mfd1_um": {
      "type": "number",
      "description": "Mode-field diameter of fibre 1 [\u00b5m] (e.g. 10.4 for SMF-28)."
    },
    "mfd2_um": {
      "type": "number",
      "description": "Mode-field diameter of fibre 2 [\u00b5m]."
    },
    "lateral_offset_um": {
      "type": "number",
      "description": "Lateral transverse offset [\u00b5m] (default 0)."
    },
    "angular_mrad": {
      "type": "number",
      "description": "Angular tilt misalignment [mrad] (default 0)."
    },
    "lambda_nm": {
      "type": "number",
      "description": "Operating wavelength [nm] (default 1550)."
    },
    "n_core": {
      "type": "number",
      "description": "Core refractive index (default 1.468 for silica @ 1550)."
    }
  },
  "required": [
    "mfd1_um",
    "mfd2_um"
  ]
}
```

---

## `photonics_link_budget`

Full optical link power budget with dispersion penalty.

margin = Tx − Rx_sens − fibre_loss − connector_loss
         − splice_loss − splitter_loss − dispersion_penalty
         − ageing_margin

Fibre types: SMF-28, SMF-28e+, MMF-OM4, MMF-OM3, DSF, NZDSF

Validation case:
  SMF-28 @ 1550 nm, 40 km, 2 connectors + 2 fusion splices,
  Tx=0 dBm, Rx_sens=-28 dBm, 10 Gbps → margin ≈ 10 dB

Input: { tx_dbm, rx_sens_dbm, fibre_type, length_km, n_connectors?, n_splices?, bit_rate_gbps?, wavelength_nm?, connector_loss_db?, splice_loss_db?, n_splitter_outputs?, ageing_margin_db?, include_dispersion_penalty? }
Returns: { ok, link_ok, margin_db, fibre_loss_db, total_connector_loss_db, total_splice_loss_db, dispersion_penalty_db, total_loss_db, max_allowable_loss_db, dispersion_detail, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "tx_dbm": {
      "type": "number",
      "description": "Transmit power [dBm]."
    },
    "rx_sens_dbm": {
      "type": "number",
      "description": "Receiver sensitivity (minimum detectable power) [dBm]."
    },
    "fibre_type": {
      "type": "string",
      "description": "Fibre type: 'SMF-28', 'SMF-28e+', 'MMF-OM4', 'MMF-OM3', 'DSF', 'NZDSF'."
    },
    "length_km": {
      "type": "number",
      "description": "Fibre span length [km]."
    },
    "n_connectors": {
      "type": "integer",
      "description": "Number of connector mated pairs (default 2)."
    },
    "n_splices": {
      "type": "integer",
      "description": "Number of fusion splices (default 0)."
    },
    "bit_rate_gbps": {
      "type": "number",
      "description": "Line bit rate [Gbps] (default 10)."
    },
    "wavelength_nm": {
      "type": "number",
      "description": "Operating wavelength [nm] (default 1550)."
    },
    "source_linewidth_nm": {
      "type": "number",
      "description": "Laser linewidth \u0394\u03bb [nm] FWHM (default 0.1)."
    },
    "connector_loss_db": {
      "type": "number",
      "description": "Per-connector insertion loss [dB] (default 0.30)."
    },
    "splice_loss_db": {
      "type": "number",
      "description": "Per-splice insertion loss [dB] (default 0.05)."
    },
    "n_splitter_outputs": {
      "type": "integer",
      "description": "Splitter output ports; 0 = no splitter (default 0)."
    },
    "splitter_excess_loss_db": {
      "type": "number",
      "description": "Splitter excess loss beyond ideal splitting [dB] (default 0.7)."
    },
    "ageing_margin_db": {
      "type": "number",
      "description": "Ageing + repair margin [dB] (default 3.0)."
    },
    "include_dispersion_penalty": {
      "type": "boolean",
      "description": "Include CD/PMD/modal dispersion penalty (default true)."
    },
    "margin_threshold_db": {
      "type": "number",
      "description": "Minimum acceptable margin [dB] (default 0.0)."
    }
  },
  "required": [
    "tx_dbm",
    "rx_sens_dbm",
    "fibre_type",
    "length_km"
  ]
}
```

---

## `photonics_dispersion_penalty`

Chromatic dispersion, PMD, and modal bandwidth penalty for a fibre link.

Chromatic: Δτ_CD = |D| · Δλ · L   [ps]
PMD:       Δτ_PMD = PMD_coeff · √L  [ps]
Modal BW:  BW = BW_per_km / √L      [GHz] (EMB concatenation rule)

Fibre types: SMF-28, SMF-28e+, MMF-OM4, MMF-OM3, DSF, NZDSF

Input: { fibre_type, length_km, bit_rate_gbps, wavelength_nm?, source_linewidth_nm?, pmd_enabled? }
Returns: { ok, delta_tau_cd_ps, cd_penalty_db, cd_ok, delta_tau_pmd_ps, pmd_penalty_db, pmd_ok, bw_modal_ghz, modal_penalty_db, modal_ok, total_dispersion_penalty_db }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "fibre_type": {
      "type": "string",
      "description": "Fibre type: 'SMF-28', 'MMF-OM4', etc."
    },
    "length_km": {
      "type": "number",
      "description": "Fibre span length [km]."
    },
    "bit_rate_gbps": {
      "type": "number",
      "description": "Line bit rate [Gbps]."
    },
    "wavelength_nm": {
      "type": "number",
      "description": "Operating wavelength [nm] (default 1550)."
    },
    "source_linewidth_nm": {
      "type": "number",
      "description": "Laser linewidth \u0394\u03bb [nm] FWHM (default 0.1)."
    },
    "pmd_enabled": {
      "type": "boolean",
      "description": "Include PMD penalty (default true)."
    }
  },
  "required": [
    "fibre_type",
    "length_km",
    "bit_rate_gbps"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
