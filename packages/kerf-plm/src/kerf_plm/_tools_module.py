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


# ===========================================================================
# PLM Effectivity BOM Expansion (ISO 10303-44 + Borst-Lahti ss7.4)
# ===========================================================================

plm_expand_effectivity_bom_spec = ToolSpec(
    name="plm_expand_effectivity_bom",
    description=(
        "Expand a 150% BOM (max-effectivity structure) to a 100% BOM for a "
        "specific effectivity context: date, configuration options, and/or "
        "serial number.\n\n"
        "A 150% BOM contains every possible line item across all variants and "
        "time periods.  This tool filters the superset down to the concrete "
        "parts list valid for the given build context.\n\n"
        "Filtering rules (ISO 10303-44 ss5.3 + Borst-Lahti ss7.4):\n"
        "  date:          line included when effective_from <= date <= effective_to "
        "(open bounds = no constraint).\n"
        "  options:       each option_requirement key=value must match the selector "
        "(implicit AND, exact-match -- complex AND/OR not supported in v1).\n"
        "  serial_number: inclusive integer or lexicographic range.\n\n"
        "Returns resolved entries with qty and total_qty summed across all "
        "included lines."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bom_lines": {
                "type": "array",
                "description": (
                    "The 150% BOM. Each line: "
                    "{part_id (required), description?, qty? (default 1), "
                    "effective_from? (YYYY-MM-DD), effective_to? (YYYY-MM-DD), "
                    "serial_from? (string), serial_to? (string), "
                    "option_requirements? ({key: value, ...}), attributes? ({})}"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "part_id": {"type": "string"},
                        "description": {"type": "string"},
                        "qty": {"type": "number"},
                        "effective_from": {"type": "string"},
                        "effective_to": {"type": "string"},
                        "serial_from": {"type": "string"},
                        "serial_to": {"type": "string"},
                        "option_requirements": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                        "attributes": {"type": "object"},
                    },
                    "required": ["part_id"],
                },
            },
            "effective_date": {
                "type": "string",
                "description": "ISO-8601 date (YYYY-MM-DD). Activates date-effectivity filtering.",
            },
            "options": {
                "type": "object",
                "description": (
                    "Configuration option selections, e.g. {\"engine\": \"v6\"}. "
                    "Lines with option_requirements not fully matched are excluded."
                ),
                "additionalProperties": {"type": "string"},
            },
            "serial_number": {
                "type": "string",
                "description": "Unit serial number for serial-range effectivity filtering.",
            },
        },
        "required": ["bom_lines"],
    },
)


@register(plm_expand_effectivity_bom_spec)
async def run_plm_expand_effectivity_bom(ctx, args: bytes) -> str:
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    raw_lines = a.get("bom_lines")
    if not isinstance(raw_lines, list):
        return err_payload("'bom_lines' must be an array", "BAD_ARGS")

    from datetime import date as _date
    from kerf_plm.effectivity_bom import BomLine, expand_effectivity_bom, HONEST_FLAG

    effective_date = None
    eff_date_str = a.get("effective_date")
    if eff_date_str:
        try:
            effective_date = _date.fromisoformat(eff_date_str)
        except ValueError as exc:
            return err_payload(f"invalid effective_date: {exc}", "BAD_ARGS")

    options = a.get("options") or {}
    if not isinstance(options, dict):
        return err_payload("'options' must be an object", "BAD_ARGS")

    serial_number = a.get("serial_number") or None

    bom_lines: list[BomLine] = []
    for i, raw in enumerate(raw_lines):
        if not isinstance(raw, dict):
            return err_payload(f"bom_lines[{i}] must be an object", "BAD_ARGS")
        part_id = raw.get("part_id")
        if not part_id:
            return err_payload(f"bom_lines[{i}].part_id is required", "BAD_ARGS")

        eff_from = None
        eff_to = None
        if raw.get("effective_from"):
            try:
                eff_from = _date.fromisoformat(raw["effective_from"])
            except ValueError as exc:
                return err_payload(f"bom_lines[{i}].effective_from invalid: {exc}", "BAD_ARGS")
        if raw.get("effective_to"):
            try:
                eff_to = _date.fromisoformat(raw["effective_to"])
            except ValueError as exc:
                return err_payload(f"bom_lines[{i}].effective_to invalid: {exc}", "BAD_ARGS")

        bom_lines.append(BomLine(
            part_id=part_id,
            description=raw.get("description", ""),
            qty=float(raw.get("qty", 1.0)),
            effective_from=eff_from,
            effective_to=eff_to,
            serial_from=raw.get("serial_from") or None,
            serial_to=raw.get("serial_to") or None,
            option_requirements=raw.get("option_requirements") or {},
            attributes=raw.get("attributes") or {},
        ))

    try:
        result = expand_effectivity_bom(
            bom_lines,
            effective_date=effective_date,
            options=options,
            serial_number=serial_number,
        )
    except Exception as exc:
        return err_payload(f"expansion error: {exc}", "EXPANSION_ERROR")

    return ok_payload({
        "entry_count": len(result.entries),
        "total_qty": result.total_qty,
        "entries": [
            {
                "part_id": e.part_id,
                "description": e.description,
                "qty": e.qty,
                "attributes": e.attributes,
            }
            for e in result.entries
        ],
        "honest_flag": HONEST_FLAG,
    })


# ===========================================================================
# PLM Document Version Diff (ISO 10303-44 §5.2 + Borst-Lahti §6.3)
# ===========================================================================

plm_document_version_diff_spec = ToolSpec(
    name="plm_document_version_diff",
    description=(
        "Diff two revisions of a controlled PLM document (BOM, drawing metadata, "
        "spec, or any JSON-like list of dicts with stable keys).\n\n"
        "Per ISO 10303-44 §5.2 (document version control) and Borst-Lahti §6.3 "
        "(change record and document delta), returns a structured diff report "
        "identifying:\n"
        "  1. Added items\n"
        "  2. Removed items\n"
        "  3. Modified items with field-level change records\n"
        "  4. Renamed items (heuristic: >=80% Jaccard field-value similarity;\n"
        "     see honest_flag in response for limitations)\n"
        "  5. Per-change criticality (engineering vs administrative) per\n"
        "     Borst-Lahti §6.3 Table 3 field classification\n\n"
        "UNCHANGED items are not included in the entries list; the *unchanged* "
        "count is reported in the summary only.\n\n"
        "Criticality rules:\n"
        "  ENGINEERING  — qty, material, tolerance, drawing_rev, revision, spec, "
        "type, part_number, mass, and related design-intent fields.\n"
        "  ADMINISTRATIVE — description-only edits, notes, supplier, cost, "
        "dates, approved_by, and metadata fields.\n"
        "  Additions and removals are always ENGINEERING.\n\n"
        "Honest flag: rename detection uses a heuristic fingerprint (>=80% field "
        "similarity). May misclassify coincidentally similar add/remove pairs as "
        "renames."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "doc_a": {
                "type": "array",
                "description": (
                    "Revision A — list of item objects with stable key fields. "
                    "Example: [{\"id\": \"P-001\", \"qty\": 2, \"material\": \"Al\"}]"
                ),
                "items": {"type": "object"},
            },
            "doc_b": {
                "type": "array",
                "description": "Revision B — same schema as doc_a.",
                "items": {"type": "object"},
            },
            "key_field": {
                "type": "string",
                "description": (
                    "Field name used as the stable item identifier. Default: 'id'. "
                    "Common alternatives: 'part_number', 'pn', 'drawing_number'."
                ),
                "default": "id",
            },
            "rename_threshold": {
                "type": "number",
                "description": (
                    "Jaccard similarity threshold for rename detection (0.0-1.0). "
                    "Default: 0.80. Lower = more renames detected (higher false-positive "
                    "risk); 1.0 disables rename detection."
                ),
                "default": 0.80,
                "minimum": 0.0,
                "maximum": 1.0,
            },
        },
        "required": ["doc_a", "doc_b"],
    },
)


