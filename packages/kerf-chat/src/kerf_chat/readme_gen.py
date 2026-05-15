"""Workshop README auto-generation helper.

This module builds an AI-generated Markdown README for a Workshop-published
project.  It is intentionally kept stateless and side-effect-free: callers
own the LLM provider instance and the storage write.

Public surface
--------------
generate_readme(project, bom_rows, parts_rows, llm_provider, model_id)
    -> str (Markdown text)

compose_readme_prompt(project, bom_rows, parts_rows)
    -> (system_prompt: str, user_prompt: str)

The ``compose_readme_prompt`` helper is separated out so tests can call it
without touching the LLM at all.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Prompt composition
# ---------------------------------------------------------------------------

def compose_readme_prompt(
    project: dict[str, Any],
    bom_rows: list[dict[str, Any]] | None = None,
    parts_rows: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Build the (system, user) prompt pair for README generation.

    Parameters
    ----------
    project:
        Minimal project dict with at minimum ``name``, ``description``,
        ``tags`` (list[str]).  Optional: ``params`` (dict), ``license``.
    bom_rows:
        List of BOM line dicts.  Each entry should have ``qty``, ``part_name``
        / ``name``, and optionally ``description``, ``supplier``.
    parts_rows:
        ``kerf_parts`` provenance / attribution rows.  Each entry should have
        ``name`` and optionally ``source_url``, ``license``, ``author``.

    Returns
    -------
    (system_prompt, user_prompt)
    """
    name = project.get("name") or "Unnamed project"
    description = (project.get("description") or "").strip()
    tags = project.get("tags") or []
    params = project.get("params") or {}
    license_spdx = project.get("license") or "MIT"

    tag_line = ", ".join(tags) if tags else "none"

    system_prompt = (
        "You are a technical writer for an open-source parametric CAD platform called Kerf. "
        "Your job is to write clear, concise, developer-friendly README files for user-published "
        "CAD projects. Write in Markdown. Be specific and practical. Do not add fake information. "
        "If data is missing, omit the section rather than guessing. "
        "Structure: # Title, ## Overview, ## Parameters (if any), ## Bill of Materials (if any), "
        "## Parts & Attribution (if any), ## Fork & Edit Guide, ## License."
    )

    user_lines = [
        f"Write a README for this Kerf Workshop project.",
        f"",
        f"**Project name:** {name}",
    ]
    if description:
        user_lines += [f"**Description:** {description}", ""]
    user_lines += [f"**Tags:** {tag_line}", ""]

    if params:
        user_lines.append("**Parameters:**")
        for k, v in params.items():
            user_lines.append(f"- `{k}`: {v}")
        user_lines.append("")

    if bom_rows:
        user_lines.append("**Bill of Materials:**")
        for row in bom_rows:
            qty = row.get("qty") or row.get("quantity") or 1
            pname = row.get("part_name") or row.get("name") or "?"
            desc = row.get("description") or ""
            supplier = row.get("supplier") or ""
            line = f"- {qty}x {pname}"
            if desc:
                line += f" — {desc}"
            if supplier:
                line += f" (supplier: {supplier})"
            user_lines.append(line)
        user_lines.append("")

    if parts_rows:
        user_lines.append("**Parts & Attribution:**")
        for row in parts_rows:
            pname = row.get("name") or "?"
            author = row.get("author") or ""
            source = row.get("source_url") or ""
            lic = row.get("license") or ""
            line = f"- {pname}"
            if author:
                line += f" by {author}"
            if source:
                line += f" ({source})"
            if lic:
                line += f" [{lic}]"
            user_lines.append(line)
        user_lines.append("")

    user_lines += [
        f"**License:** {license_spdx}",
        "",
        "Include a brief Fork & Edit Guide explaining how to fork this project on Kerf and "
        "edit the parameters or geometry. End with a License section. "
        "Keep the README under 600 words.",
    ]

    return system_prompt, "\n".join(user_lines)


