#!/usr/bin/env python3
"""Realistic dev-seed data for local Kerf development.

Creates four example projects in the local database under a seed workspace:
  - _seed_BIM Example       : 1 BIM project (walls + floor + roof shell)
  - _seed_Mechanical Part   : 1 mechanical project with 5 features
  - _seed_PCB Example       : 1 PCB project (3 components)
  - _seed_Component Library : 1 library project (10 BOM parts with distributors)

Idempotent: any project whose name starts with the _seed_ prefix is skipped on
re-run (checked by workspace + name). Safe to run repeatedly.

Connects via DATABASE_URL env var; defaults to the local dev URL.
# pc role + kerf db (per project memory)
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# DB connectivity — try SQLAlchemy (real Postgres); fall back to sqlite for
# unit-test purposes when SA is available and we have a sqlite:// URL.
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    # pc role + kerf db (per project memory)
    "postgres://pc@localhost:5432/kerf?sslmode=disable",
)

_SEED_PREFIX = "_seed_"
_SEED_USER_EMAIL = "seed-dev@kerf.local"
_SEED_WORKSPACE_SLUG = "seed-dev-workspace"
_NOW = datetime.now(tz=timezone.utc)


def _make_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Low-level DB helpers (sqlalchemy core — avoids needing the ORM for seeds)
# ---------------------------------------------------------------------------

def _get_engine():
    try:
        from sqlalchemy import create_engine
    except ImportError:
        print("ERROR: sqlalchemy not installed. Run: pip install sqlalchemy", file=sys.stderr)
        sys.exit(1)

    url = DATABASE_URL
    # asyncpg DSN → psycopg2 DSN for sync SQLAlchemy (postgres:// → postgresql://)
    if url.startswith("postgres://"):
        url = "postgresql" + url[len("postgres"):]
    elif url.startswith("postgres+asyncpg://"):
        url = "postgresql" + url[len("postgres+asyncpg"):]

    return create_engine(url, future=True)


def _ensure_tables(conn) -> None:
    """Create only the tables this seed needs, IF NOT EXISTS.

    We do not use Alembic/our migration runner here so that the seed can also
    run against a fresh sqlite:// DB in tests without requiring asyncpg.
    """
    conn.execute(_sql("""
        CREATE TABLE IF NOT EXISTS users (
            id          TEXT PRIMARY KEY,
            email       TEXT UNIQUE NOT NULL,
            name        TEXT NOT NULL DEFAULT '',
            avatar_url  TEXT NOT NULL DEFAULT '',
            account_role TEXT NOT NULL DEFAULT 'user',
            is_system   BOOLEAN NOT NULL DEFAULT FALSE,
            password_hash TEXT,
            google_id   TEXT,
            avatar_storage_key TEXT,
            avatar_updated_at  TEXT,
            is_verified_publisher BOOLEAN NOT NULL DEFAULT FALSE,
            preferences TEXT NOT NULL DEFAULT '{}',
            created_at  TEXT NOT NULL
        )
    """))
    conn.execute(_sql("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id          TEXT PRIMARY KEY,
            slug        TEXT UNIQUE NOT NULL,
            name        TEXT NOT NULL,
            created_by  TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            avatar_storage_key TEXT
        )
    """))
    conn.execute(_sql("""
        CREATE TABLE IF NOT EXISTS workspace_members (
            workspace_id TEXT NOT NULL,
            user_id      TEXT NOT NULL,
            role         TEXT NOT NULL DEFAULT 'owner',
            created_at   TEXT NOT NULL,
            PRIMARY KEY (workspace_id, user_id)
        )
    """))
    conn.execute(_sql("""
        CREATE TABLE IF NOT EXISTS projects (
            id           TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            name         TEXT NOT NULL,
            description  TEXT NOT NULL DEFAULT '',
            visibility   TEXT NOT NULL DEFAULT 'private',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            thumbnail_storage_key TEXT,
            thumbnail_updated_at  TEXT,
            tags         TEXT NOT NULL DEFAULT '[]'
        )
    """))
    conn.execute(_sql("""
        CREATE TABLE IF NOT EXISTS files (
            id          TEXT PRIMARY KEY,
            project_id  TEXT NOT NULL,
            parent_id   TEXT,
            name        TEXT NOT NULL,
            kind        TEXT NOT NULL DEFAULT 'file',
            content     TEXT NOT NULL DEFAULT '',
            storage_key TEXT,
            mime_type   TEXT,
            size        INTEGER,
            deleted_at  TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            mesh_storage_key TEXT,
            extension   TEXT
        )
    """))