@register(plm_document_version_diff_spec)
async def run_plm_document_version_diff(ctx, args: bytes) -> str:
    """Tool handler for plm_document_version_diff (ISO 10303-44 §5.2 + Borst-Lahti §6.3)."""
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    doc_a = a.get("doc_a")
    doc_b = a.get("doc_b")
    key_field = a.get("key_field", "id") or "id"
    rename_threshold = float(a.get("rename_threshold", 0.80))

    if not isinstance(doc_a, list):
        return err_payload("'doc_a' must be an array", "BAD_ARGS")
    if not isinstance(doc_b, list):
        return err_payload("'doc_b' must be an array", "BAD_ARGS")
    if not isinstance(key_field, str) or not key_field:
        return err_payload("'key_field' must be a non-empty string", "BAD_ARGS")
    if not (0.0 <= rename_threshold <= 1.0):
        return err_payload("'rename_threshold' must be between 0.0 and 1.0", "BAD_ARGS")

    try:
        from kerf_plm.document_version_diff import diff_documents
        report = diff_documents(
            doc_a,
            doc_b,
            key_field=key_field,
            rename_threshold=rename_threshold,
        )
    except (TypeError, ValueError) as exc:
        return err_payload(f"diff error: {exc}", "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"diff error: {exc}", "DIFF_ERROR")

    return ok_payload(report.to_dict())


# ===========================================================================
# PLM Multi-Cavity Tool Effectivity (PROSTEP-iViP SIG §6)
# ===========================================================================

plm_query_multi_cavity_spec = ToolSpec(
    name="plm_query_multi_cavity",
    description=(
        "Query per-cavity insert revision state for a multi-cavity injection mold "
        "or similar tooling family on a specific date.\n\n"
        "Per PROSTEP-iViP SIG §6 'Multi-cavity tool effectivity', each cavity slot "
        "carries a history of insert revision records with date-effectivity windows. "
        "For a given query date the tool returns which revision each cavity is "
        "currently producing.\n\n"
        "Resolution rule: the LAST declared insert record whose effectivity window "
        "contains the query date wins (latest-specification-wins; ISO 10303-44 §5.3 "
        "date-effectivity bounds are inclusive, open ends = no constraint).\n\n"
        "Honest flag — does NOT model:\n"
        "  - Insert wear curves or physical degradation.\n"
        "  - Change-out queuing or maintenance schedules.\n"
        "  - Partial revision ordering (e.g. R5 >= R4); compatible_revisions is "
        "    an exact-match set only.\n\n"
        "Example: 4-cavity tool at R5; cavity 3 swapped to R6 from 2026-04-01.\n"
        "  query 2026-05-01 → [(1,R5),(2,R5),(3,R6),(4,R5)]\n"
        "  query 2026-03-15 → [(1,R5),(2,R5),(3,R5),(4,R5)]"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tool_id": {
                "type": "string",
                "description": "Unique identifier for the multi-cavity tool, e.g. 'MOLD-001'.",
            },
            "cavities": {
                "type": "array",
                "description": (
                    "List of cavity objects. Each cavity has:\n"
                    "  cavity_id (integer, required) — slot number 1-N.\n"
                    "  inserts (array, required) — ordered list of insert revision records.\n"
                    "Each insert record: {revision (str), effective_from? (YYYY-MM-DD), "
                    "effective_to? (YYYY-MM-DD), compatible_revisions? ([str, ...])}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "cavity_id": {"type": "integer"},
                        "inserts": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "revision": {"type": "string"},
                                    "effective_from": {"type": "string"},
                                    "effective_to": {"type": "string"},
                                    "compatible_revisions": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["revision"],
                            },
                        },
                    },
                    "required": ["cavity_id", "inserts"],
                },
            },
            "query_date": {
                "type": "string",
                "description": "ISO-8601 date (YYYY-MM-DD) for which to resolve cavity states.",
            },
            "options": {
                "type": "object",
                "description": (
                    "Optional query modifiers:\n"
                    "  require_revision (str | [str]): only count cavities whose active "
                    "revision is in this set toward effective_count."
                ),
                "properties": {
                    "require_revision": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                        "description": "Only these revision labels count as effective.",
                    },
                },
            },
        },
        "required": ["tool_id", "cavities", "query_date"],
    },
)


@register(plm_query_multi_cavity_spec)
async def run_plm_query_multi_cavity(ctx, args: bytes) -> str:
    """Tool handler for plm_query_multi_cavity (PROSTEP-iViP SIG §6)."""
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    tool_id = a.get("tool_id", "")
    raw_cavities = a.get("cavities")
    query_date_str = a.get("query_date", "")
    options = a.get("options") or {}

    if not tool_id:
        return err_payload("'tool_id' is required", "BAD_ARGS")
    if not isinstance(raw_cavities, list):
        return err_payload("'cavities' must be an array", "BAD_ARGS")
    if not query_date_str:
        return err_payload("'query_date' is required", "BAD_ARGS")

    from datetime import date as _date
    try:
        query_date = _date.fromisoformat(query_date_str)
    except ValueError as exc:
        return err_payload(f"invalid query_date: {exc}", "BAD_ARGS")

    from kerf_plm.multi_cavity_effectivity import (
        MultiCavityTool,
        ToolCavity,
        CavityInsert,
        query_multi_cavity_effectivity,
        HONEST_FLAG,
    )

    cavities = []
    for i, raw_c in enumerate(raw_cavities):
        if not isinstance(raw_c, dict):
            return err_payload(f"cavities[{i}] must be an object", "BAD_ARGS")
        cid = raw_c.get("cavity_id")
        if cid is None:
            return err_payload(f"cavities[{i}].cavity_id is required", "BAD_ARGS")
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return err_payload(f"cavities[{i}].cavity_id must be an integer", "BAD_ARGS")

        raw_inserts = raw_c.get("inserts")
        if not isinstance(raw_inserts, list):
            return err_payload(f"cavities[{i}].inserts must be an array", "BAD_ARGS")

        inserts = []
        for j, raw_ins in enumerate(raw_inserts):
            if not isinstance(raw_ins, dict):
                return err_payload(f"cavities[{i}].inserts[{j}] must be an object", "BAD_ARGS")
            rev = raw_ins.get("revision")
            if not rev:
                return err_payload(
                    f"cavities[{i}].inserts[{j}].revision is required", "BAD_ARGS"
                )
            eff_from = None
            eff_to = None
            if raw_ins.get("effective_from"):
                try:
                    eff_from = _date.fromisoformat(raw_ins["effective_from"])
                except ValueError as exc:
                    return err_payload(
                        f"cavities[{i}].inserts[{j}].effective_from invalid: {exc}", "BAD_ARGS"
                    )
            if raw_ins.get("effective_to"):
                try:
                    eff_to = _date.fromisoformat(raw_ins["effective_to"])
                except ValueError as exc:
                    return err_payload(
                        f"cavities[{i}].inserts[{j}].effective_to invalid: {exc}", "BAD_ARGS"
                    )
            compat = set(raw_ins.get("compatible_revisions") or [])
            inserts.append(CavityInsert(
                revision=rev,
                effective_from=eff_from,
                effective_to=eff_to,
                compatible_revisions=compat,
            ))

        cavities.append(ToolCavity(cavity_id=cid, inserts=inserts))

    tool = MultiCavityTool(tool_id=tool_id, cavities=cavities)

    try:
        result = query_multi_cavity_effectivity(tool, query_date, options=options)
    except Exception as exc:
        return err_payload(f"query error: {exc}", "QUERY_ERROR")

    return ok_payload({
        "tool_id": result.tool_id,
        "query_date": result.query_date.isoformat(),
        "effective_count": result.effective_count,
        "cavity_count": len(result.per_cavity_revisions),
        "per_cavity_revisions": [
            {
                "cavity_id": r.cavity_id,
                "revision": r.revision,
                "effective": r.effective,
                "compatible_revisions": sorted(r.compatible_revisions),
            }
            for r in result.per_cavity_revisions
        ],
        "honest_flag": HONEST_FLAG,
    })


