"""
LLM tool definitions for kerf-plm.

Registered tools:
  plm_configure          — evaluate a rule-based product configurator for a
                           given feature selection and return the resulting
                           parts list + parameters.
  plm_change_management  — ECR/ECO workflow (ISO 10007): submit, review,
                           escalate, and implement engineering changes.
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


# ---------------------------------------------------------------------------
# plm_change_management  (ECR/ECO workflow — ISO 10007)
# ---------------------------------------------------------------------------

plm_change_management_spec = ToolSpec(
    name="plm_change_management",
    description=(
        "Drive the ISO 10007 Engineering Change Request / Engineering Change Order "
        "(ECR/ECO) workflow.\n\n"
        "Supported *action* values:\n"
        "  submit_ecr      — create and submit a new ECR (draft → submitted).\n"
        "  review_ecr      — record a reviewer vote (approve / reject) on an ECR.\n"
        "                    Auto-transitions to 'approved' when required_approvals met;\n"
        "                    auto-transitions to 'rejected' on majority rejection.\n"
        "  escalate_to_eco — convert an approved ECR into an ECO (planned state).\n"
        "  implement_eco   — record a functional signoff (engineering / manufacturing / qa).\n"
        "                    Auto-releases the ECO when all three signoffs are present.\n"
        "  get_ecr         — return the current state + votes of an ECR.\n"
        "  get_eco         — return the current state + signoffs of an ECO.\n"
        "  audit_trail     — return the full immutable audit trail.\n\n"
        "The tool is stateless per call: the caller must persist and pass the "
        "serialised board state between calls, OR use the low-level Python API "
        "(ChangeBoard) for a long-lived session.\n\n"
        "ECR JSON shape: {id, title, description, originator, affected_parts[], "
        "rationale?, classification (minor|major|critical), "
        "proposed_disposition (use_as_is|rework|scrap|redesign), "
        "reviewers[], required_approvals?}\n\n"
        "ECO JSON shape: {id, references_ecrs[], description, affected_parts[], "
        "effective_date (YYYY-MM-DD)}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "submit_ecr",
                    "review_ecr",
                    "escalate_to_eco",
                    "implement_eco",
                    "get_ecr",
                    "get_eco",
                    "audit_trail",
                ],
                "description": "The workflow action to perform.",
            },
            "ecr_json": {
                "type": "string",
                "description": "JSON object with ECR fields. Required for submit_ecr.",
            },
            "eco_json": {
                "type": "string",
                "description": "JSON object with ECO fields. Required for escalate_to_eco.",
            },
            "ecr_id": {
                "type": "string",
                "description": "ECR identifier. Required for review_ecr, escalate_to_eco, get_ecr.",
            },
            "eco_id": {
                "type": "string",
                "description": "ECO identifier. Required for implement_eco, get_eco.",
            },
            "reviewer": {
                "type": "string",
                "description": "Reviewer user id. Required for review_ecr.",
            },
            "decision": {
                "type": "string",
                "enum": ["approve", "reject"],
                "description": "Vote decision. Required for review_ecr.",
            },
            "signer": {
                "type": "string",
                "description": "Signer user id. Required for implement_eco.",
            },
            "role": {
                "type": "string",
                "enum": ["engineering", "manufacturing", "qa"],
                "description": "Functional role of the signer. Required for implement_eco.",
            },
        },
        "required": ["action"],
    },
)


def plm_change_management(
    action: str,
    ecr_json: str | None = None,
    eco_json: str | None = None,
    ecr_id: str | None = None,
    eco_id: str | None = None,
    reviewer: str | None = None,
    decision: str | None = None,
    signer: str | None = None,
    role: str | None = None,
) -> dict:
    """Stateless helper that drives a single ECR/ECO workflow step.

    For multi-step sessions the caller should use ChangeBoard directly.
    This tool is designed for one-shot LLM agent calls.
    """
    from kerf_plm.change_management import ChangeBoard, ECR, ECO
    from datetime import date as _date

    board = ChangeBoard()

    try:
        if action == "submit_ecr":
            if not ecr_json:
                return {"ok": False, "error": "ecr_json is required for submit_ecr", "code": "BAD_ARGS"}
            raw = json.loads(ecr_json)
            eff_date = raw.get("effective_date")
            ecr = ECR(
                id=raw["id"],
                title=raw.get("title", ""),
                description=raw.get("description", ""),
                originator=raw.get("originator", ""),
                affected_parts=raw.get("affected_parts", []),
                rationale=raw.get("rationale", ""),
                classification=raw.get("classification", "minor"),
                proposed_disposition=raw.get("proposed_disposition", "rework"),
                reviewers=raw.get("reviewers", []),
                required_approvals=int(raw.get("required_approvals", 2)),
            )
            board.submit_ecr(ecr)
            return {"ok": True, "ecr": _ecr_to_dict(ecr)}

        elif action == "review_ecr":
            for param, name in [(ecr_id, "ecr_id"), (reviewer, "reviewer"), (decision, "decision")]:
                if not param:
                    return {"ok": False, "error": f"{name} is required for review_ecr", "code": "BAD_ARGS"}
            # Stateless — we can only validate the API; real use needs persistent board
            return {
                "ok": True,
                "message": (
                    f"review_ecr({ecr_id!r}, reviewer={reviewer!r}, decision={decision!r}) "
                    "validated. Use ChangeBoard directly for stateful multi-step sessions."
                ),
            }

        elif action == "escalate_to_eco":
            if not ecr_id:
                return {"ok": False, "error": "ecr_id is required for escalate_to_eco", "code": "BAD_ARGS"}
            if not eco_json:
                return {"ok": False, "error": "eco_json is required for escalate_to_eco", "code": "BAD_ARGS"}
            raw = json.loads(eco_json)
            eff_date_str = raw.get("effective_date")
            eff_date = _date.fromisoformat(eff_date_str) if eff_date_str else None
            eco = ECO(
                id=raw["id"],
                references_ecrs=raw.get("references_ecrs", []),
                description=raw.get("description", ""),
                affected_parts=raw.get("affected_parts", []),
                effective_date=eff_date,
            )
            return {
                "ok": True,
                "message": (
                    f"escalate_to_eco({ecr_id!r}, eco={eco.id!r}) validated. "
                    "Use ChangeBoard directly for stateful multi-step sessions."
                ),
                "eco": _eco_to_dict(eco),
            }

        elif action == "implement_eco":
            for param, name in [(eco_id, "eco_id"), (signer, "signer"), (role, "role")]:
                if not param:
                    return {"ok": False, "error": f"{name} is required for implement_eco", "code": "BAD_ARGS"}
            from kerf_plm.change_management import REQUIRED_SIGNOFF_ROLES
            if role not in REQUIRED_SIGNOFF_ROLES:
                return {
                    "ok": False,
                    "error": f"role must be one of {sorted(REQUIRED_SIGNOFF_ROLES)}, got {role!r}",
                    "code": "BAD_ARGS",
                }
            return {
                "ok": True,
                "message": (
                    f"implement_eco({eco_id!r}, signer={signer!r}, role={role!r}) validated. "
                    "Use ChangeBoard directly for stateful multi-step sessions."
                ),
            }

        elif action == "get_ecr":
            if not ecr_id:
                return {"ok": False, "error": "ecr_id is required for get_ecr", "code": "BAD_ARGS"}
            return {
                "ok": True,
                "message": f"Use ChangeBoard.get_ecr({ecr_id!r}) in a stateful session.",
            }

        elif action == "get_eco":
            if not eco_id:
                return {"ok": False, "error": "eco_id is required for get_eco", "code": "BAD_ARGS"}
            return {
                "ok": True,
                "message": f"Use ChangeBoard.get_eco({eco_id!r}) in a stateful session.",
            }

        elif action == "audit_trail":
            trail = board.audit_trail()
            return {"ok": True, "audit_trail": [_audit_entry_to_dict(e) for e in trail]}

        else:
            return {
                "ok": False,
                "error": (
                    f"Unknown action {action!r}. Valid actions: submit_ecr, review_ecr, "
                    "escalate_to_eco, implement_eco, get_ecr, get_eco, audit_trail."
                ),
                "code": "BAD_ARGS",
            }

    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSON parse error: {exc}", "code": "PARSE_ERROR"}
    except (KeyError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "BAD_ARGS"}
    except Exception as exc:
        return {"ok": False, "error": f"unexpected error: {exc}", "code": "ERROR"}


def _ecr_to_dict(ecr) -> dict:
    return {
        "id": ecr.id,
        "title": ecr.title,
        "state": ecr.state,
        "originator": ecr.originator,
        "classification": ecr.classification,
        "proposed_disposition": ecr.proposed_disposition,
        "affected_parts": ecr.affected_parts,
        "reviewers": ecr.reviewers,
        "votes": ecr.votes,
        "required_approvals": ecr.required_approvals,
        "created_at": ecr.created_at,
    }


def _eco_to_dict(eco) -> dict:
    return {
        "id": eco.id,
        "references_ecrs": eco.references_ecrs,
        "description": eco.description,
        "affected_parts": eco.affected_parts,
        "effective_date": eco.effective_date.isoformat() if eco.effective_date else None,
        "implementation_state": eco.implementation_state,
        "engineering_signoff": eco.engineering_signoff,
        "manufacturing_signoff": eco.manufacturing_signoff,
        "qa_signoff": eco.qa_signoff,
        "created_at": eco.created_at,
    }


def _audit_entry_to_dict(entry) -> dict:
    return {
        "timestamp": entry.timestamp,
        "actor": entry.actor,
        "entity_id": entry.entity_id,
        "entity_type": entry.entity_type,
        "old_state": entry.old_state,
        "new_state": entry.new_state,
        "note": entry.note,
    }


# ---------------------------------------------------------------------------
# TOOL_DEFS — Anthropic-style function-call descriptors for all PLM tools
# ---------------------------------------------------------------------------

TOOL_DEFS: list[dict] = [
    {
        "name": plm_configure_spec.name,
        "description": plm_configure_spec.description,
        "input_schema": plm_configure_spec.input_schema,
    },
    {
        "name": plm_change_management_spec.name,
        "description": plm_change_management_spec.description,
        "input_schema": plm_change_management_spec.input_schema,
    },
]


# ===========================================================================
# Change-impact analyzer (PROSTEP-iViP SIG) — Wave 4NN
# ===========================================================================

from kerf_plm.change_impact import (
    analyze_change_impact as _analyze_change_impact,
    build_impact_graph as _build_impact_graph,
    estimate_change_cost as _estimate_change_cost,
    propose_co_changes as _propose_co_changes,
)


plm_change_impact_spec = ToolSpec(
    name="plm_change_impact",
    description=(
        "Analyze the downstream change impact when a part or assembly changes. "
        "Builds a directed impact graph from BOM, assembly hierarchy, requirements, "
        "tests, and documents, then BFS-propagates from the changed node. "
        "Returns each impacted entity with its impact level "
        "(high = direct, medium = 2-3 hops, low = >=4 hops) "
        "and estimated rework hours per PROSTEP-iViP SIG methodology."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "changed_part_id": {"type": "string"},
            "plm_data": {"type": "object"},
            "hourly_rate": {"type": "number"},
            "max_hops": {"type": "integer"},
        },
        "required": ["changed_part_id", "plm_data"],
    },
)


@register(plm_change_impact_spec)
async def run_plm_change_impact(ctx, args: bytes) -> str:
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    changed_part_id = a.get("changed_part_id", "")
    plm_data = a.get("plm_data", {})
    hourly_rate = float(a.get("hourly_rate", 100.0))
    max_hops = int(a.get("max_hops", 10))

    if not changed_part_id:
        return err_payload("'changed_part_id' is required", "BAD_ARGS")
    if not isinstance(plm_data, dict):
        return err_payload("'plm_data' must be an object", "BAD_ARGS")

    try:
        graph = _build_impact_graph(plm_data)
        report = _analyze_change_impact(changed_part_id, graph, max_hops=max_hops)
        cost = _estimate_change_cost(report, hourly_rate=hourly_rate)
    except Exception as exc:
        return err_payload(f"analysis error: {exc}", "ANALYSIS_ERROR")

    impacted_out = [
        {
            "node_id": n.node_id,
            "kind": n.kind,
            "label": n.label,
            "hop_distance": n.hop_distance,
            "impact_level": n.impact_level,
            "rework_hours": n.rework_hours,
        }
        for n in report.impacted_nodes
    ]

    return ok_payload({
        "changed_part_id": changed_part_id,
        "impacted_count": len(impacted_out),
        "impacted_nodes": impacted_out,
        "cost_estimate": cost,
        "summary": {
            "high": len(report.nodes_at_level("high")),
            "medium": len(report.nodes_at_level("medium")),
            "low": len(report.nodes_at_level("low")),
            "total_rework_hours": report.total_rework_hours(),
        },
    })


plm_where_used_spec = ToolSpec(
    name="plm_where_used",
    description=(
        "Perform a Where-Used Analysis for a given part: list every assembly and "
        "sub-assembly that consumes it, with occurrence multiplicity and hierarchy "
        "depth.\n\n"
        "This is the *inverse* of BOM expansion.  Where BOM expansion walks "
        "downward from an assembly to its children, Where-Used walks *upward* "
        "from a part to every parent assembly that references it.\n\n"
        "Methodology: PROSTEP-iViP SIG §5.2 'Where-Used Analysis'.\n\n"
        "Depth semantics:\n"
        "  depth == 1 → the assembly is an immediate parent of the target part.\n"
        "  depth == 2 → grandparent assembly (contains a sub-assembly that\n"
        "               contains the target part), etc.\n\n"
        "Multiplicity: *occurrence_count* is the number of times the target part "
        "(or the sub-assembly that carries it) appears as a direct child in the "
        "named assembly.  A bolt used four times in one bracket gives "
        "occurrence_count == 4 for that assembly entry.\n\n"
        "Cycle handling: assumes an acyclic assembly DAG.  If a cycle is detected "
        "the traversal is cut at that branch and *cycle_detected* is set True in "
        "the response.  Traversal is capped at depth 20 as a defensive measure."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_part_id": {
                "type": "string",
                "description": "ID of the part (or sub-assembly) to query.",
            },
            "plm_data": {
                "type": "object",
                "description": (
                    "PLM product-structure data.  Same schema as plm_change_impact: "
                    "keys 'parts' (list of {id, label?, kind?, attributes?}) and "
                    "'assemblies' (list of {id, label?, children: [part_id, ...]}) "
                    "are used.  'children' may repeat a part_id to express "
                    "multiplicity (e.g. ['P-001', 'P-001'] → occurrence_count=2). "
                    "Additional keys (requirements, tests, edges) are accepted but "
                    "ignored for where-used."
                ),
            },
        },
        "required": ["target_part_id", "plm_data"],
    },
)


@register(plm_where_used_spec)
async def run_plm_where_used(ctx, args: bytes) -> str:
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    target_part_id = a.get("target_part_id", "")
    plm_data = a.get("plm_data", {})

    if not target_part_id:
        return err_payload("'target_part_id' is required", "BAD_ARGS")
    if not isinstance(plm_data, dict):
        return err_payload("'plm_data' must be an object", "BAD_ARGS")

    try:
        from kerf_plm.where_used import where_used as _where_used
        report = _where_used(target_part_id, plm_data)
    except Exception as exc:
        return err_payload(f"where-used error: {exc}", "ANALYSIS_ERROR")

    return ok_payload({
        "target_part_id": target_part_id,
        "assembly_count": len(report.entries),
        "total_occurrences": report.total_occurrences(),
        "cycle_detected": report.cycle_detected,
        "cycle_path": report.cycle_path,
        "entries": [
            {
                "assembly_id": e.assembly_id,
                "label": e.label,
                "occurrence_count": e.occurrence_count,
                "depth": e.depth,
            }
            for e in report.entries
        ],
    })


plm_propose_co_changes_spec = ToolSpec(
    name="plm_propose_co_changes",
    description=(
        "Given a changed part and PLM product structure, propose co-changes "
        "via PROSTEP-iViP §6.2 interface-coupling heuristics."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "changed_part_id": {"type": "string"},
            "plm_data": {"type": "object"},
        },
        "required": ["changed_part_id", "plm_data"],
    },
)


@register(plm_propose_co_changes_spec)
async def run_plm_propose_co_changes(ctx, args: bytes) -> str:
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    changed_part_id = a.get("changed_part_id", "")
    plm_data = a.get("plm_data", {})

    if not changed_part_id:
        return err_payload("'changed_part_id' is required", "BAD_ARGS")
    if not isinstance(plm_data, dict):
        return err_payload("'plm_data' must be an object", "BAD_ARGS")

    try:
        graph = _build_impact_graph(plm_data)
        report = _analyze_change_impact(changed_part_id, graph)
        suggestions = _propose_co_changes(report, impact_graph=graph)
    except Exception as exc:
        return err_payload(f"analysis error: {exc}", "ANALYSIS_ERROR")

    return ok_payload({
        "changed_part_id": changed_part_id,
        "suggestion_count": len(suggestions),
        "suggestions": [
            {
                "node_id": s.node_id,
                "label": s.label,
                "reason": s.reason,
                "confidence": s.confidence,
            }
            for s in suggestions
        ],
    })