def _sql(stmt: str):
    from sqlalchemy import text
    return text(stmt)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _upsert_user(conn) -> str:
    row = conn.execute(
        _sql("SELECT id FROM users WHERE email = :email"),
        {"email": _SEED_USER_EMAIL},
    ).fetchone()
    if row:
        return str(row[0])
    uid = _make_id()
    conn.execute(
        _sql("""
            INSERT INTO users
              (id, email, name, avatar_url, account_role, is_system,
               is_verified_publisher, preferences, created_at)
            VALUES
              (:id, :email, :name, '', 'user', FALSE, FALSE, '{}', :now)
        """),
        {"id": uid, "email": _SEED_USER_EMAIL, "name": "Seed Dev User", "now": _NOW.isoformat()},
    )
    return uid


def _upsert_workspace(conn, user_id: str) -> str:
    row = conn.execute(
        _sql("SELECT id FROM workspaces WHERE slug = :slug"),
        {"slug": _SEED_WORKSPACE_SLUG},
    ).fetchone()
    if row:
        return str(row[0])
    wid = _make_id()
    conn.execute(
        _sql("""
            INSERT INTO workspaces (id, slug, name, created_by, created_at, updated_at)
            VALUES (:id, :slug, :name, :created_by, :now, :now)
        """),
        {
            "id": wid,
            "slug": _SEED_WORKSPACE_SLUG,
            "name": "Seed Dev Workspace",
            "created_by": user_id,
            "now": _NOW.isoformat(),
        },
    )
    conn.execute(
        _sql("""
            INSERT INTO workspace_members (workspace_id, user_id, role, created_at)
            VALUES (:wid, :uid, 'owner', :now)
            ON CONFLICT (workspace_id, user_id) DO NOTHING
        """),
        {"wid": wid, "uid": user_id, "now": _NOW.isoformat()},
    )
    return wid


def _project_exists(conn, workspace_id: str, name: str) -> bool:
    row = conn.execute(
        _sql("SELECT id FROM projects WHERE workspace_id = :wid AND name = :name"),
        {"wid": workspace_id, "name": name},
    ).fetchone()
    return row is not None


def _create_project(conn, workspace_id: str, name: str, description: str, tags: list[str]) -> str:
    pid = _make_id()
    conn.execute(
        _sql("""
            INSERT INTO projects
              (id, workspace_id, name, description, visibility, created_at, updated_at, tags)
            VALUES
              (:id, :wid, :name, :desc, 'private', :now, :now, :tags)
        """),
        {
            "id": pid,
            "wid": workspace_id,
            "name": name,
            "desc": description,
            "now": _NOW.isoformat(),
            "tags": json.dumps(tags),
        },
    )
    return pid


def _create_file(
    conn,
    project_id: str,
    name: str,
    kind: str,
    content: dict | str,
    parent_id: str | None = None,
) -> str:
    fid = _make_id()
    raw = json.dumps(content) if isinstance(content, dict) else content
    conn.execute(
        _sql("""
            INSERT INTO files
              (id, project_id, parent_id, name, kind, content, created_at, updated_at)
            VALUES
              (:id, :pid, :parent_id, :name, :kind, :content, :now, :now)
        """),
        {
            "id": fid,
            "pid": project_id,
            "parent_id": parent_id,
            "name": name,
            "kind": kind,
            "content": raw,
            "now": _NOW.isoformat(),
        },
    )
    return fid


# ---------------------------------------------------------------------------
# Seed: BIM project — walls + floor + roof shell
# ---------------------------------------------------------------------------