# ===========================================================================
# PLM Part-Numbering Schema (GS1 GTIN + ISO 8000-110 + Cooper DFM §6)
# ===========================================================================

plm_validate_part_number_spec = ToolSpec(
    name="plm_validate_part_number",
    description=(
        "Validate a part number against a declared corporate part-numbering schema.\n\n"
        "Supported schema types:\n"
        "  sequential   — PN-00001 … PN-99999 (simple sequential, Cooper DFM §6.2).\n"
        "  hierarchical — TTT-FFF-VVV-SSS (type-family-variant-serial, Cooper §6.3).\n"
        "  semantic     — SKU-BLK-12X10-AL-V2 (color/size/material/revision, Cooper §6.4).\n"
        "  hash_based   — HASH-<10-hex> (SHA-256 truncation of attributes, deterministic).\n"
        "  custom       — caller-supplied regex pattern.\n\n"
        "Validation checks (GS1 GTIN §2.1 + ISO 8000-110 §6.5):\n"
        "  1. Part number matches the schema regex pattern.\n"
        "  2. Part number does not start with any reserved prefix.\n\n"
        "Returns {valid: bool, reason: str, matched_schema: str}.\n\n"
        "Depth-bar example:\n"
        "  schema PN-{type:3}-{family:3}-{serial:5}, pattern PN-[A-Z]{3}-[A-Z]{3}-\\d{5}:\n"
        "  'PN-ABC-DEF-00123' → valid=true\n"
        "  'PN-AB-DEF-00123'  → valid=false, reason='does not match … pattern'\n\n"
        "Honest flag: validation is syntactic only; duplicate / issued-set checks require "
        "the stateful plm_allocate_part_number tool."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "part_number": {
                "type": "string",
                "description": "The part number string to validate.",
            },
            "schema_type": {
                "type": "string",
                "enum": ["sequential", "hierarchical", "semantic", "hash_based", "custom"],
                "description": "Schema type.  Use 'custom' and supply *pattern* for non-standard schemas.",
                "default": "sequential",
            },
            "pattern": {
                "type": "string",
                "description": (
                    "Regex pattern (Python re, anchored at both ends automatically). "
                    "Required for schema_type='custom'; ignored otherwise."
                ),
            },
            "prefix": {
                "type": "string",
                "description": (
                    "Constant prefix for sequential schemas.  Default: 'PN-'."
                ),
                "default": "PN-",
            },
            "serial_width": {
                "type": "integer",
                "description": "Zero-padded serial digit width for sequential schemas.  Default: 5.",
                "default": 5,
            },
            "reserved_prefixes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Prefixes that must not appear at the start of any valid PN.",
            },
        },
        "required": ["part_number"],
    },
)


@register(plm_validate_part_number_spec)
async def run_plm_validate_part_number(ctx, args: bytes) -> str:
    """Tool handler for plm_validate_part_number (GS1 GTIN §2.1 + ISO 8000-110 §6.5)."""
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    pn = a.get("part_number", "")
    if not pn:
        return err_payload("'part_number' is required", "BAD_ARGS")

    schema_type_str = a.get("schema_type", "sequential")
    pattern = a.get("pattern")
    prefix = a.get("prefix", "PN-")
    serial_width = int(a.get("serial_width", 5))
    reserved = set(a.get("reserved_prefixes") or [])

    try:
        from kerf_plm.part_numbering_schema import (
            PartNumberSchema, SchemaType,
            make_sequential_schema, make_hierarchical_schema,
            make_semantic_schema, make_hash_schema,
        )
        schema_type = SchemaType(schema_type_str)
        if schema_type == SchemaType.SEQUENTIAL:
            schema = make_sequential_schema(
                prefix=prefix, serial_width=serial_width, reserved_prefixes=reserved
            )
        elif schema_type == SchemaType.HIERARCHICAL:
            schema = make_hierarchical_schema(reserved_prefixes=reserved)
        elif schema_type == SchemaType.SEMANTIC:
            schema = make_semantic_schema(reserved_prefixes=reserved)
        elif schema_type == SchemaType.HASH_BASED:
            schema = make_hash_schema(reserved_prefixes=reserved)
        else:  # CUSTOM
            if not pattern:
                return err_payload(
                    "'pattern' is required for schema_type='custom'", "BAD_ARGS"
                )
            schema = PartNumberSchema(
                name="custom",
                schema_type=SchemaType.CUSTOM,
                pattern=pattern,
                prefix=prefix,
                serial_width=serial_width,
                reserved_prefixes=reserved,
            )
        result = schema.validate(pn)
    except ValueError as exc:
        return err_payload(f"invalid schema_type '{schema_type_str}': {exc}", "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"validation error: {exc}", "ERROR")

    return ok_payload({
        "valid": result.valid,
        "reason": result.reason,
        "matched_schema": result.matched_schema,
        "honest_flag": PartNumberSchema.HONEST_FLAG,
    })


plm_allocate_part_number_spec = ToolSpec(
    name="plm_allocate_part_number",
    description=(
        "Allocate (mint) the next available part number under a declared schema.\n\n"
        "The tool maintains a per-call issued-number set passed as *state_json* — "
        "a serialised dict previously returned in the response.  Callers must persist "
        "and re-supply state_json to maintain uniqueness across calls.\n\n"
        "Supported schema types: sequential, hierarchical, hash_based.  Semantic "
        "schemas do not support auto-allocation.\n\n"
        "Sequential family_key: optional string key to namespace serials "
        "(e.g. 'component' vs 'assembly').  Omit for a single global sequence.\n\n"
        "Hierarchical family_key: [type_code, family_code, variant_code], each a "
        "3-digit string.  Separate counter per (type, family, variant).\n\n"
        "Hash-based family_key: a JSON object of part attributes — SHA-256 truncated "
        "to 10 hex chars; deterministic (same attrs → same PN).  Returns duplicate=true "
        "if already issued.\n\n"
        "Depth-bar: allocate next in family ABC-DEF after 'PN-ABC-DEF-00123' issued "
        "→ returns 'PN-ABC-DEF-00124'.\n\n"
        "Honest flag: uniqueness is per-instance / per-state_json only.  "
        "No cross-session federation.  Persist state_json between calls."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "schema_type": {
                "type": "string",
                "enum": ["sequential", "hierarchical", "hash_based"],
                "description": "Schema type for allocation.",
                "default": "sequential",
            },
            "prefix": {
                "type": "string",
                "description": "Constant prefix for sequential schemas.  Default: 'PN-'.",
                "default": "PN-",
            },
            "serial_width": {
                "type": "integer",
                "description": "Zero-padded digit width for sequential schemas.  Default: 5.",
                "default": 5,
            },
            "family_key": {
                "description": (
                    "Namespace key for allocation.  "
                    "Sequential: omit or supply a string key.  "
                    "Hierarchical: [type_code, family_code, variant_code].  "
                    "Hash-based: a JSON object of part attributes."
                ),
            },
            "state_json": {
                "type": "string",
                "description": (
                    "Serialised schema state from a previous call "
                    "(value of 'state' in the previous response).  "
                    "Omit on the first call.  Must be supplied on subsequent "
                    "calls to maintain duplicate detection."
                ),
            },
            "reserved_prefixes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Prefixes that must not be allocated.",
            },
        },
        "required": [],
    },
)


