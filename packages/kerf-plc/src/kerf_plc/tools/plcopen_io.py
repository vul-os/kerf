"""LLM tools: import_plcopen_xml / export_plcopen_xml

These tools give the agent the ability to:
  - import_plcopen_xml: parse a PLCopen XML string → structured ladder model
    (POU list, rung/contact/coil/FB counts, variable declarations).
  - export_plcopen_xml: take a structured ladder model and produce a valid
    PLCopen XML document (IEC TR 61131-10 / PLCopen TC6 schema version 2.01).

Both tools are stateless; they do not read or write files — the XML is
passed/returned inline.  The agent or front-end is responsible for file I/O.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    # Standalone / test context — minimal shims
    from dataclasses import dataclass

    @dataclass
    class ToolSpec:  # type: ignore[no-redef]
        name: str
        description: str
        input_schema: dict

    def ok_payload(v: Any) -> str:  # type: ignore[misc]
        return json.dumps(v)

    def err_payload(msg: str, code: str) -> str:  # type: ignore[misc]
        return json.dumps({"error": msg, "code": code})

    ProjectCtx = Any  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# import_plcopen_xml
# ---------------------------------------------------------------------------

import_plcopen_xml_spec = ToolSpec(
    name="import_plcopen_xml",
    description=(
        "Parse a PLCopen XML document (IEC TR 61131-10, schema v2.01) and return "
        "a structured summary of its contents: the project name, list of POUs with "
        "their type (program/functionBlock/function) and body language (LD/ST/FBD/IL), "
        "variable declarations, and — for Ladder Diagram (LD) bodies — a serialised "
        "rung model with contacts, coils, and function-block instances.\n\n"
        "Use this tool whenever the user uploads or pastes a .plc file, or asks Kerf "
        "to load, analyse, or edit a PLC program. "
        "The returned `model` dict can be passed directly to export_plcopen_xml to "
        "round-trip the project.\n\n"
        "Raises a parse error (code PARSE_ERROR) if the XML is structurally invalid "
        "or violates the PLCopen schema (e.g. unknown pouType)."
    ),
    input_schema={
        "type": "object",
        "required": ["xml"],
        "properties": {
            "xml": {
                "type": "string",
                "description": (
                    "PLCopen XML text. Must contain a <project> root element with "
                    "the PLCopen TC6 namespace "
                    "(http://www.plcopen.org/xml/tc6_0201). "
                    "Both namespace-qualified and bare (no-namespace) XML are accepted."
                ),
            },
        },
    },
)


async def import_plcopen_xml(ctx: ProjectCtx, args: bytes) -> str:
    """Parse PLCopen XML → structured model dict."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    xml = a.get("xml", "").strip()
    if not xml:
        return err_payload("'xml' is required and must be non-empty", "BAD_ARGS")

    try:
        from kerf_plc.plcopen.reader import loads
        from kerf_plc.plcopen.ast import LDBody, STBody, FBDBody, ILBody
    except Exception as exc:
        return err_payload(f"plcopen reader unavailable: {exc}", "INTERNAL")

    try:
        project = loads(xml)
    except Exception as exc:
        return err_payload(f"PLCopen XML parse error: {exc}", "PARSE_ERROR")

    # Serialise to a stable dict the agent can inspect and re-export.
    pous_out = []
    for pou in project.pous:
        body = pou.body
        if isinstance(body, LDBody):
            body_lang = "LD"
            rungs_out = []
            for rung in body.rungs:
                rungs_out.append({
                    "left_power_rail": (
                        {"local_id": rung.left_power_rail.local_id}
                        if rung.left_power_rail else None
                    ),
                    "right_power_rail": (
                        {"local_id": rung.right_power_rail.local_id}
                        if rung.right_power_rail else None
                    ),
                    "contacts": [
                        {
                            "local_id": c.local_id,
                            "variable": c.variable,
                            "negated": c.negated,
                            "position": (
                                {"x": c.position.x, "y": c.position.y}
                                if c.position else None
                            ),
                        }
                        for c in rung.contacts
                    ],
                    "coils": [
                        {
                            "local_id": c.local_id,
                            "variable": c.variable,
                            "negated": c.negated,
                            "position": (
                                {"x": c.position.x, "y": c.position.y}
                                if c.position else None
                            ),
                        }
                        for c in rung.coils
                    ],
                    "fb_instances": [
                        {
                            "local_id": fb.local_id,
                            "type_name": fb.type_name,
                            "instance_name": fb.instance_name,
                            "position": (
                                {"x": fb.position.x, "y": fb.position.y}
                                if fb.position else None
                            ),
                        }
                        for fb in rung.fb_instances
                    ],
                })
            body_out = {"language": "LD", "rungs": rungs_out}
        elif isinstance(body, STBody):
            body_lang = "ST"
            body_out = {"language": "ST", "text": body.text}
        elif isinstance(body, FBDBody):
            body_lang = "FBD"
            body_out = {"language": "FBD", "raw_xml": body.raw_xml}
        elif isinstance(body, ILBody):
            body_lang = "IL"
            body_out = {"language": "IL", "text": body.text}
        else:
            body_lang = "unknown"
            body_out = {"language": "unknown"}

        var_blocks_out = []
        for vb in pou.var_blocks:
            var_blocks_out.append({
                "kind": vb.kind,
                "variables": [
                    {
                        "name": v.name,
                        "type_name": v.type_name,
                        "initial_value": v.initial_value,
                    }
                    for v in vb.variables
                ],
            })

        pous_out.append({
            "name": pou.name,
            "pou_type": pou.pou_type,
            "body_language": body_lang,
            "var_blocks": var_blocks_out,
            "body": body_out,
        })

    # Instance / configuration summary
    configs_out = [
        {
            "name": cfg.name,
            "resources": [
                {
                    "name": res.name,
                    "type_name": res.type_name,
                    "tasks": [
                        {"name": t.name, "interval": t.interval, "priority": t.priority}
                        for t in res.tasks
                    ],
                    "program_instances": [
                        {"name": pi.name, "type_name": pi.type_name, "task_name": pi.task_name}
                        for pi in res.program_instances
                    ],
                }
                for res in cfg.resources
            ],
        }
        for cfg in project.instances.configurations
    ]

    model = {
        "project_name": project.content_header.name,
        "version": project.content_header.version,
        "author": project.content_header.author,
        "description": project.content_header.description,
        "pous": pous_out,
        "configurations": configs_out,
    }

    # Summary stats for quick consumption
    total_rungs = sum(
        len(p["body"].get("rungs", []))
        for p in pous_out
        if p["body_language"] == "LD"
    )
    total_vars = sum(
        len(vb["variables"])
        for p in pous_out
        for vb in p["var_blocks"]
    )

    return ok_payload({
        "ok": True,
        "project_name": project.content_header.name,
        "pou_count": len(pous_out),
        "rung_count": total_rungs,
        "variable_count": total_vars,
        "model": model,
    })