def seed_bim_project(conn, workspace_id: str) -> int:
    name = f"{_SEED_PREFIX}BIM Example"
    if _project_exists(conn, workspace_id, name):
        print(f"  SKIP  {name} (already exists)")
        return 0
    pid = _create_project(conn, workspace_id, name, "Simple BIM building shell — walls/floor/roof", ["bim", "architecture"])

    # Root folder
    root = _create_file(conn, pid, "Building Shell", "folder", "", None)

    # Outer walls (4 walls in a 10m×8m plan, 3m height)
    walls = [
        ("North Wall",  {"kind": "wall", "length": 10000, "height": 3000, "thickness": 250, "material": "concrete", "offset_x": 0,     "offset_y": 8000}),
        ("South Wall",  {"kind": "wall", "length": 10000, "height": 3000, "thickness": 250, "material": "concrete", "offset_x": 0,     "offset_y": 0}),
        ("East Wall",   {"kind": "wall", "length": 8000,  "height": 3000, "thickness": 250, "material": "concrete", "offset_x": 10000, "offset_y": 0}),
        ("West Wall",   {"kind": "wall", "length": 8000,  "height": 3000, "thickness": 250, "material": "concrete", "offset_x": 0,     "offset_y": 0}),
    ]
    for wname, wdata in walls:
        _create_file(conn, pid, wname, "sheet", {**wdata, "elevation": 0}, root)

    # Floor slab
    _create_file(conn, pid, "Ground Floor", "sheet", {
        "kind": "floor",
        "width": 10000,
        "length": 8000,
        "thickness": 200,
        "material": "reinforced_concrete",
        "elevation": 0,
    }, root)

    # Roof
    _create_file(conn, pid, "Flat Roof", "sheet", {
        "kind": "roof",
        "width": 10000,
        "length": 8000,
        "thickness": 150,
        "material": "flat_roof_system",
        "elevation": 3000,
        "slope_deg": 2.0,
    }, root)

    # Staircase stub
    _create_file(conn, pid, "Main Stair", "stair", {
        "kind": "stair",
        "num_risers": 12,
        "riser_height": 175,
        "tread_depth": 280,
        "width": 1200,
        "material": "concrete",
    }, root)

    print(f"  SEED  {name}  (6 files: 4 walls + floor + roof + stair)")
    return 1


# ---------------------------------------------------------------------------
# Seed: Mechanical part — 5-feature solid
# ---------------------------------------------------------------------------

def seed_mechanical_project(conn, workspace_id: str) -> int:
    name = f"{_SEED_PREFIX}Mechanical Part"
    if _project_exists(conn, workspace_id, name):
        print(f"  SKIP  {name} (already exists)")
        return 0
    pid = _create_project(conn, workspace_id, name, "Bracket with 5 modelling features", ["mechanical", "cad"])

    # Part file — 50-part assembly worth of detail via feature tree
    _create_file(conn, pid, "mounting_bracket.part", "part", {
        "unit": "mm",
        "material": "aluminium_6061",
        "features": [
            {
                "index": 0,
                "kind": "extrude",
                "name": "Base Plate",
                "sketch": {
                    "plane": "XY",
                    "entities": [
                        {"type": "rect", "x": 0, "y": 0, "w": 120, "h": 80},
                    ],
                },
                "depth": 10,
                "direction": "normal",
            },
            {
                "index": 1,
                "kind": "extrude",  # boss extrude on top face
                "name": "Central Boss",
                "sketch": {
                    "plane": "TOP_FACE_0",
                    "entities": [
                        {"type": "circle", "cx": 60, "cy": 40, "r": 20},
                    ],
                },
                "depth": 25,
                "direction": "normal",
            },
            {
                "index": 2,
                "kind": "feature",
                "feature_type": "hole",
                "name": "M8 Clearance Holes",
                "positions": [
                    {"x": 15, "y": 15},
                    {"x": 105, "y": 15},
                    {"x": 15, "y": 65},
                    {"x": 105, "y": 65},
                ],
                "diameter": 9.0,
                "depth": 10,
                "hole_type": "simple",
            },
            {
                "index": 3,
                "kind": "feature",
                "feature_type": "fillet",
                "name": "Plate Fillets",
                "edge_selector": "base_plate_vertical_edges",
                "radius": 4.0,
            },
            {
                "index": 4,
                "kind": "feature",
                "feature_type": "chamfer",
                "name": "Boss Top Chamfer",
                "edge_selector": "central_boss_top_edge",
                "distance": 2.0,
            },
        ],
    })

    # Drawing file
    _create_file(conn, pid, "mounting_bracket.drawing", "drawing", {
        "title": "Mounting Bracket",
        "scale": "1:1",
        "standard": "ISO",
        "views": ["front", "top", "right", "isometric"],
        "tolerances": "general_ISO_2768_m",
    })

    # Simulation setup
    _create_file(conn, pid, "static_analysis.simulation", "simulation", {
        "type": "static_structural",
        "material": "aluminium_6061",
        "loads": [{"face": "boss_top", "force_N": 500, "direction": "-Z"}],
        "constraints": [{"face": "base_bottom", "type": "fixed"}],
        "mesh_size_mm": 2.0,
    })

    print(f"  SEED  {name}  (3 files: part + drawing + simulation)")
    return 1