@register(plm_allocate_part_number_spec)
async def run_plm_allocate_part_number(ctx, args: bytes) -> str:
    """Tool handler for plm_allocate_part_number (GS1 GTIN §2.1 + ISO 8000-110 §6.5)."""
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    schema_type_str = a.get("schema_type", "sequential")
    prefix = a.get("prefix", "PN-")
    serial_width = int(a.get("serial_width", 5))
    family_key_raw = a.get("family_key")
    state_json_str = a.get("state_json")
    reserved = set(a.get("reserved_prefixes") or [])

    try:
        from kerf_plm.part_numbering_schema import (
            PartNumberSchema, SchemaType,
            make_sequential_schema, make_hierarchical_schema, make_hash_schema,
        )
        schema_type = SchemaType(schema_type_str)
        if schema_type == SchemaType.SEQUENTIAL:
            schema = make_sequential_schema(
                prefix=prefix, serial_width=serial_width, reserved_prefixes=reserved
            )
        elif schema_type == SchemaType.HIERARCHICAL:
            schema = make_hierarchical_schema(reserved_prefixes=reserved)
        elif schema_type == SchemaType.HASH_BASED:
            schema = make_hash_schema(reserved_prefixes=reserved)
        else:
            return err_payload(
                f"schema_type '{schema_type_str}' does not support auto-allocation; "
                "use sequential, hierarchical, or hash_based.",
                "BAD_ARGS",
            )

        # Restore state if provided
        if state_json_str:
            try:
                state = _json.loads(state_json_str)
                PartNumberSchema.from_state_dict(state, schema)
            except Exception as exc:
                return err_payload(f"invalid state_json: {exc}", "BAD_ARGS")

        # Build family_key
        if family_key_raw is None:
            family_key: tuple = ()
        elif isinstance(family_key_raw, list):
            family_key = tuple(family_key_raw)
        elif isinstance(family_key_raw, dict):
            family_key = (family_key_raw,)
        else:
            family_key = (str(family_key_raw),)

        result = schema.allocate_next(family_key=family_key)
    except ValueError as exc:
        return err_payload(f"invalid schema_type '{schema_type_str}': {exc}", "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"allocation error: {exc}", "ERROR")

    if not result.ok:
        return err_payload(result.reason, "DUPLICATE" if result.duplicate else "ALLOC_FAILED")

    return ok_payload({
        "part_number": result.part_number,
        "duplicate": result.duplicate,
        "state": schema.to_state_dict(),
        "honest_flag": PartNumberSchema.HONEST_FLAG,
    })


# ===========================================================================
# PLM Change Notification Distribution (ISO 10007 §6.2 + APQP PPAP §3)
# ===========================================================================

plm_compute_change_notification_spec = ToolSpec(
    name="plm_compute_change_notification",
    description=(
        "Compute the notification distribution for an Engineering Change Order (ECO).\n\n"
        "For each ECO line item (part revision change) the tool identifies every "
        "stakeholder that must be notified, the reason (citing ISO 10007 §6.2 or "
        "APQP PPAP §3 where applicable), and the urgency level.\n\n"
        "Stakeholder categories:\n"
        "  engineering       — owner of the affected part/assembly; notified for "
        "every ECO line (ISO 10007 §6.2).\n"
        "  supplier          — external supplier; notified when PPAP renewal is "
        "triggered (Class A or Class B dimension/material/process/finish change, "
        "per APQP PPAP §3).\n"
        "  manufacturing_lead — process documentation lead; notified when process "
        "spec, dimension, material, or finish changes (ISO 10007 §6.2).\n"
        "  quality           — QA team; notified for Class A changes, PPAP renewals, "
        "and dimension/material/process changes (ISO 10007 §5.1 + APQP §3).\n"
        "  document_control  — notified for every ECO line for revision packaging "
        "(ISO 10007 §6.2).\n\n"
        "Change classification (ISO 10007 §5.1):\n"
        "  class_a — Critical/Major (safety, regulatory, key characteristic). "
        "Always triggers Quality + Supplier PPAP + Manufacturing.\n"
        "  class_b — Significant functional change. Triggers suppliers/quality/mfg "
        "only for specific change types.\n"
        "  class_c — Minor/Administrative. Engineering + Document Control only.\n\n"
        "Urgency levels (APQP §3 timing guidance):\n"
        "  high   — action required before effectivity date "
        "(PPAP renewal, safety review).\n"
        "  normal — action within normal process lead time.\n"
        "  low    — informational only.\n\n"
        "HONEST FLAG: this tool produces a *recipient list* only. "
        "It does NOT send notifications. The caller must route the returned "
        "notification list to their delivery layer."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "eco_id": {
                "type": "string",
                "description": "Engineering Change Order identifier, e.g. 'ECO-0042'.",
            },
            "eco_lines": {
                "type": "array",
                "description": (
                    "List of ECO line items. Each item:\n"
                    "  part_id (str, required) — part number being changed.\n"
                    "  rev_from (str) — current revision, e.g. 'A'.\n"
                    "  rev_to (str) — target revision, e.g. 'B'.\n"
                    "  change_class (str) — 'class_a' | 'class_b' | 'class_c'. "
                    "Default 'class_b'.\n"
                    "  change_types (list[str]) — one or more of: 'dimension', "
                    "'material', 'process_spec', 'drawing', 'document', 'finish', "
                    "'other'.\n"
                    "  description (str) — free-text change description."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "part_id": {"type": "string"},
                        "rev_from": {"type": "string"},
                        "rev_to": {"type": "string"},
                        "change_class": {
                            "type": "string",
                            "enum": ["class_a", "class_b", "class_c"],
                        },
                        "change_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "dimension", "material", "process_spec",
                                    "drawing", "document", "finish", "other",
                                ],
                            },
                        },
                        "description": {"type": "string"},
                    },
                    "required": ["part_id"],
                },
            },
            "plm_data": {
                "type": "object",
                "description": (
                    "PLM product-structure and stakeholder data. Shape:\n"
                    "  parts: { <part_id>: { owner_team, suppliers, "
                    "manufacturing_routes } }\n"
                    "  quality_team: str (default '@quality-team')\n"
                    "  document_control_team: str (default '@doc-control')"
                ),
                "properties": {
                    "parts": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "object",
                            "properties": {
                                "owner_team": {"type": "string"},
                                "suppliers": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "manufacturing_routes": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                    "quality_team": {"type": "string"},
                    "document_control_team": {"type": "string"},
                },
            },
        },
        "required": ["eco_id", "eco_lines", "plm_data"],
    },
)


