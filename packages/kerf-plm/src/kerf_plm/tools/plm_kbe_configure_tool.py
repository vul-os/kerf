"""
kerf_plm.tools.plm_kbe_configure_tool — LLM tool surface for KBE-driven configuration.

Exposes ``plm_kbe_configure`` as an LLM tool that accepts customer options +
inline KBE rules + configurator rules and returns a fully resolved BOM.

Tool name:  ``plm_kbe_configure``

Input schema
------------
{
  "options": {
    "type": "object",
    "description": "Customer engineering requirements (free-form key/value pairs)"
  },
  "kbe_rules": {
    "type": "array",
    "description": "List of KBE rule dicts (id, description, derive_expr, select_expr, condition_keys, domain)",
    "items": { "type": "object" }
  },
  "configurator_rules": {
    "type": "array",
    "description": "List of configurator rule dicts (id, description, condition_expr, effect)",
    "items": { "type": "object" }
  },
  "eco_table": {
    "type": "array",
    "description": "Optional list of ECO records {old_sku, new_sku, effective_from, eco_id}",
    "items": { "type": "object" }
  },
  "effective_date": {
    "type": "string",
    "description": "ISO date (YYYY-MM-DD) for effectivity filtering; omit to skip"
  }
}

Returns
-------
{
  "ok":              bool,
  "bom":             [...],         // selected part lines
  "kbe_params":      {...},         // KBE-derived engineering params
  "config_params":   {...},         // final configurator param set
  "fired_kbe_rules": [...],         // ordered KBE rule IDs that fired
  // on error:
  "error":           str,
  "error_code":      str,
  "conflict_detail": {...}          // present for CONFIG_CONFLICT
}

Inline rule DSL
---------------
Because this tool is invoked by an LLM that cannot pass Python callables, the
``kbe_rules`` and ``configurator_rules`` arrays carry *serialised* rule
descriptions.  The tool re-hydrates them into live callable objects.

KBE rule dict shape::

    {
      "id":             "battery_capacity",
      "description":    "Derive battery capacity from weight + target range",
      "domain":         "automotive",
      "condition_keys": ["weight_kg", "target_range_km"],   // all must be non-None
      "derive": {
        "battery_capacity_kwh": "weight_kg * target_range_km / 10000"  // expr string
      },
      "select": {
        // lookup table: battery_capacity_kwh threshold → SKU
        "param":  "battery_capacity_kwh",
        "table":  [[75, "BATT-75-AWD"], [90, "BATT-90-AWD"], [110, "BATT-110-AWD"]],
        "default": "BATT-110-AWD"
      }
    }

Configurator rule dict shape::

    {
      "id":             "awd_motor_rule",
      "description":    "AWD selects dual motor SKU",
      "domain":         "automotive",
      "condition_expr": "state.get('drivetrain') == 'AWD'",  // eval'd with state in scope
      "effect": [
        {"action_type": "include_part", "sku": "MOTOR-DUAL-AWD", "quantity": 2,
         "provenance": "AWD drivetrain requires dual motors"}
      ]
    }
"""

from __future__ import annotations

import json
import math
from typing import Any

from kerf_rules.kbe import KBEEngine, KBERule, KBEState, RuleSelection
from kerf_plm.configurator import Action, Configurator, ConfiguratorState, Rule
from kerf_plm.kbe_bridge import plm_kbe_configure as _plm_kbe_configure


# ---------------------------------------------------------------------------
# Rule hydration helpers
# ---------------------------------------------------------------------------


def _hydrate_kbe_rule(rd: dict[str, Any]) -> KBERule:
    """Re-hydrate a serialised KBE rule dict into a live KBERule."""
    rule_id = rd.get("id", "unnamed")
    desc = rd.get("description", "")
    domain = rd.get("domain", "general")
    condition_keys: list[str] = rd.get("condition_keys", [])
    derive_spec: dict[str, str] = rd.get("derive", {})
    select_spec: dict[str, Any] | None = rd.get("select")

    def condition(state: KBEState) -> bool:
        return all(state.get(k) is not None for k in condition_keys)

    def derive(state: KBEState) -> dict[str, Any]:
        result: dict[str, Any] = {}
        ns = {
            "__builtins__": {},
            "math": math,
        }
        # Merge state into namespace
        ns.update(state.options)
        ns.update(state.params)
        for key, expr in derive_spec.items():
            try:
                result[key] = eval(expr, ns)  # noqa: S307
            except Exception:
                pass
        return result

    def select(state: KBEState) -> list[RuleSelection]:
        if not select_spec:
            return []
        param_key = select_spec.get("param", "")
        table = select_spec.get("table", [])   # [[threshold, sku], ...]
        default_sku = select_spec.get("default", "")
        val = state.get(param_key)
        if val is None:
            return []
        chosen_sku = default_sku
        for threshold, sku in sorted(table, key=lambda row: row[0]):
            if val <= threshold:
                chosen_sku = sku
                break
        if not chosen_sku:
            return []
        return [
            RuleSelection(
                rule_id=rule_id,
                param_key=param_key,
                param_value=val,
                sku=chosen_sku,
                provenance=f"{rule_id}: {param_key}={val!r} → {chosen_sku!r}",
            )
        ]

    return KBERule(
        id=rule_id,
        description=desc,
        condition=condition,
        derive=derive,
        select=select,
        domain=domain,
    )


