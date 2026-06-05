"""
archviz_assets.py — Kerf archviz asset library.

Provides categorised parametric placeholder assets (trees, shrubs, people, cars,
furniture) with bounding-box metadata.  Each asset is a lightweight stub — no
geometry mesh is stored here; consumers (scatter engine, renderer) reference
assets by id and use the bounding-box + default_scale for collision tests and
instanced rendering.

Asset schema
------------
{
  "id":            str,          # stable slug, e.g. "tree_deciduous_medium"
  "category":      str,          # "tree" | "shrub" | "person" | "car" | "furniture"
  "label":         str,          # human-readable name
  "default_scale": [sx, sy, sz], # scale in scene units (metres implied)
  "bbox":          [lx, ly, lz], # full extent at default_scale
  "tags":          [str, ...],   # free-form search tags
  "color_hint":    "#rrggbb",    # used by scatter preview dot colouring
}
"""
from __future__ import annotations

from typing import Any

# ── Colour hints per category (used by the scatter preview panel) ──────────
CATEGORY_COLORS: dict[str, str] = {
    "tree":      "#2d8a3e",
    "shrub":     "#5aad4e",
    "person":    "#e07040",
    "car":       "#4070c0",
    "furniture": "#9060b0",
    "ground_cover": "#8aaa44",
}