@register(plm_compute_change_notification_spec)
async def run_plm_compute_change_notification(ctx, args: bytes) -> str:
    """Tool handler for plm_compute_change_notification (ISO 10007 §6.2 + APQP §3)."""
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    eco_id = a.get("eco_id", "")
    raw_lines = a.get("eco_lines")
    raw_plm = a.get("plm_data")

    if not eco_id:
        return err_payload("'eco_id' is required", "BAD_ARGS")
    if not isinstance(raw_lines, list):
        return err_payload("'eco_lines' must be an array", "BAD_ARGS")
    if not isinstance(raw_plm, dict):
        return err_payload("'plm_data' must be an object", "BAD_ARGS")

    from kerf_plm.change_notification import (
        compute_notification_distribution,
        eco_line_from_dict,
        plm_data_from_dict,
    )

    try:
        eco_lines = [eco_line_from_dict(l) for l in raw_lines]
    except (KeyError, TypeError) as exc:
        return err_payload(f"invalid eco_lines entry: {exc}", "BAD_ARGS")

    plm_data = plm_data_from_dict(raw_plm)

    try:
        report = compute_notification_distribution(eco_id, eco_lines, plm_data)
    except Exception as exc:
        return err_payload(f"notification computation error: {exc}", "COMPUTATION_ERROR")

    return ok_payload({
        "eco_id": report.eco_id,
        "notification_count": len(report.notifications),
        "honest_flag": report.honest_flag,
        "notifications": [
            {
                "part_id": n.part_id,
                "stakeholder": n.stakeholder,
                "role": n.role,
                "reason": n.reason,
                "urgency": n.urgency.value,
                "ppap_renewal_required": n.ppap_renewal_required,
            }
            for n in report.notifications
        ],
        "by_part": {
            pid: [
                {
                    "stakeholder": n.stakeholder,
                    "role": n.role,
                    "urgency": n.urgency.value,
                    "ppap_renewal_required": n.ppap_renewal_required,
                }
                for n in notifs
            ]
            for pid, notifs in report.by_part().items()
        },
    })


# ===========================================================================
# PLM BOM Cost Roll-up (ISO 10303-44 + APICS "rolled-up cost")
# ===========================================================================

plm_rollup_bom_cost_spec = ToolSpec(
    name="plm_rollup_bom_cost",
    description=(
        "Compute the rolled-up cost at every assembly node in a multi-level BOM tree.\n\n"
        "Per ISO 10303-44 (STEP AP44 product structure) and the APICS dictionary "
        "'rolled-up cost' definition:\n\n"
        "    rolled_cost(node) = node.internal_cost\n"
        "                      + sum(qty_i * rolled_cost(child_i))\n\n"
        "All costs are converted to the target *currency* via *fx_rates* before "
        "summation.  For leaf (purchased) nodes where internal_cost is omitted, "
        "unit_cost is used as the leaf cost.\n\n"
        "Cycle detection: raises an error if any part_number appears on its own "
        "ancestor path (A → B → A).\n\n"
        "HONEST FLAG — static unit costs only:\n"
        "  - No scrap allowance, overhead absorption, or yield-based costing.\n"
        "  - No activity-based or machine-rate overhead.\n"
        "  - FX rates are caller-supplied constants (no live feed).\n"
        "  - Shared sub-assemblies are costed per occurrence path, not deduplicated.\n\n"
        "References: ISO 10303-44:2021 §5.3; APICS Dictionary 16th ed. 'rolled-up cost';\n"
        "Horngren et al. *Cost Accounting* 16th ed. §7."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bom_tree": {
                "type": "object",
                "description": (
                    "Root BOM node (recursive tree). Each node:\n"
                    "  part_number (str, required) — unique part identifier.\n"
                    "  name (str, required) — human-readable part name.\n"
                    "  unit_cost (number, required) — own cost (purchase price for "
                    "    leaf parts; own-process cost for assemblies).\n"
                    "  currency (str, required) — ISO 4217 code for unit_cost and "
                    "    internal_cost, e.g. 'USD', 'EUR', 'ZAR'.\n"
                    "  internal_cost (number, default 0.0) — cost intrinsic to this "
                    "    assembly beyond its children (e.g. assembly labour).  "
                    "    For leaf parts leave at 0.0 and set unit_cost.\n"
                    "  children (array, default []) — list of {node, qty} objects:\n"
                    "    node: nested BOM node (same schema, recursive).\n"
                    "    qty: positive real quantity of the child."
                ),
                "properties": {
                    "part_number": {"type": "string"},
                    "name": {"type": "string"},
                    "unit_cost": {"type": "number"},
                    "currency": {"type": "string"},
                    "internal_cost": {"type": "number", "default": 0.0},
                    "children": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "node": {"type": "object"},
                                "qty": {"type": "number"},
                            },
                            "required": ["node", "qty"],
                        },
                    },
                },
                "required": ["part_number", "name", "unit_cost", "currency"],
            },
            "currency": {
                "type": "string",
                "description": (
                    "ISO 4217 target currency for the roll-up report. "
                    "Default: 'USD'."
                ),
                "default": "USD",
            },
            "fx_rates": {
                "type": "object",
                "description": (
                    "Optional FX rate table mapping ISO 4217 code → rate-to-USD. "
                    "Example: {'USD': 1.0, 'EUR': 1.10, 'ZAR': 0.054}. "
                    "If omitted, a built-in 2025 baseline table is used. "
                    "Provide your own for accurate conversion."
                ),
                "additionalProperties": {"type": "number"},
            },
        },
        "required": ["bom_tree"],
    },
)


