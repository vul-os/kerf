"""
LLM tool definitions for kerf-plm.

Registered tool:
  plm_configure  — evaluate a rule-based product configurator for a
                   given feature selection and return the resulting
                   parts list + parameters.
"""

from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_plm._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# plm_configure
# ---------------------------------------------------------------------------

plm_configure_spec = ToolSpec(
    name="plm_configure",
    description=(
        "Evaluate a rule-based PLM product configurator for a given feature selection.\n\n"
        "Supply a *rules* list (each rule has a Python-expression condition string "
        "and a list of actions) together with an *options* map and a *selection*. "
        "Returns the resolved parts list, parameter overrides, and any errors.\n\n"
        "Action kinds: include_part, exclude_part, set_param, raise_constraint.\n"
        "Conflict detection: two rules forcing include AND exclude on the same part "
        "raise a ConfigConflict error.\n\n"
        "Also supports effectivity-date BOM filtering when *effective_date* is provided "
        "(ISO-8601 date string, e.g. '2025-01-01')."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "rules": {
                "type": "array",
                "description": (
                    "List of rule objects. Each rule has:\n"
                    "  condition_expr: Python expression (string) evaluated against "
                    "the selection dict (available as `s`). Example: \"s.get('engine')=='V8'\"\n"
                    "  effect: list of action objects\n"
                    "  priority: integer (lower = higher priority, default 100)\n"
                    "  name: optional label"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "condition_expr": {
                            "type": "string",
                            "description": "Python boolean expression; selection available as `s`.",
                        },
                        "effect": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": [
                                            "include_part",
                                            "exclude_part",
                                            "set_param",
                                            "raise_constraint",
                                        ],
                                    },
                                    "part_id": {"type": "string"},
                                    "param": {"type": "string"},
                                    "value": {},
                                },
                                "required": ["kind"],
                            },
                        },
                        "priority": {"type": "integer", "default": 100},
                        "name": {"type": "string", "default": ""},
                    },
                    "required": ["condition_expr", "effect"],
                },
            },
            "options": {
                "type": "object",
                "description": (
                    "Map of feature → [allowed values]. "
                    "Example: {\"colour\": [\"red\", \"blue\"], \"engine\": [\"V6\", \"V8\"]}"
                ),
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "selection": {
                "type": "object",
                "description": "Feature → value map representing the customer's choice.",
                "additionalProperties": {"type": "string"},
            },
            "effective_date": {
                "type": "string",
                "description": (
                    "ISO-8601 date (YYYY-MM-DD). When provided, the returned parts list "
                    "will also be filtered through an effectivity-BOM check against a "
                    "supplied *parts_catalogue*."
                ),
            },
            "parts_catalogue": {
                "type": "array",
                "description": (
                    "Optional 150% parts catalogue. Each entry: "
                    "{part_id, description, effective_from?, effective_to?}. "
                    "Used together with *effective_date* to filter the resolved "
                    "parts list to only effectivity-valid parts."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "part_id": {"type": "string"},
                        "description": {"type": "string"},
                        "effective_from": {"type": "string"},
                        "effective_to": {"type": "string"},
                    },
                    "required": ["part_id"],
                },
            },
        },
        "required": ["rules", "options", "selection"],
    },
)


def _build_rule(raw: dict):
    """Convert a JSON rule dict into a kerf_plm.configurator.Rule."""
    from kerf_plm.configurator import Rule, Action, ActionKind

    expr = raw.get("condition_expr", "False")
    # Compile the expression with a restricted namespace (only `s` is exposed)
    compiled = compile(expr, "<rule-condition>", "eval")

    def condition(s: dict, _code=compiled) -> bool:
        return bool(eval(_code, {"__builtins__": {}}, {"s": s}))  # noqa: S307

    actions = []
    for a in raw.get("effect", []):
        kind_str = a.get("kind", "")
        try:
            kind = ActionKind[kind_str.upper()]
        except KeyError:
            continue
        actions.append(Action(
            kind=kind,
            part_id=a.get("part_id"),
            param=a.get("param"),
            value=a.get("value"),
        ))

    return Rule(
        condition=condition,
        effect=actions,
        priority=int(raw.get("priority", 100)),
        name=raw.get("name", ""),
    )


@register(plm_configure_spec)
async def run_plm_configure(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    raw_rules = a.get("rules")
    options = a.get("options")
    selection = a.get("selection")

    if not isinstance(raw_rules, list):
        return err_payload("'rules' must be a list", "BAD_ARGS")
    if not isinstance(options, dict):
        return err_payload("'options' must be an object", "BAD_ARGS")
    if not isinstance(selection, dict):
        return err_payload("'selection' must be an object", "BAD_ARGS")

    from kerf_plm.configurator import (
        Configurator, ConfigConflict, ConstraintViolation, effectivity_bom, Part
    )

    # Build rules
    try:
        rules = [_build_rule(r) for r in raw_rules]
    except Exception as e:
        return err_payload(f"rule build error: {e}", "BAD_ARGS")

    cfg = Configurator(rules=rules, options=options)

    try:
        result = cfg.configure(selection)
    except ConstraintViolation as e:
        return err_payload(str(e), "CONSTRAINT_VIOLATION")
    except ConfigConflict as e:
        return err_payload(str(e), "CONFIG_CONFLICT")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(f"configurator error: {e}", "ERROR")

    parts_list = result.parts

    # Effectivity filtering (optional)
    effective_date_str = a.get("effective_date")
    catalogue = a.get("parts_catalogue")
    if effective_date_str and catalogue:
        from datetime import date as _date
        try:
            eff_date = _date.fromisoformat(effective_date_str)
        except ValueError as e:
            return err_payload(f"invalid effective_date: {e}", "BAD_ARGS")

        # Build Part objects from catalogue, limited to parts in result
        catalogue_map = {p["part_id"]: p for p in catalogue}
        bom_parts = []
        for pid in parts_list:
            raw_part = catalogue_map.get(pid)
            if raw_part is None:
                # Part not in catalogue — include without effectivity filter
                bom_parts.append(Part(part_id=pid))
                continue
            eff_from = None
            eff_to = None
            if raw_part.get("effective_from"):
                try:
                    eff_from = _date.fromisoformat(raw_part["effective_from"])
                except ValueError:
                    pass
            if raw_part.get("effective_to"):
                try:
                    eff_to = _date.fromisoformat(raw_part["effective_to"])
                except ValueError:
                    pass
            bom_parts.append(Part(
                part_id=pid,
                description=raw_part.get("description", ""),
                effective_from=eff_from,
                effective_to=eff_to,
            ))

        effective_parts = effectivity_bom(bom_parts, eff_date)
        parts_list = [p.part_id for p in effective_parts]

    return ok_payload({
        "parts": parts_list,
        "params": result.params,
        "errors": result.errors,
        "iterations": result.iterations,
    })
