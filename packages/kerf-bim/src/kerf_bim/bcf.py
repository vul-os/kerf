"""
bcf.py — BCF 3.0 (BIM Collaboration Format) issue-manager implementation.

BCF 3.0 is a buildingSMART-standardised ZIP-based format for exchanging clash /
issue / RFI annotations between BIM authoring tools (ArchiCAD, Revit, Navisworks,
Kerf, …).

Spec reference: https://github.com/buildingSMART/BCF-API / ISO 19650-series.

ZIP structure (one folder per topic GUID):
    bcf.version                         — version marker (JSON)
    project.bcfp                        — project metadata (JSON)
    <topic-guid>/
        markup.bcf                      — topic + comments (JSON)
        viewpoint-<vp-guid>.bcfv        — camera viewpoint (JSON)
        snapshot-<vp-guid>.png          — screenshot (binary, optional)
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ── BCF 3.0 version marker ────────────────────────────────────────────────────

BCF_VERSION = "3.0"
BCF_SCHEMA  = "https://raw.githubusercontent.com/buildingSMART/BCF-XML/release_3_0/Schemas/version.xsd"

VALID_TOPIC_TYPES = {"Clash", "Issue", "Request", "Fault", "Inquiry"}
VALID_PRIORITIES  = {"Critical", "Normal", "Minor"}
VALID_STATUSES    = {"Open", "In Progress", "Resolved", "Closed"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_guid() -> str:
    return str(uuid.uuid4())


def _validate(value: str, allowed: set[str], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} must be one of {sorted(allowed)!r}, got {value!r}")
    return value


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class BcfTopic:
    guid: str
    title: str
    description: str
    topic_type: str          # "Clash" | "Issue" | "Request" | "Fault" | "Inquiry"
    priority: str            # "Critical" | "Normal" | "Minor"
    status: str              # "Open" | "In Progress" | "Resolved" | "Closed"
    assigned_to: str         # email address
    creation_date_iso: str
    creation_author: str
    modified_date_iso: str
    due_date_iso: str = ""


@dataclass
class BcfComment:
    guid: str
    topic_guid: str
    comment: str
    author: str
    date_iso: str
    modified_date_iso: str = ""


@dataclass
class BcfViewpoint:
    guid: str
    topic_guid: str
    camera_position_xyz: tuple    # (x, y, z) in metres
    camera_target_xyz: tuple      # (x, y, z) in metres
    field_of_view_deg: float = 60.0
    snapshot_filename: str = ""


@dataclass
class BcfProject:
    project_id: str
    name: str
    topics: list[BcfTopic]    = field(default_factory=list)
    comments: list[BcfComment] = field(default_factory=list)
    viewpoints: list[BcfViewpoint] = field(default_factory=list)


# ── CRUD helpers ─────────────────────────────────────────────────────────────

def create_topic(
    project: BcfProject,
    title: str,
    description: str = "",
    topic_type: str = "Issue",
    priority: str = "Normal",
    status: str = "Open",
    assigned_to: str = "",
    creation_author: str = "",
    due_date_iso: str = "",
) -> BcfTopic:
    """Create a new BcfTopic and append it to the project."""
    _validate(topic_type, VALID_TOPIC_TYPES, "topic_type")
    _validate(priority,   VALID_PRIORITIES,  "priority")
    _validate(status,     VALID_STATUSES,    "status")

    now = _now_iso()
    topic = BcfTopic(
        guid              = _new_guid(),
        title             = title,
        description       = description,
        topic_type        = topic_type,
        priority          = priority,
        status            = status,
        assigned_to       = assigned_to,
        creation_date_iso = now,
        creation_author   = creation_author,
        modified_date_iso = now,
        due_date_iso      = due_date_iso,
    )
    project.topics.append(topic)
    return topic


def add_comment(
    project: BcfProject,
    topic_guid: str,
    comment: str,
    author: str = "",
) -> BcfComment:
    """Append a comment to the topic identified by *topic_guid*."""
    topic_guids = {t.guid for t in project.topics}
    if topic_guid not in topic_guids:
        raise ValueError(f"Topic {topic_guid!r} not found in project")

    now = _now_iso()
    bcf_comment = BcfComment(
        guid              = _new_guid(),
        topic_guid        = topic_guid,
        comment           = comment,
        author            = author,
        date_iso          = now,
        modified_date_iso = now,
    )
    project.comments.append(bcf_comment)
    return bcf_comment


def add_viewpoint(
    project: BcfProject,
    topic_guid: str,
    camera_position_xyz: tuple,
    camera_target_xyz: tuple,
    field_of_view_deg: float = 60.0,
    snapshot_filename: str = "",
) -> BcfViewpoint:
    """Attach a camera viewpoint to the topic identified by *topic_guid*."""
    topic_guids = {t.guid for t in project.topics}
    if topic_guid not in topic_guids:
        raise ValueError(f"Topic {topic_guid!r} not found in project")

    vp = BcfViewpoint(
        guid                 = _new_guid(),
        topic_guid           = topic_guid,
        camera_position_xyz  = tuple(camera_position_xyz),
        camera_target_xyz    = tuple(camera_target_xyz),
        field_of_view_deg    = float(field_of_view_deg),
        snapshot_filename    = snapshot_filename,
    )
    project.viewpoints.append(vp)
    return vp


def update_topic_status(
    project: BcfProject,
    topic_guid: str,
    new_status: str,
) -> bool:
    """Update the status of a topic. Returns True on success, False if not found."""
    _validate(new_status, VALID_STATUSES, "new_status")
    for topic in project.topics:
        if topic.guid == topic_guid:
            topic.status           = new_status
            topic.modified_date_iso = _now_iso()
            return True
    return False


# ── Summarise ────────────────────────────────────────────────────────────────

def summarize_project(project: BcfProject) -> dict[str, int]:
    """Return counts per status, per priority, and total/comment/viewpoint totals."""
    summary: dict[str, int] = {
        "total_topics":    len(project.topics),
        "total_comments":  len(project.comments),
        "total_viewpoints": len(project.viewpoints),
    }
    for s in VALID_STATUSES:
        summary[f"status_{s.lower().replace(' ', '_')}"] = sum(
            1 for t in project.topics if t.status == s
        )
    for p in VALID_PRIORITIES:
        summary[f"priority_{p.lower()}"] = sum(
            1 for t in project.topics if t.priority == p
        )
    return summary


# ── BCF 3.0 serialisation helpers ────────────────────────────────────────────

def _topic_to_markup(topic: BcfTopic, comments: list[BcfComment], viewpoints: list[BcfViewpoint]) -> dict:
    """Serialise a topic + its comments and viewpoint references as a BCF markup dict."""
    return {
        "Topic": {
            "Guid":             topic.guid,
            "Title":            topic.title,
            "Description":      topic.description,
            "TopicType":        topic.topic_type,
            "Priority":         topic.priority,
            "TopicStatus":      topic.status,
            "AssignedTo":       topic.assigned_to,
            "CreationDate":     topic.creation_date_iso,
            "CreationAuthor":   topic.creation_author,
            "ModifiedDate":     topic.modified_date_iso,
            "DueDate":          topic.due_date_iso,
        },
        "Comments": [
            {
                "Guid":          c.guid,
                "Comment":       c.comment,
                "Author":        c.author,
                "Date":          c.date_iso,
                "ModifiedDate":  c.modified_date_iso,
            }
            for c in comments if c.topic_guid == topic.guid
        ],
        "Viewpoints": [
            {"ViewpointGuid": vp.guid, "SnapshotFilename": vp.snapshot_filename}
            for vp in viewpoints if vp.topic_guid == topic.guid
        ],
    }


def _viewpoint_to_bcfv(vp: BcfViewpoint) -> dict:
    px, py, pz = vp.camera_position_xyz
    tx, ty, tz = vp.camera_target_xyz
    # Direction vector (normalised)
    dx, dy, dz = tx - px, ty - py, tz - pz
    length = max((dx**2 + dy**2 + dz**2) ** 0.5, 1e-9)
    dx, dy, dz = dx / length, dy / length, dz / length
    return {
        "Guid": vp.guid,
        "PerspectiveCamera": {
            "CameraViewPoint": {"X": px, "Y": py, "Z": pz},
            "CameraDirection":  {"X": dx, "Y": dy, "Z": dz},
            "CameraUpVector":   {"X": 0.0, "Y": 0.0, "Z": 1.0},
            "FieldOfView":      vp.field_of_view_deg,
        },
    }


def _markup_to_topic(markup: dict) -> BcfTopic:
    t = markup["Topic"]
    return BcfTopic(
        guid              = t["Guid"],
        title             = t.get("Title", ""),
        description       = t.get("Description", ""),
        topic_type        = t.get("TopicType", "Issue"),
        priority          = t.get("Priority", "Normal"),
        status            = t.get("TopicStatus", "Open"),
        assigned_to       = t.get("AssignedTo", ""),
        creation_date_iso = t.get("CreationDate", ""),
        creation_author   = t.get("CreationAuthor", ""),
        modified_date_iso = t.get("ModifiedDate", ""),
        due_date_iso      = t.get("DueDate", ""),
    )


def _markup_to_comments(markup: dict, topic_guid: str) -> list[BcfComment]:
    return [
        BcfComment(
            guid              = c.get("Guid", _new_guid()),
            topic_guid        = topic_guid,
            comment           = c.get("Comment", ""),
            author            = c.get("Author", ""),
            date_iso          = c.get("Date", ""),
            modified_date_iso = c.get("ModifiedDate", ""),
        )
        for c in markup.get("Comments", [])
    ]


def _markup_to_viewpoints(markup: dict, bcfv_map: dict[str, dict], topic_guid: str) -> list[BcfViewpoint]:
    vps = []
    for vref in markup.get("Viewpoints", []):
        vp_guid = vref.get("ViewpointGuid", "")
        bcfv = bcfv_map.get(vp_guid, {})
        cam = bcfv.get("PerspectiveCamera", {})
        pos = cam.get("CameraViewPoint", {"X": 0, "Y": 0, "Z": 0})
        fov = cam.get("FieldOfView", 60.0)
        # Reconstruct a target 1 unit along direction
        dirv = cam.get("CameraDirection", {"X": 1, "Y": 0, "Z": 0})
        target = (pos["X"] + dirv["X"], pos["Y"] + dirv["Y"], pos["Z"] + dirv["Z"])
        vps.append(BcfViewpoint(
            guid                = vp_guid or _new_guid(),
            topic_guid          = topic_guid,
            camera_position_xyz = (pos["X"], pos["Y"], pos["Z"]),
            camera_target_xyz   = target,
            field_of_view_deg   = fov,
            snapshot_filename   = vref.get("SnapshotFilename", ""),
        ))
    return vps


# ── Export ───────────────────────────────────────────────────────────────────

def export_bcf_zip(project: BcfProject, output_path: str) -> dict:
    """
    Write a BCF 3.0 compliant .bcf zip to *output_path*.

    Returns a summary dict::

        {"path": output_path, "topics": n, "comments": m, "viewpoints": k}
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # bcf.version
        zf.writestr("bcf.version", json.dumps({
            "VersionId":   BCF_VERSION,
            "DetailedVersion": BCF_VERSION,
        }, indent=2))

        # project.bcfp
        zf.writestr("project.bcfp", json.dumps({
            "Project": {
                "ProjectId": project.project_id,
                "Name":      project.name,
            }
        }, indent=2))

        # One folder per topic
        for topic in project.topics:
            folder = topic.guid

            # markup.bcf
            markup = _topic_to_markup(topic, project.comments, project.viewpoints)
            zf.writestr(f"{folder}/markup.bcf", json.dumps(markup, indent=2))

            # Viewpoint files
            for vp in project.viewpoints:
                if vp.topic_guid != topic.guid:
                    continue
                bcfv = _viewpoint_to_bcfv(vp)
                zf.writestr(f"{folder}/viewpoint-{vp.guid}.bcfv", json.dumps(bcfv, indent=2))

    data = buf.getvalue()
    with open(output_path, "wb") as fh:
        fh.write(data)

    return {
        "path":       output_path,
        "topics":     len(project.topics),
        "comments":   len(project.comments),
        "viewpoints": len(project.viewpoints),
    }