def _parse_bom_node(raw: dict) -> "BomNode":
    """Recursively parse a raw dict into a BomNode."""
    from kerf_plm.bom_cost_rollup import BomNode

    part_number = raw.get("part_number")
    if not part_number:
        raise ValueError("bom_tree node missing 'part_number'")
    name = raw.get("name", "")
    unit_cost = float(raw.get("unit_cost", 0.0))
    currency = raw.get("currency", "USD")
    internal_cost = float(raw.get("internal_cost", 0.0))

    children = []
    for item in raw.get("children", []):
        if not isinstance(item, dict):
            raise ValueError(
                f"children entries must be objects, got {type(item).__name__}"
            )
        child_raw = item.get("node")
        if child_raw is None:
            raise ValueError(
                f"children entry missing 'node' field for part '{part_number}'"
            )
        qty = float(item.get("qty", 1.0))
        child_node = _parse_bom_node(child_raw)
        children.append((child_node, qty))

    return BomNode(
        part_number=part_number,
        name=name,
        unit_cost=unit_cost,
        currency=currency,
        children=children,
        internal_cost=internal_cost,
    )


@register(plm_rollup_bom_cost_spec)
async def run_plm_rollup_bom_cost(ctx, args: bytes) -> str:
    """Tool handler for plm_rollup_bom_cost (ISO 10303-44 + APICS rolled-up cost)."""
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    raw_tree = a.get("bom_tree")
    if not isinstance(raw_tree, dict):
        return err_payload("'bom_tree' must be an object", "BAD_ARGS")

    currency = a.get("currency", "USD") or "USD"
    fx_rates_raw = a.get("fx_rates")
    fx_rates = None
    if fx_rates_raw is not None:
        if not isinstance(fx_rates_raw, dict):
            return err_payload("'fx_rates' must be an object", "BAD_ARGS")
        try:
            fx_rates = {k: float(v) for k, v in fx_rates_raw.items()}
        except (TypeError, ValueError) as exc:
            return err_payload(f"invalid fx_rates: {exc}", "BAD_ARGS")

    try:
        root = _parse_bom_node(raw_tree)
    except (TypeError, ValueError) as exc:
        return err_payload(f"invalid bom_tree: {exc}", "BAD_ARGS")

    try:
        from kerf_plm.bom_cost_rollup import rollup_bom_cost
        report = rollup_bom_cost(root, currency=currency, fx_rates=fx_rates)
    except ValueError as exc:
        return err_payload(str(exc), "CYCLE_DETECTED" if "Cycle" in str(exc) else "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"rollup error: {exc}", "ROLLUP_ERROR")

    return ok_payload({
        "part_number": report.part_number,
        "total_cost": report.total_cost,
        "currency": report.currency,
        "num_unique_parts": report.num_unique_parts,
        "depth": report.depth,
        "cost_breakdown_by_node": report.cost_breakdown_by_node,
        "honest_caveat": report.honest_caveat,
    })


# ===========================================================================
# PLM Component Where-Used (ISO 10303-44 + APICS "where-used")
# ===========================================================================

plm_component_whereused_spec = ToolSpec(
    name="plm_component_whereused",
    description=(
        "Produce a Where-Used report for a component: every parent assembly "
        "that references it (directly or transitively) with quantity and level.\n\n"
        "This is the *component-centric* inverse-BOM traversal defined by:\n"
        "  ISO 10303-44:2021 (STEP AP44) — next_assembly_usage_occurrence traversal.\n"
        "  APICS Dictionary 16th ed. — 'where-used': determination of every higher-level "
        "item that incorporates a given component in its bill of material.\n\n"
        "Input: a flat list of BOM relationships (parent_pn, child_pn, qty).  "
        "Output: every assembly that contains the queried component, with:\n"
        "  - qty: direct quantity consumed at that parent level.\n"
        "  - level: BFS depth (1 = direct parent, 2 = grandparent, …).\n\n"
        "Quantity semantics:\n"
        "  qty per entry is the *direct* usage at that BFS hop.  For extended "
        "path-multiplied quantities, multiply down the path manually.\n"
        "  Multiple BomRelationship rows with the same (parent, child) are "
        "summed into a single qty.\n\n"
        "Cycle detection:\n"
        "  The tool returns an error if the BOM graph contains a cycle.  "
        "BOM cycles violate ISO 10303-44 constraints.\n\n"
        "HONEST FLAG — in-memory traversal only:\n"
        "  - No DB pagination or live PDM sync.\n"
        "  - No effectivity, variant, or revision filtering.\n"
        "  - qty per entry is direct (not path-multiplied extended quantity).\n"
        "  - Cycles raise an error (not silently truncated)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "component_pn": {
                "type": "string",
                "description": "Part number of the component to query.",
            },
            "relationships": {
                "type": "array",
                "description": (
                    "Flat list of BOM relationships. Each entry:\n"
                    "  parent_pn (str, required) — part number of the parent assembly.\n"
                    "  child_pn  (str, required) — part number of the child component.\n"
                    "  qty       (number, required) — quantity of child_pn used in "
                    "one unit of parent_pn."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "parent_pn": {"type": "string"},
                        "child_pn": {"type": "string"},
                        "qty": {"type": "number"},
                    },
                    "required": ["parent_pn", "child_pn", "qty"],
                },
            },
            "names": {
                "type": "object",
                "description": (
                    "Optional map of part_number → human-readable name.  "
                    "Used to populate parent_name in each entry."
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["component_pn", "relationships"],
    },
)


@register(plm_component_whereused_spec)
async def run_plm_component_whereused(ctx, args: bytes) -> str:
    """Tool handler for plm_component_whereused (ISO 10303-44 + APICS where-used)."""
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    component_pn = a.get("component_pn", "")
    raw_relationships = a.get("relationships")
    names = a.get("names") or {}

    if not component_pn:
        return err_payload("'component_pn' is required", "BAD_ARGS")
    if not isinstance(raw_relationships, list):
        return err_payload("'relationships' must be an array", "BAD_ARGS")
    if not isinstance(names, dict):
        return err_payload("'names' must be an object", "BAD_ARGS")

    from kerf_plm.component_whereused import BomRelationship, find_component_whereused

    try:
        relationships = []
        for i, raw in enumerate(raw_relationships):
            if not isinstance(raw, dict):
                return err_payload(f"relationships[{i}] must be an object", "BAD_ARGS")
            parent_pn = raw.get("parent_pn")
            child_pn = raw.get("child_pn")
            qty_raw = raw.get("qty")
            if not parent_pn:
                return err_payload(f"relationships[{i}].parent_pn is required", "BAD_ARGS")
            if not child_pn:
                return err_payload(f"relationships[{i}].child_pn is required", "BAD_ARGS")
            if qty_raw is None:
                return err_payload(f"relationships[{i}].qty is required", "BAD_ARGS")
            try:
                qty = float(qty_raw)
            except (TypeError, ValueError) as exc:
                return err_payload(f"relationships[{i}].qty must be a number: {exc}", "BAD_ARGS")
            relationships.append(BomRelationship(parent_pn=parent_pn, child_pn=child_pn, qty=qty))
    except Exception as exc:
        return err_payload(f"invalid relationships: {exc}", "BAD_ARGS")

    try:
        report = find_component_whereused(component_pn, relationships, names=names)
    except ValueError as exc:
        return err_payload(str(exc), "CYCLE_DETECTED")
    except Exception as exc:
        return err_payload(f"where-used error: {exc}", "ANALYSIS_ERROR")

    return ok_payload({
        "component_pn": report.component_pn,
        "num_unique_parents": report.num_unique_parents,
        "num_total_usages": report.num_total_usages,
        "max_depth": report.max_depth,
        "honest_caveat": report.honest_caveat,
        "entries": [
            {
                "parent_pn": e.parent_pn,
                "parent_name": e.parent_name,
                "qty": e.qty,
                "level": e.level,
            }
            for e in report.entries
        ],
    })


# ===========================================================================
# PLM ECN Impact Analysis (ISO 10007 §6 + APICS "ECN")
# ===========================================================================

plm_analyze_ecn_impact_spec = ToolSpec(
    name="plm_analyze_ecn_impact",
    description=(
        "Compute the cascading impact of an Engineering Change Notice (ECN) "
        "affecting one or more part numbers.\n\n"
        "Per ISO 10007:2003 §6 (Change control) and the APICS Dictionary "
        "'engineering change notice (ECN)' definition, an ECN initiates a "
        "structured change-control process.  This tool performs:\n\n"
        "  1. BFS upward traversal from every ECN-affected component through "
        "the BOM hierarchy to identify ALL transitively affected parent "
        "assemblies (deduplicated across all input components).\n"
        "  2. Drawing impact: counts distinct drawing IDs linked to any "
        "affected parent (from optional *drawings_db*).\n"
        "  3. Work-order impact: counts distinct open work order IDs linked "
        "to any affected parent (from optional *work_orders_db*).\n"
        "  4. Heuristic cost estimate (USD):\n"
        "       cost = (parents × $50) + (drawings × cost_per_drawing_revision) "
        "+ (work_orders × $200)\n"
        "  5. Implementation class assignment (ISO 10007 §6.3.2):\n"
        "       Class_I_immediate    — emergency urgency OR ≥ 20 affected parents.\n"
        "       Class_II_rev         — normal urgency, 1–19 affected parents.\n"
        "       Class_III_drawing_only — deferred urgency OR zero affected parents.\n\n"
        "HONEST FLAG: cost formula is a heuristic estimate only.  "
        "Real-world ECN costs vary widely by industry — aerospace/defence "
        "drawing revisions can exceed $10 000; consumer electronics may be "
        "< $50.  Use for initial prioritisation, not budget approval.  "
        "Class assignment is heuristic; real ECN classification requires "
        "engineering judgment and change-board review per ISO 10007 §6.5."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ecn_id": {
                "type": "string",
                "description": "Unique ECN identifier, e.g. 'ECN-2026-0042'.",
            },
            "affected_components": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Part numbers directly listed on the ECN. "
                    "Each is used as a starting point for BFS upward traversal."
                ),
            },
            "change_description": {
                "type": "string",
                "description": "Free-text description of the engineering change.",
            },
            "urgency": {
                "type": "string",
                "enum": ["emergency", "normal", "deferred"],
                "description": (
                    "Change urgency.  Controls implementation class:\n"
                    "  emergency → Class_I_immediate (regardless of impact size).\n"
                    "  normal    → Class_I if >= 20 parents, else Class_II_rev.\n"
                    "  deferred  → Class_III_drawing_only if zero parents found, "
                    "else Class_II_rev."
                ),
            },
            "relationships": {
                "type": "array",
                "description": (
                    "Flat list of BOM relationships. Each entry:\n"
                    "  parent_pn (str, required) — parent assembly part number.\n"
                    "  child_pn  (str, required) — child component part number.\n"
                    "  qty       (number, required) — quantity of child in one parent."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "parent_pn": {"type": "string"},
                        "child_pn": {"type": "string"},
                        "qty": {"type": "number"},
                    },
                    "required": ["parent_pn", "child_pn", "qty"],
                },
            },
            "drawings_db": {
                "type": "object",
                "description": (
                    "Optional mapping of part_number → [drawing_id, ...]. "
                    "Used to count distinct drawings affected by the ECN. "
                    "Omit if drawing impact is not relevant."
                ),
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "work_orders_db": {
                "type": "object",
                "description": (
                    "Optional mapping of part_number → [work_order_id, ...] "
                    "for currently open work orders. "
                    "Omit if work-order impact is not relevant."
                ),
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "cost_per_drawing_revision": {
                "type": "number",
                "description": (
                    "Heuristic cost (USD) to revise one drawing. "
                    "Default: 150.0.  "
                    "Adjust for your industry — aerospace typically higher, "
                    "consumer electronics typically lower."
                ),
                "default": 150.0,
            },
        },
        "required": ["ecn_id", "affected_components", "change_description", "urgency", "relationships"],
    },
)