# ---------------------------------------------------------------------------
# Generation (requires a live LLM provider)
# ---------------------------------------------------------------------------

def generate_readme(
    project: dict[str, Any],
    bom_rows: list[dict[str, Any]] | None = None,
    parts_rows: list[dict[str, Any]] | None = None,
    llm_provider=None,
    model_id: str = "claude-haiku-4-5",
) -> str:
    """Generate a Markdown README for a Workshop project via LLM.

    Parameters
    ----------
    project, bom_rows, parts_rows:
        See ``compose_readme_prompt``.
    llm_provider:
        An instance of ``kerf_chat.llm.Provider`` (or any object with a
        ``complete(CompleteRequest) -> CompleteResponse`` method).
        When ``None``, the function raises ``ValueError`` — callers that want
        a no-LLM fallback should call ``compose_readme_prompt`` directly and
        build a template.
    model_id:
        Model to use.  Defaults to haiku (cheapest, fast enough for docs).

    Returns
    -------
    Markdown string.
    """
    if llm_provider is None:
        raise ValueError("llm_provider is required for README generation")

    from kerf_chat.llm import CompleteRequest, Message

    system_prompt, user_prompt = compose_readme_prompt(project, bom_rows, parts_rows)

    req = CompleteRequest(
        model=model_id,
        system=system_prompt,
        messages=[Message(role="user", content=user_prompt)],
        max_tokens=1024,
        temperature=0.3,
    )
    resp = llm_provider.complete(req)
    return resp.content.strip()


# ---------------------------------------------------------------------------
# Template fallback (used when no LLM is configured)
# ---------------------------------------------------------------------------

def generate_readme_template(
    project: dict[str, Any],
    bom_rows: list[dict[str, Any]] | None = None,
    parts_rows: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a minimal template README without requiring a live LLM.

    Used as the graceful fallback when no LLM provider is available.
    The template includes all structural sections populated from the
    project data so it is still useful — just not prose-generated.
    """
    name = project.get("name") or "Untitled"
    description = (project.get("description") or "").strip()
    tags = project.get("tags") or []
    params = project.get("params") or {}
    license_spdx = project.get("license") or "MIT"

    lines = [f"# {name}", ""]

    if description:
        lines += ["## Overview", "", description, ""]
    else:
        lines += ["## Overview", "", "_No description provided._", ""]

    if tags:
        lines += [f"**Tags:** {', '.join(tags)}", ""]

    if params:
        lines += ["## Parameters", ""]
        lines += ["| Parameter | Value |", "|-----------|-------|"]
        for k, v in params.items():
            lines.append(f"| `{k}` | {v} |")
        lines.append("")

    if bom_rows:
        lines += ["## Bill of Materials", ""]
        lines += ["| Qty | Part | Notes |", "|-----|------|-------|"]
        for row in bom_rows:
            qty = row.get("qty") or row.get("quantity") or 1
            pname = row.get("part_name") or row.get("name") or "?"
            desc = row.get("description") or ""
            lines.append(f"| {qty} | {pname} | {desc} |")
        lines.append("")

    if parts_rows:
        lines += ["## Parts & Attribution", ""]
        for row in parts_rows:
            pname = row.get("name") or "?"
            author = row.get("author") or ""
            source = row.get("source_url") or ""
            lic = row.get("license") or ""
            entry = f"- **{pname}**"
            if author:
                entry += f" — {author}"
            if source:
                entry += f" ([source]({source}))"
            if lic:
                entry += f" `{lic}`"
            lines.append(entry)
        lines.append("")

    lines += [
        "## Fork & Edit Guide",
        "",
        f"1. Open the [Workshop listing](https://kerf.design/workshop) and click **Fork to my projects**.",
        "2. The project will appear in your private workspace.",
        "3. Edit parameters, geometry, or files directly in the Kerf editor.",
        "4. Re-publish when ready to share your version.",
        "",
        "## License",
        "",
        f"Released under the **{license_spdx}** license.",
        "",
    ]

    return "\n".join(lines)