# ---------------------------------------------------------------------------
# export_plcopen_xml
# ---------------------------------------------------------------------------

export_plcopen_xml_spec = ToolSpec(
    name="export_plcopen_xml",
    description=(
        "Serialise a ladder/PLC model dict to a valid PLCopen XML document "
        "(IEC TR 61131-10, PLCopen TC6 schema v2.01). "
        "The input `model` must match the structure returned by import_plcopen_xml "
        "or make_ladder_program. "
        "Returns the PLCopen XML string ready to save as a .plc file.\n\n"
        "Use this tool whenever the user wants to export or download a PLC program, "
        "or after editing a model to produce a file the user can open in CODESYS, "
        "Beremiz, OpenPLC Editor, or any other PLCopen-compatible tool.\n\n"
        "If `project_name` is omitted, the value from `model.project_name` is used. "
        "Raises INVALID_MODEL if required model fields are missing."
    ),
    input_schema={
        "type": "object",
        "required": ["model"],
        "properties": {
            "model": {
                "type": "object",
                "description": (
                    "A PLC model dict as returned by import_plcopen_xml or "
                    "make_ladder_program. Must contain at minimum a 'pous' list."
                ),
            },
            "project_name": {
                "type": "string",
                "description": (
                    "Optional override for the project name written into the "
                    "<contentHeader>. Defaults to model.project_name if present, "
                    "otherwise 'Untitled'."
                ),
            },
            "author": {
                "type": "string",
                "description": "Optional author string for the <contentHeader>.",
            },
            "description": {
                "type": "string",
                "description": "Optional description string for the <contentHeader>.",
            },
        },
    },
)