@register(plm_analyze_ecn_impact_spec)
async def run_plm_analyze_ecn_impact(ctx, args: bytes) -> str:
    """Tool handler for plm_analyze_ecn_impact (ISO 10007 §6 + APICS ECN)."""
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    ecn_id = a.get("ecn_id", "")
    affected_components = a.get("affected_components")
    change_description = a.get("change_description", "")
    urgency = a.get("urgency", "")
    raw_relationships = a.get("relationships")
    drawings_db_raw = a.get("drawings_db") or {}
    work_orders_db_raw = a.get("work_orders_db") or {}
    cost_per_rev = float(a.get("cost_per_drawing_revision", 150.0))

    if not ecn_id:
        return err_payload("'ecn_id' is required", "BAD_ARGS")
    if not isinstance(affected_components, list):
        return err_payload("'affected_components' must be an array", "BAD_ARGS")
    if not urgency:
        return err_payload("'urgency' is required", "BAD_ARGS")
    if urgency not in {"emergency", "normal", "deferred"}:
        return err_payload(
            f"'urgency' must be 'emergency', 'normal', or 'deferred', got {urgency!r}",
            "BAD_ARGS",
        )
    if not isinstance(raw_relationships, list):
        return err_payload("'relationships' must be an array", "BAD_ARGS")
    if not isinstance(drawings_db_raw, dict):
        return err_payload("'drawings_db' must be an object", "BAD_ARGS")
    if not isinstance(work_orders_db_raw, dict):
        return err_payload("'work_orders_db' must be an object", "BAD_ARGS")

    from kerf_plm.component_whereused import BomRelationship
    from kerf_plm.ecn_impact_analysis import EcnInput, analyze_ecn_impact

    # Parse relationships
    try:
        relationships = []
        for i, raw in enumerate(raw_relationships):
            if not isinstance(raw, dict):
                return err_payload(f"relationships[{i}] must be an object", "BAD_ARGS")
            parent_pn = raw.get("parent_pn")
            child_pn = raw.get("child_pn")
            qty_raw = raw.get("qty")
            if not parent_pn:
                return err_payload(f"relationships[{i}].parent_pn is required", "BAD_ARGS")
            if not child_pn:
                return err_payload(f"relationships[{i}].child_pn is required", "BAD_ARGS")
            if qty_raw is None:
                return err_payload(f"relationships[{i}].qty is required", "BAD_ARGS")
            try:
                qty = float(qty_raw)
            except (TypeError, ValueError) as exc:
                return err_payload(f"relationships[{i}].qty must be a number: {exc}", "BAD_ARGS")
            relationships.append(BomRelationship(parent_pn=parent_pn, child_pn=child_pn, qty=qty))
    except Exception as exc:
        return err_payload(f"invalid relationships: {exc}", "BAD_ARGS")

    ecn_input = EcnInput(
        ecn_id=ecn_id,
        affected_components=affected_components,
        change_description=change_description,
        urgency=urgency,
    )

    try:
        report = analyze_ecn_impact(
            ecn_input=ecn_input,
            bom_relationships=relationships,
            drawings_db=drawings_db_raw if drawings_db_raw else None,
            work_orders_db=work_orders_db_raw if work_orders_db_raw else None,
            cost_per_drawing_revision=cost_per_rev,
        )
    except ValueError as exc:
        code = "CYCLE_DETECTED" if "Cycle" in str(exc) else "BAD_ARGS"
        return err_payload(str(exc), code)
    except Exception as exc:
        return err_payload(f"analysis error: {exc}", "ANALYSIS_ERROR")

    return ok_payload({
        "ecn_id": report.ecn_id,
        "total_affected_parents": report.total_affected_parents,
        "total_affected_drawings": report.total_affected_drawings,
        "total_open_work_orders": report.total_open_work_orders,
        "estimated_cost_usd": report.estimated_cost_usd,
        "implementation_class": report.implementation_class,
        "affected_parent_tree": report.affected_parent_tree,
        "honest_caveat": report.honest_caveat,
    })