# ---------------------------------------------------------------------------
# Seed: PCB project — 3 components (resistor + capacitor + LED)
# ---------------------------------------------------------------------------

def seed_pcb_project(conn, workspace_id: str) -> int:
    name = f"{_SEED_PREFIX}PCB Example"
    if _project_exists(conn, workspace_id, name):
        print(f"  SKIP  {name} (already exists)")
        return 0
    pid = _create_project(conn, workspace_id, name, "Simple PCB with 3 passives and an LED", ["electronics", "pcb"])

    _create_file(conn, pid, "blinky.circuit", "circuit", {
        "board": {"width_mm": 50, "height_mm": 40, "layers": 2, "copper_weight_oz": 1},
        "design_rules": {
            "min_trace_width_mm": 0.15,
            "min_clearance_mm": 0.15,
            "min_drill_mm": 0.3,
        },
        "schematic": {
            "nets": ["VCC", "GND", "LED_ANODE"],
            "components": [
                {
                    "ref": "R1",
                    "value": "330R",
                    "mpn": "CRCW0402330RFKED",
                    "footprint": "Resistor_SMD:R_0402_1005Metric",
                    "description": "Current limiting resistor 330 Ohm 1% 0402",
                    "pins": {"1": "VCC", "2": "LED_ANODE"},
                    "placement": {"x_mm": 10, "y_mm": 20, "rotation_deg": 0, "side": "front"},
                },
                {
                    "ref": "C1",
                    "value": "100nF",
                    "mpn": "GRM155R71C104KA88D",
                    "footprint": "Capacitor_SMD:C_0402_1005Metric",
                    "description": "Bypass capacitor 100nF 16V X7R 0402",
                    "pins": {"1": "VCC", "2": "GND"},
                    "placement": {"x_mm": 20, "y_mm": 20, "rotation_deg": 90, "side": "front"},
                },
                {
                    "ref": "D1",
                    "value": "LED_RED",
                    "mpn": "LTST-C190CKT",
                    "footprint": "LED_SMD:LED_0805_2012Metric",
                    "description": "Red LED 0805 2.1V 20mA",
                    "pins": {"A": "LED_ANODE", "K": "GND"},
                    "placement": {"x_mm": 30, "y_mm": 20, "rotation_deg": 0, "side": "front"},
                },
            ],
        },
    })

    # BOM for the PCB
    _create_file(conn, pid, "blinky_bom.csv", "file", (
        "Ref,Value,MPN,Footprint,Qty,Description\n"
        "R1,330R,CRCW0402330RFKED,R_0402_1005Metric,1,Current limit resistor\n"
        "C1,100nF,GRM155R71C104KA88D,C_0402_1005Metric,1,Bypass cap\n"
        "D1,LED_RED,LTST-C190CKT,LED_0805_2012Metric,1,Red indicator LED\n"
    ))

    print(f"  SEED  {name}  (2 files: circuit + BOM)")
    return 1


