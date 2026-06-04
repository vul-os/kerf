# electronics_netlist_consistency

*Module: `kerf_electronics.tools.netlist_drc` · Domain: electronics*

## Description

Verify that a PCB layout's copper connectivity matches the schematic netlist (IPC-7351B §4.1-4.2). Detects: missing_connections (schematic connection not realised in copper), extra_connections (PCB copper joins pins from different schematic nets — short), and swapped_nets (pin assignments migrated between nets, indicating a net swap). Returns a ConsistencyReport with consistent=true/false, per-category lists, recommended_fixes, and IPC-7351B-tagged violations with severity=error|warning. Inputs: schematic_json (source_* CircuitJSON elements) and pcb_json (pcb_* CircuitJSON elements). Run run_pcb_drc first for physical DRC; run this tool for logical netlist parity.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "schematic_json": {
      "type": "array",
      "description": "Flat CircuitJSON array containing source_component, source_port, source_trace, and source_net elements that define the intended netlist.",
      "items": {
        "type": "object"
      }
    },
    "pcb_json": {
      "type": "array",
      "description": "Flat CircuitJSON array containing pcb_smtpad, pcb_plated_hole, and pcb_trace elements that describe the actual copper layout. Pads must have source_component_id + pin_name (or component_ref + pin) fields to be matched against the schematic.",
      "items": {
        "type": "object"
      }
    }
  },
  "required": [
    "schematic_json",
    "pcb_json"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_netlist_consistency",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