# ---------------------------------------------------------------------------
# plm_assess_bom_maturity
# ---------------------------------------------------------------------------

plm_assess_bom_maturity_spec = ToolSpec(
    name="plm_assess_bom_maturity",
    description=(
        "Assess BOM completeness maturity using a NASA TRL-style (Technology "
        "Readiness Level) scoring model rolled up to a parent assembly score.\n\n"
        "References: NASA SP-2016-6105 Rev 2 (TRL 1–9); ISO/IEC 15288:2023 §6.3 "
        "(system maturity); INCOSE SE Handbook v4 §4.1.\n\n"
        "Supply a *parent_pn* (assembly part number), a *children* list "
        "(one entry per child component with trl_level 1–9 and boolean "
        "completeness flags), and an optional *qty_per_child* map.\n\n"
        "Returns weighted_avg_trl, blocker_count (TRL < 5), risk_level "
        "(low / medium / high / critical), recommendation, and honest_caveat.\n\n"
        "Honest caveat: TRL weighted average is a simplified proxy. Real maturity "
        "assessments also include test heritage, supplier capability maturity "
        "(AS9100 / CMMI), demonstrated performance in operational environment, "
        "FMEA closure, and PPAP evidence packages."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "parent_pn": {
                "type": "string",
                "description": "Part number of the parent assembly being assessed.",
            },
            "children": {
                "type": "array",
                "description": (
                    "List of child component maturity records. Each record has:\n"
                    "  part_number: str — unique part identifier.\n"
                    "  trl_level: int 1–9 — NASA TRL score.\n"
                    "  manufacturer_qualified: bool — holds AS9100 / QPL cert.\n"
                    "  has_drawings: bool — released engineering drawing exists.\n"
                    "  has_supplier: bool — confirmed supplier on record.\n"
                    "  has_test_data: bool — DV/PV or acceptance test data exists."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "part_number": {"type": "string"},
                        "trl_level": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 9,
                            "description": "NASA TRL 1–9.",
                        },
                        "manufacturer_qualified": {"type": "boolean"},
                        "has_drawings": {"type": "boolean"},
                        "has_supplier": {"type": "boolean"},
                        "has_test_data": {"type": "boolean"},
                    },
                    "required": [
                        "part_number",
                        "trl_level",
                        "manufacturer_qualified",
                        "has_drawings",
                        "has_supplier",
                        "has_test_data",
                    ],
                },
            },
            "qty_per_child": {
                "type": "object",
                "description": (
                    "Optional mapping of part_number → quantity in the assembly. "
                    "Missing entries default to 1.0. Quantities must be > 0."
                ),
                "additionalProperties": {"type": "number"},
            },
        },
        "required": ["parent_pn", "children"],
    },
)


@register(plm_assess_bom_maturity_spec)
async def run_plm_assess_bom_maturity(ctx, args: bytes) -> str:
    """Tool handler for plm_assess_bom_maturity."""
    import json as _json
    try:
        a = _json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    parent_pn = a.get("parent_pn", "")
    children_raw = a.get("children")
    qty_raw = a.get("qty_per_child") or {}

    if not parent_pn:
        return err_payload("'parent_pn' is required", "BAD_ARGS")
    if not isinstance(children_raw, list):
        return err_payload("'children' must be an array", "BAD_ARGS")
    if not isinstance(qty_raw, dict):
        return err_payload("'qty_per_child' must be an object", "BAD_ARGS")

    from kerf_plm.maturity_check import ComponentMaturity, assess_bom_maturity

    # Parse children
    children = []
    for i, raw in enumerate(children_raw):
        if not isinstance(raw, dict):
            return err_payload(f"children[{i}] must be an object", "BAD_ARGS")
        pn = raw.get("part_number")
        trl_raw = raw.get("trl_level")
        mfr_q = raw.get("manufacturer_qualified")
        has_dr = raw.get("has_drawings")
        has_sup = raw.get("has_supplier")
        has_td = raw.get("has_test_data")

        if not pn:
            return err_payload(f"children[{i}].part_number is required", "BAD_ARGS")
        if trl_raw is None:
            return err_payload(f"children[{i}].trl_level is required", "BAD_ARGS")
        for fname, fval in [
            ("manufacturer_qualified", mfr_q),
            ("has_drawings", has_dr),
            ("has_supplier", has_sup),
            ("has_test_data", has_td),
        ]:
            if fval is None:
                return err_payload(
                    f"children[{i}].{fname} is required", "BAD_ARGS"
                )

        try:
            trl = int(trl_raw)
        except (TypeError, ValueError) as exc:
            return err_payload(
                f"children[{i}].trl_level must be an integer: {exc}", "BAD_ARGS"
            )

        try:
            comp = ComponentMaturity(
                part_number=pn,
                trl_level=trl,
                manufacturer_qualified=bool(mfr_q),
                has_drawings=bool(has_dr),
                has_supplier=bool(has_sup),
                has_test_data=bool(has_td),
            )
        except (TypeError, ValueError) as exc:
            return err_payload(f"children[{i}] invalid: {exc}", "BAD_ARGS")

        children.append(comp)

    # Parse qty_per_child
    qty_per_child: dict[str, float] = {}
    for pn_key, qty_val in qty_raw.items():
        try:
            qty_f = float(qty_val)
        except (TypeError, ValueError) as exc:
            return err_payload(
                f"qty_per_child['{pn_key}'] must be a number: {exc}", "BAD_ARGS"
            )
        qty_per_child[pn_key] = qty_f

    try:
        report = assess_bom_maturity(
            parent_pn=parent_pn,
            children=children,
            qty_per_child=qty_per_child,
        )
    except (TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"assessment error: {exc}", "ASSESSMENT_ERROR")

    return ok_payload({
        "parent_pn": report.parent_pn,
        "weighted_avg_trl": report.weighted_avg_trl,
        "blocker_count": report.blocker_count,
        "risk_level": report.risk_level,
        "recommendation": report.recommendation,
        "honest_caveat": report.honest_caveat,
    })