# ---------------------------------------------------------------------------
# Seed: Library / BOM project — 10 distributor-linked parts
# ---------------------------------------------------------------------------

# 10 realistic parts with distributor links
_LIBRARY_PARTS = [
    {
        "name": "M3×10 SHCS",
        "category": "fasteners/screws",
        "description": "M3×10 Socket Head Cap Screw, Class 8.8, Zinc",
        "mpn": "M3X10-SHCS-ZN",
        "manufacturer": "Bossard",
        "distributors": [
            {"name": "Digi-Key", "sku": "M3X10SHCSZN-ND", "unit_price_usd": 0.12, "stock": 10000, "moq": 50},
            {"name": "RS Components", "sku": "535-791", "unit_price_usd": 0.14, "stock": 5000, "moq": 100},
        ],
        "metadata": {"thread": "M3", "pitch_mm": 0.5, "length_mm": 10, "drive": "hex_socket", "standard": "ISO 4762"},
    },
    {
        "name": "M3 Hex Nut",
        "category": "fasteners/nuts",
        "description": "M3 Hex Nut, Class 8, Zinc",
        "mpn": "M3-HEX-NUT-ZN",
        "manufacturer": "Bossard",
        "distributors": [
            {"name": "Digi-Key", "sku": "M3HEXNUTZN-ND", "unit_price_usd": 0.05, "stock": 20000, "moq": 100},
        ],
        "metadata": {"thread": "M3", "standard": "ISO 4032", "width_across_flats_mm": 5.5},
    },
    {
        "name": "608-2RS Bearing",
        "category": "bearings/deep_groove",
        "description": "608-2RS Deep Groove Ball Bearing 8×22×7mm",
        "mpn": "608-2RS-SKF",
        "manufacturer": "SKF",
        "distributors": [
            {"name": "Digi-Key", "sku": "608-2RS-ND", "unit_price_usd": 1.85, "stock": 2000, "moq": 1},
            {"name": "Mouser", "sku": "527-608-2RS", "unit_price_usd": 1.95, "stock": 1500, "moq": 1},
        ],
        "metadata": {"bore_mm": 8, "od_mm": 22, "width_mm": 7, "seal": "2RS", "cage": "steel"},
    },
    {
        "name": "NEMA 17 Stepper Motor",
        "category": "motors/stepper",
        "description": "NEMA 17 Bipolar Stepper Motor 1.8°/step 0.9A 44Ncm",
        "mpn": "17HS4401",
        "manufacturer": "OMC",
        "distributors": [
            {"name": "Digi-Key", "sku": "17HS4401-ND", "unit_price_usd": 12.50, "stock": 500, "moq": 1},
        ],
        "metadata": {"step_angle_deg": 1.8, "current_A": 0.9, "torque_Ncm": 44, "frame": "NEMA17"},
    },
    {
        "name": "Arduino Nano 33 IoT",
        "category": "electronics/microcontrollers",
        "description": "Arduino Nano 33 IoT with WiFi/BLE SAMD21",
        "mpn": "ABX00027",
        "manufacturer": "Arduino",
        "distributors": [
            {"name": "Digi-Key", "sku": "1050-1160-ND", "unit_price_usd": 18.00, "stock": 300, "moq": 1},
            {"name": "Mouser", "sku": "782-ABX00027", "unit_price_usd": 18.00, "stock": 250, "moq": 1},
        ],
        "metadata": {"mcu": "SAMD21G18A", "flash_kb": 256, "wifi": True, "ble": True, "usb": "micro"},
    },
    {
        "name": "GT2 Timing Belt 6mm",
        "category": "mechanical/belts",
        "description": "GT2 Open Timing Belt 6mm Width 2mm Pitch",
        "mpn": "GT2-6MM-OPEN",
        "manufacturer": "Gates",
        "distributors": [
            {"name": "Digi-Key", "sku": "GT26MMOPEN-ND", "unit_price_usd": 0.45, "stock": 5000, "moq": 100, "unit": "mm"},
        ],
        "metadata": {"pitch_mm": 2.0, "width_mm": 6, "tooth_profile": "GT2"},
    },
    {
        "name": "LM358 Op-Amp",
        "category": "electronics/analog",
        "description": "LM358 Dual Op-Amp 1MHz SOIC-8",
        "mpn": "LM358DR",
        "manufacturer": "Texas Instruments",
        "distributors": [
            {"name": "Digi-Key", "sku": "296-1395-1-ND", "unit_price_usd": 0.35, "stock": 50000, "moq": 1},
            {"name": "Mouser", "sku": "595-LM358DR", "unit_price_usd": 0.38, "stock": 40000, "moq": 1},
        ],
        "metadata": {"package": "SOIC-8", "supply_V": "3-32", "bandwidth_MHz": 1, "channels": 2},
    },
    {
        "name": "6061-T6 Aluminium Sheet 3mm",
        "category": "materials/aluminium",
        "description": "6061-T6 Aluminium Sheet 3mm×300mm×300mm",
        "mpn": "AL6061-T6-3X300",
        "manufacturer": "Midwest Steel & Aluminium",
        "distributors": [
            {"name": "RS Components", "sku": "688-8563", "unit_price_usd": 8.50, "stock": 200, "moq": 1},
        ],
        "metadata": {"alloy": "6061-T6", "thickness_mm": 3, "width_mm": 300, "length_mm": 300, "temper": "T6"},
    },
    {
        "name": "12V DC Power Jack",
        "category": "electronics/connectors",
        "description": "2.1mm Barrel Jack 12V 5A Panel Mount",
        "mpn": "PJ-202A",
        "manufacturer": "CUI Devices",
        "distributors": [
            {"name": "Digi-Key", "sku": "CP-202A-ND", "unit_price_usd": 0.98, "stock": 3000, "moq": 1},
            {"name": "Mouser", "sku": "490-PJ-202A", "unit_price_usd": 1.05, "stock": 2500, "moq": 1},
        ],
        "metadata": {"inner_diameter_mm": 2.1, "outer_diameter_mm": 5.5, "max_current_A": 5, "voltage_V": 12},
    },
    {
        "name": "608 Bearing Spacer",
        "category": "mechanical/spacers",
        "description": "608 Bearing OD Spacer PETG Printed 22mm OD 8mm ID",
        "mpn": "KERF-SPACER-608",
        "manufacturer": "Kerf Workshop",
        "distributors": [],
        "metadata": {"od_mm": 22, "id_mm": 8, "length_mm": 7, "material": "PETG", "compatible_bearing": "608"},
    },
]