# ── Import ───────────────────────────────────────────────────────────────────

def import_bcf_zip(zip_path: str) -> BcfProject:
    """
    Parse a BCF 3.0 (or 2.x) .bcf zip and return a :class:`BcfProject`.

    Handles both .bcfzip and .bcf extensions (same format).
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())

        # Project metadata
        project_id = _new_guid()
        project_name = "Imported BCF Project"
        if "project.bcfp" in names:
            proj_data = json.loads(zf.read("project.bcfp"))
            proj_info = proj_data.get("Project", {})
            project_id   = proj_info.get("ProjectId", project_id)
            project_name = proj_info.get("Name", project_name)

        project = BcfProject(
            project_id = project_id,
            name       = project_name,
        )

        # Collect topic folders (any uuid4-shaped directory)
        topic_folders = set()
        for name in names:
            parts = name.split("/")
            if len(parts) >= 2 and "/" + parts[0] + "/" not in {"/bcf.version", "/project.bcfp"}:
                try:
                    uuid.UUID(parts[0])
                    topic_folders.add(parts[0])
                except ValueError:
                    pass

        for folder in topic_folders:
            markup_key = f"{folder}/markup.bcf"
            if markup_key not in names:
                continue

            markup = json.loads(zf.read(markup_key))

            # Pre-load all .bcfv files for this topic folder
            bcfv_map: dict[str, dict] = {}
            for n in names:
                if n.startswith(f"{folder}/") and n.endswith(".bcfv"):
                    bcfv_data = json.loads(zf.read(n))
                    bcfv_map[bcfv_data.get("Guid", "")] = bcfv_data

            topic      = _markup_to_topic(markup)
            comments   = _markup_to_comments(markup, topic.guid)
            viewpoints = _markup_to_viewpoints(markup, bcfv_map, topic.guid)

            project.topics.extend([topic])
            project.comments.extend(comments)
            project.viewpoints.extend(viewpoints)

    return project