def _model_to_project(model: dict, project_name: str, author: str, description: str):
    """Convert the model dict produced by import_plcopen_xml back to a Project AST."""
    from kerf_plc.plcopen.ast import (
        Project, ContentHeader, Types, Instances,
        POU, LDBody, STBody, FBDBody, ILBody,
        Rung, Contact, Coil, FBInstance, LeftPowerRail, RightPowerRail, Position,
        VarBlock, Variable, Configuration, Resource, TaskConfig, ProgramInstance,
    )

    # --- ContentHeader ---
    content_header = ContentHeader(
        name=project_name,
        version=model.get("version", "1.0"),
        product_name="Kerf",
        product_version="1.0",
        product_release="1.0",
        author=author,
        description=description,
    )

    # --- POUs ---
    pous = []
    for pou_dict in model.get("pous", []):
        body_dict = pou_dict.get("body", {})
        lang = body_dict.get("language", "ST")

        if lang == "LD":
            rungs = []
            for rung_dict in body_dict.get("rungs", []):
                lpr = None
                rpr = None
                lpr_d = rung_dict.get("left_power_rail")
                rpr_d = rung_dict.get("right_power_rail")
                if lpr_d:
                    lpr = LeftPowerRail(local_id=lpr_d.get("local_id", 1))
                if rpr_d:
                    rpr = RightPowerRail(local_id=rpr_d.get("local_id", 2))

                contacts = []
                for cd in rung_dict.get("contacts", []):
                    pos = cd.get("position")
                    contacts.append(Contact(
                        local_id=cd.get("local_id", 0),
                        variable=cd.get("variable", ""),
                        negated=cd.get("negated", False),
                        position=Position(x=pos["x"], y=pos["y"]) if pos else None,
                    ))

                coils = []
                for cd in rung_dict.get("coils", []):
                    pos = cd.get("position")
                    coils.append(Coil(
                        local_id=cd.get("local_id", 0),
                        variable=cd.get("variable", ""),
                        negated=cd.get("negated", False),
                        position=Position(x=pos["x"], y=pos["y"]) if pos else None,
                    ))

                fb_instances = []
                for fd in rung_dict.get("fb_instances", []):
                    pos = fd.get("position")
                    fb_instances.append(FBInstance(
                        local_id=fd.get("local_id", 0),
                        type_name=fd.get("type_name", ""),
                        instance_name=fd.get("instance_name", ""),
                        position=Position(x=pos["x"], y=pos["y"]) if pos else None,
                    ))

                rungs.append(Rung(
                    left_power_rail=lpr,
                    right_power_rail=rpr,
                    contacts=contacts,
                    coils=coils,
                    fb_instances=fb_instances,
                ))
            body = LDBody(rungs=rungs)

        elif lang == "ST":
            body = STBody(text=body_dict.get("text", ""))
        elif lang == "FBD":
            body = FBDBody(raw_xml=body_dict.get("raw_xml", ""))
        elif lang == "IL":
            body = ILBody(text=body_dict.get("text", ""))
        else:
            body = STBody(text="")

        var_blocks = []
        for vb_dict in pou_dict.get("var_blocks", []):
            variables = [
                Variable(
                    name=v["name"],
                    type_name=v.get("type_name", "BOOL"),
                    initial_value=v.get("initial_value"),
                )
                for v in vb_dict.get("variables", [])
            ]
            var_blocks.append(VarBlock(kind=vb_dict.get("kind", "local"), variables=variables))

        pous.append(POU(
            name=pou_dict.get("name", "Main"),
            pou_type=pou_dict.get("pou_type", "program"),
            var_blocks=var_blocks,
            body=body,
        ))

    # --- Instances ---
    configs = []
    for cfg_dict in model.get("configurations", []):
        resources = []
        for res_dict in cfg_dict.get("resources", []):
            tasks = [
                TaskConfig(
                    name=t.get("name", ""),
                    interval=t.get("interval"),
                    priority=t.get("priority", 0),
                )
                for t in res_dict.get("tasks", [])
            ]
            prog_instances = [
                ProgramInstance(
                    name=pi.get("name", ""),
                    type_name=pi.get("type_name", ""),
                    task_name=pi.get("task_name"),
                )
                for pi in res_dict.get("program_instances", [])
            ]
            resources.append(Resource(
                name=res_dict.get("name", ""),
                type_name=res_dict.get("type_name", "PLC"),
                tasks=tasks,
                program_instances=prog_instances,
            ))
        configs.append(Configuration(name=cfg_dict.get("name", ""), resources=resources))

    return Project(
        content_header=content_header,
        types=Types(pous=pous),
        instances=Instances(configurations=configs),
    )


async def export_plcopen_xml(ctx: ProjectCtx, args: bytes) -> str:
    """Serialise a model dict to PLCopen XML."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    model = a.get("model")
    if not isinstance(model, dict):
        return err_payload("'model' must be an object", "INVALID_MODEL")
    if "pous" not in model:
        return err_payload("'model.pous' is required", "INVALID_MODEL")

    project_name = (
        a.get("project_name")
        or model.get("project_name", "")
        or "Untitled"
    )
    author = a.get("author") or model.get("author", "")
    description = a.get("description") or model.get("description", "")

    try:
        from kerf_plc.plcopen.writer import dumps
    except Exception as exc:
        return err_payload(f"plcopen writer unavailable: {exc}", "INTERNAL")

    try:
        project = _model_to_project(model, project_name, author, description)
    except Exception as exc:
        return err_payload(f"model conversion error: {exc}", "INVALID_MODEL")

    try:
        xml = dumps(project)
    except Exception as exc:
        return err_payload(f"XML serialisation error: {exc}", "INTERNAL")

    rung_count = sum(len(p.rungs) for p in project.pous)
    return ok_payload({
        "ok": True,
        "project_name": project_name,
        "pou_count": len(project.pous),
        "rung_count": rung_count,
        "xml": xml,
    })