# ── Built-in asset catalogue ───────────────────────────────────────────────
_CATALOGUE: list[dict[str, Any]] = [
    # ── TREES ──────────────────────────────────────────────────────────────
    {
        "id":            "tree_deciduous_small",
        "category":      "tree",
        "label":         "Deciduous Tree (Small)",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [2.0, 2.0, 4.0],
        "tags":          ["tree", "deciduous", "small", "outdoor"],
        "color_hint":    CATEGORY_COLORS["tree"],
    },
    {
        "id":            "tree_deciduous_medium",
        "category":      "tree",
        "label":         "Deciduous Tree (Medium)",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [4.0, 4.0, 8.0],
        "tags":          ["tree", "deciduous", "medium", "outdoor"],
        "color_hint":    CATEGORY_COLORS["tree"],
    },
    {
        "id":            "tree_deciduous_large",
        "category":      "tree",
        "label":         "Deciduous Tree (Large)",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [6.0, 6.0, 14.0],
        "tags":          ["tree", "deciduous", "large", "outdoor"],
        "color_hint":    CATEGORY_COLORS["tree"],
    },
    {
        "id":            "tree_conifer_tall",
        "category":      "tree",
        "label":         "Conifer / Pine (Tall)",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [2.5, 2.5, 12.0],
        "tags":          ["tree", "conifer", "pine", "evergreen", "outdoor"],
        "color_hint":    CATEGORY_COLORS["tree"],
    },
    {
        "id":            "tree_palm",
        "category":      "tree",
        "label":         "Palm Tree",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [3.0, 3.0, 10.0],
        "tags":          ["tree", "palm", "tropical", "outdoor"],
        "color_hint":    CATEGORY_COLORS["tree"],
    },
    # ── SHRUBS ─────────────────────────────────────────────────────────────
    {
        "id":            "shrub_rounded",
        "category":      "shrub",
        "label":         "Rounded Shrub",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [1.2, 1.2, 0.8],
        "tags":          ["shrub", "bush", "rounded", "outdoor"],
        "color_hint":    CATEGORY_COLORS["shrub"],
    },
    {
        "id":            "shrub_columnar",
        "category":      "shrub",
        "label":         "Columnar Shrub",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [0.5, 0.5, 1.8],
        "tags":          ["shrub", "columnar", "boxwood", "outdoor"],
        "color_hint":    CATEGORY_COLORS["shrub"],
    },
    {
        "id":            "ground_cover_grass",
        "category":      "ground_cover",
        "label":         "Grass Clump",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [0.4, 0.4, 0.3],
        "tags":          ["grass", "ground_cover", "vegetation", "outdoor"],
        "color_hint":    CATEGORY_COLORS["ground_cover"],
    },
    # ── PEOPLE ─────────────────────────────────────────────────────────────
    {
        "id":            "person_standing_male",
        "category":      "person",
        "label":         "Standing Male Figure",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [0.5, 0.3, 1.78],
        "tags":          ["person", "human", "standing", "male", "scale_figure"],
        "color_hint":    CATEGORY_COLORS["person"],
    },
    {
        "id":            "person_standing_female",
        "category":      "person",
        "label":         "Standing Female Figure",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [0.45, 0.28, 1.65],
        "tags":          ["person", "human", "standing", "female", "scale_figure"],
        "color_hint":    CATEGORY_COLORS["person"],
    },
    {
        "id":            "person_seated",
        "category":      "person",
        "label":         "Seated Figure",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [0.55, 0.55, 1.05],
        "tags":          ["person", "human", "seated", "scale_figure"],
        "color_hint":    CATEGORY_COLORS["person"],
    },
    {
        "id":            "person_walking",
        "category":      "person",
        "label":         "Walking Figure",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [0.6, 0.8, 1.75],
        "tags":          ["person", "human", "walking", "scale_figure"],
        "color_hint":    CATEGORY_COLORS["person"],
    },
    # ── CARS ───────────────────────────────────────────────────────────────
    {
        "id":            "car_sedan",
        "category":      "car",
        "label":         "Generic Sedan",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [4.5, 1.8, 1.45],
        "tags":          ["car", "vehicle", "sedan", "transport"],
        "color_hint":    CATEGORY_COLORS["car"],
    },
    {
        "id":            "car_suv",
        "category":      "car",
        "label":         "Generic SUV",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [4.7, 1.9, 1.7],
        "tags":          ["car", "vehicle", "suv", "transport"],
        "color_hint":    CATEGORY_COLORS["car"],
    },
    # ── FURNITURE ──────────────────────────────────────────────────────────
    {
        "id":            "furniture_chair",
        "category":      "furniture",
        "label":         "Generic Chair",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [0.55, 0.55, 0.85],
        "tags":          ["furniture", "chair", "seating", "interior"],
        "color_hint":    CATEGORY_COLORS["furniture"],
    },
    {
        "id":            "furniture_table_dining",
        "category":      "furniture",
        "label":         "Dining Table",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [1.8, 0.9, 0.75],
        "tags":          ["furniture", "table", "dining", "interior"],
        "color_hint":    CATEGORY_COLORS["furniture"],
    },
    {
        "id":            "furniture_sofa_2seat",
        "category":      "furniture",
        "label":         "2-Seat Sofa",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [1.7, 0.85, 0.85],
        "tags":          ["furniture", "sofa", "seating", "interior"],
        "color_hint":    CATEGORY_COLORS["furniture"],
    },
    {
        "id":            "furniture_bed_double",
        "category":      "furniture",
        "label":         "Double Bed",
        "default_scale": [1.0, 1.0, 1.0],
        "bbox":          [1.4, 2.0, 0.5],
        "tags":          ["furniture", "bed", "bedroom", "interior"],
        "color_hint":    CATEGORY_COLORS["furniture"],
    },
]

# Pre-build lookup index
_BY_ID: dict[str, dict] = {a["id"]: a for a in _CATALOGUE}
_BY_CATEGORY: dict[str, list[dict]] = {}
for _a in _CATALOGUE:
    _BY_CATEGORY.setdefault(_a["category"], []).append(_a)


def search_assets(
    query: str | None = None,
    category: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return assets matching *category* and/or free-text *query* in tags/label."""
    results = _CATALOGUE
    if category:
        cat = category.lower().strip()
        results = [a for a in results if a["category"] == cat]
    if query:
        q = query.lower().strip()
        results = [
            a for a in results
            if q in a["label"].lower()
            or q in a["id"].lower()
            or any(q in t for t in a["tags"])
        ]
    return results[:limit]


def get_asset(asset_id: str) -> dict[str, Any] | None:
    """Return a single asset by id, or None."""
    return _BY_ID.get(asset_id)


def all_categories() -> list[str]:
    return sorted(_BY_CATEGORY.keys())