def seed_library_project(conn, workspace_id: str) -> int:
    name = f"{_SEED_PREFIX}Component Library"
    if _project_exists(conn, workspace_id, name):
        print(f"  SKIP  {name} (already exists)")
        return 0
    pid = _create_project(conn, workspace_id, name, "10-part BOM library with distributor links", ["library", "bom"])

    count = 0
    for part in _LIBRARY_PARTS:
        _create_file(conn, pid, part["name"], "part", {
            "version": 1,
            "name": part["name"],
            "description": part["description"],
            "category": part["category"],
            "manufacturer": part["manufacturer"],
            "mpn": part["mpn"],
            "distributors": part["distributors"],
            "visibility": "public",
            "metadata": part["metadata"],
        })
        count += 1

    print(f"  SEED  {name}  ({count} parts)")
    return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> None:
    print(f"seed_dev_data.py — DATABASE_URL: {DATABASE_URL.split('?')[0]}")
    print()

    engine = _get_engine()
    seeded = 0
    skipped = 0

    with engine.begin() as conn:
        _ensure_tables(conn)
        user_id = _upsert_user(conn)
        workspace_id = _upsert_workspace(conn, user_id)

        for seeder in [
            seed_bim_project,
            seed_mechanical_project,
            seed_pcb_project,
            seed_library_project,
        ]:
            n = seeder(conn, workspace_id)
            seeded += n
            skipped += 1 - n

    print()
    print(f"Done — {seeded} project(s) seeded, {skipped} skipped (already existed).")


if __name__ == "__main__":
    run()
