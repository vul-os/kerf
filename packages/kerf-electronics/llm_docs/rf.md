# rf

*Module: `kerf_electronics.tools.rf` · Domain: electronics*

This module registers **3** LLM tool(s):

- [`run_rf_study`](#run-rf-study)
- [`rf_job_status`](#rf-job-status)
- [`import_touchstone`](#import-touchstone)

---

## `run_rf_study`

Run an S-parameter analysis on a .rf-study file using scikit-rf. Performs Smith chart analysis, VSWR, return loss, and insertion loss on touchstone (.sNp) data.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
    },
    "port_impedance": {
      "type": "number",
      "description": "Reference impedance in ohms for renormalization (default 50)."
    },
    "freq_unit": {
      "type": "string",
      "enum": [
        "Hz",
        "kHz",
        "MHz",
        "GHz"
      ],
      "description": "Frequency unit for output plots (default GHz)."
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## `rf_job_status`

Poll the status of an RF study analysis job. Returns job status, and when complete the S-parameter analysis results including Smith chart SVG, VSWR, return loss, and insertion loss.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## `import_touchstone`

Import a Touchstone (.sNp) file and create a .rf-study file. Supports S1P, S2P, S3P, S4P formats with automatic renormalization to the specified port impedance.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "touchstone_file_id": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "port_impedance": {
      "type": "number",
      "description": "Reference impedance in ohms (default 50)."
    }
  },
  "required": [
    "touchstone_file_id",
    "name"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