def _hydrate_configurator_rule(rd: dict[str, Any]) -> Rule:
    """Re-hydrate a serialised configurator rule dict into a live Rule."""
    rule_id = rd.get("id", "unnamed")
    desc = rd.get("description", "")
    domain = rd.get("domain", "general")
    condition_expr: str = rd.get("condition_expr", "True")
    effect_list: list[dict] = rd.get("effect", [])

    def condition(state: ConfiguratorState) -> bool:
        ns = {"__builtins__": {}, "state": state}
        try:
            return bool(eval(condition_expr, ns))  # noqa: S307
        except Exception:
            return False

    def effect(state: ConfiguratorState) -> list[Action]:
        actions: list[Action] = []
        for ae in effect_list:
            at = ae.get("action_type", "")
            if at == "set_param":
                actions.append(
                    Action.set_param(
                        key=ae["param_key"],
                        value=ae["param_value"],
                        rule_id=rule_id,
                        provenance=ae.get("provenance", ""),
                        hard_constraint=ae.get("hard_constraint", False),
                    )
                )
            elif at == "include_part":
                actions.append(
                    Action.include_part(
                        sku=ae["sku"],
                        quantity=ae.get("quantity", 1),
                        rule_id=rule_id,
                        provenance=ae.get("provenance", ""),
                    )
                )
        return actions

    return Rule(
        id=rule_id,
        description=desc,
        condition=condition,
        effect=effect,
        domain=domain,
    )


# ---------------------------------------------------------------------------
# Main tool function
# ---------------------------------------------------------------------------


def plm_kbe_configure_tool(
    options: dict[str, Any],
    kbe_rules: list[dict[str, Any]],
    configurator_rules: list[dict[str, Any]],
    eco_table: list[dict[str, Any]] | None = None,
    effective_date: str = "",
) -> dict[str, Any]:
    """
    LLM-callable entry point: drive KBE + configurator in one call.

    Accepts serialised rule dicts, hydrates them, and delegates to
    ``plm_kbe_configure()``.
    """
    live_kbe_rules = [_hydrate_kbe_rule(r) for r in kbe_rules]
    live_cfg_rules = [_hydrate_configurator_rule(r) for r in configurator_rules]
    return _plm_kbe_configure(
        options=options,
        kbe_rules=live_kbe_rules,
        configurator_rules=live_cfg_rules,
        eco_table=eco_table or [],
        effective_date=effective_date,
    )


# ---------------------------------------------------------------------------
# Anthropic tool schema
# ---------------------------------------------------------------------------

TOOL_SCHEMA = {
    "name": "plm_kbe_configure",
    "description": (
        "Drive KBE-based engineering parameter derivation and PLM variant "
        "configurator parts selection in a single call.  Given customer options "
        "(e.g. vehicle weight, target range, drivetrain) and inline KBE + "
        "configurator rule packs, returns a fully resolved BOM with part SKUs, "
        "provenance, and optional ECO/ECR effectivity filtering."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "options": {
                "type": "object",
                "description": "Customer engineering requirements (free-form key/value pairs)",
            },
            "kbe_rules": {
                "type": "array",
                "description": (
                    "KBE derivation rules.  Each rule is an object with: "
                    "id, description, domain, condition_keys (list of option keys that must be set), "
                    "derive (dict of param_key→expr_string), "
                    "select (optional: {param, table: [[threshold, sku], ...], default})."
                ),
                "items": {"type": "object"},
            },
            "configurator_rules": {
                "type": "array",
                "description": (
                    "Configurator variant rules.  Each rule is an object with: "
                    "id, description, domain, condition_expr (Python bool expr with 'state'), "
                    "effect (list of action dicts: {action_type, sku/param_key, quantity/param_value, "
                    "provenance, hard_constraint})."
                ),
                "items": {"type": "object"},
            },
            "eco_table": {
                "type": "array",
                "description": (
                    "Optional ECO/ECR records for BOM effectivity filtering. "
                    "Each record: {old_sku, new_sku, effective_from (ISO date), eco_id}."
                ),
                "items": {"type": "object"},
            },
            "effective_date": {
                "type": "string",
                "description": "ISO date (YYYY-MM-DD) for effectivity; omit to skip filtering.",
            },
        },
        "required": ["options", "kbe_rules", "configurator_rules"],
    },
}


# ---------------------------------------------------------------------------
# ToolSpec + async handler for ctx.tools.register
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx

    plm_kbe_configure_spec = ToolSpec(
        name="plm_kbe_configure",
        description=TOOL_SCHEMA["description"],
        input_schema=TOOL_SCHEMA["input_schema"],
    )

    async def run_plm_kbe_configure(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args) if args else {}
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        options = a.get("options")
        kbe_rules = a.get("kbe_rules")
        cfg_rules = a.get("configurator_rules")

        if not isinstance(options, dict):
            return err_payload("'options' must be an object", "BAD_ARGS")
        if not isinstance(kbe_rules, list):
            return err_payload("'kbe_rules' must be an array", "BAD_ARGS")
        if not isinstance(cfg_rules, list):
            return err_payload("'configurator_rules' must be an array", "BAD_ARGS")

        try:
            result = plm_kbe_configure_tool(
                options=options,
                kbe_rules=kbe_rules,
                configurator_rules=cfg_rules,
                eco_table=a.get("eco_table"),
                effective_date=a.get("effective_date", ""),
            )
        except Exception as exc:
            return err_payload(str(exc), "PLM_KBE_ERROR")

        return ok_payload(result)

    TOOLS = [
        (plm_kbe_configure_spec.name, plm_kbe_configure_spec, run_plm_kbe_configure),
    ]

except ImportError:
    TOOLS = []
