"""
kerf_bim.materials — BIM material catalogue with IFC IfcMaterial round-trip (T-115).

Ties the :mod:`~kerf_bim.materials_catalogue` ``BIMMaterial`` objects to
the IFC material model (``IfcMaterial``, ``IfcMaterialLayer``,
``IfcMaterialLayerSet``) and bridges render-appearance data to the PBR
hero renderer.

IFC mapping
-----------
- Each :class:`~kerf_bim.materials_catalogue.BIMMaterial` → ``IfcMaterial``
  with a name and optional ``IfcMaterialProperties`` pset.
- A wall / slab / roof layer stack → ``IfcMaterialLayerSet`` containing
  one ``IfcMaterialLayer`` per :class:`~kerf_bim.walls.WallLayer`.
- Render appearance (PBR) is attached to the material via a custom
  ``Pset_KerfRenderAppearance`` property set (non-standard, vendor-specific).

Reference
---------
ISO 16739-1:2018 — ``IfcMaterial``, ``IfcMaterialLayer``,
``IfcMaterialLayerSet``, ``IfcMaterialProperties``.
Autodesk Revit 2024 — Material Editor / Appearance Asset.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from kerf_bim.materials_catalogue import (
    CATALOGUE,
    BIMMaterial,
    PBRAppearance,
    StructuralProps,
    ThermalProps,
    FireProps,
    find_material,
    list_by_category,
    MPa,
    GPa,
)

__all__ = [
    # Re-exports from catalogue
    "CATALOGUE",
    "BIMMaterial",
    "PBRAppearance",
    "StructuralProps",
    "ThermalProps",
    "FireProps",
    "find_material",
    "list_by_category",
    "MPa",
    "GPa",
    # IFC round-trip
    "material_to_ifc_dict",
    "layer_set_to_ifc_dict",
    "material_from_ifc_dict",
    # PBR appearance bridge
    "pbr_appearance_dict",
    "wall_material_layer_set",
    # Query helpers
    "get_material",
    "MaterialError",
]


class MaterialError(KeyError):
    """Raised when a material is not found in the catalogue."""


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_material(name: str) -> BIMMaterial:
    """Return a :class:`BIMMaterial` by name, raising :class:`MaterialError`
    if not found.

    Lookup is case-insensitive.
    """
    result = find_material(name)
    if not result["ok"]:
        raise MaterialError(
            f"Material '{name}' not in BIM catalogue. "
            f"Available: {sorted(CATALOGUE)[:10]} …"
        )
    return result["material"]


# ---------------------------------------------------------------------------
# IFC dict for IfcMaterial
# ---------------------------------------------------------------------------

def material_to_ifc_dict(material: BIMMaterial) -> dict:
    """Serialise a :class:`BIMMaterial` to an IFC-compatible dict.

    The returned dict represents the data needed to emit:
    - ``IfcMaterial`` (name)
    - ``IfcMaterialProperties`` (thermal + structural + fire psets)
    - ``Pset_KerfRenderAppearance`` (PBR vendor pset)

    Returns::

        {
          "ifc_entity":  "IfcMaterial",
          "name":        str,          # material name key
          "category":    str,
          "density_kg_m3": float,
          "source":      str,
          "structural": {
            "elastic_modulus_pa": float | None,
            "yield_strength_pa":  float | None,
            "tensile_strength_pa": float | None,
            "poisson_ratio":      float | None,
            "shear_modulus_pa":   float | None,
          } | None,
          "thermal": {
            "thermal_conductivity_w_mk": float,
            "specific_heat_j_kgk":      float,
            "thermal_expansion_1_k":    float,
            "emissivity":               float,
          } | None,
          "fire": {
            "rating_class":          str,
            "fire_resistance_hours": float,
          } | None,
          "render_appearance": {
            "base_color":  [r, g, b],   # [0-1] each
            "metallic":    float,
            "roughness":   float,
            "ior":         float,
            "opacity":     float,
            "normal_map":  str | None,
            "emissive":    [r, g, b] | None,
          },
        }
    """
    s = material.structural
    t = material.thermal
    f = material.fire
    r = material.render_appearance

    return {
        "ifc_entity":    "IfcMaterial",
        "name":          material.name,
        "category":      material.category,
        "density_kg_m3": material.density,
        "source":        material.source,
        "structural": {
            "elastic_modulus_pa":  s.elastic_modulus  if s else None,
            "yield_strength_pa":   s.yield_strength   if s else None,
            "tensile_strength_pa": s.tensile_strength if s else None,
            "poisson_ratio":       s.poisson_ratio    if s else None,
            "shear_modulus_pa":    s.shear_modulus    if s else None,
        } if s else None,
        "thermal": {
            "thermal_conductivity_w_mk": t.thermal_conductivity,
            "specific_heat_j_kgk":      t.specific_heat,
            "thermal_expansion_1_k":    t.thermal_expansion,
            "emissivity":               t.emissivity,
        } if t else None,
        "fire": {
            "rating_class":          f.rating_class,
            "fire_resistance_hours": f.fire_resistance_hours,
        } if f else None,
        "render_appearance": {
            "base_color":  list(r.base_color),
            "metallic":    r.metallic,
            "roughness":   r.roughness,
            "ior":         r.ior,
            "opacity":     r.opacity,
            "normal_map":  r.normal_map,
            "emissive":    list(r.emissive) if r.emissive else None,
        },
    }


def material_from_ifc_dict(d: dict) -> BIMMaterial:
    """Reconstruct a :class:`BIMMaterial` from a dict produced by
    :func:`material_to_ifc_dict`.

    Intended for round-trip testing and import from IFC property sets.

    Raises
    ------
    KeyError
        If required fields are missing from the dict.
    """
    r = d["render_appearance"]
    appearance = PBRAppearance(
        base_color=tuple(r["base_color"]),
        metallic=r["metallic"],
        roughness=r["roughness"],
        ior=r["ior"],
        opacity=r["opacity"],
        normal_map=r.get("normal_map"),
        emissive=tuple(r["emissive"]) if r.get("emissive") else None,
    )

    structural = None
    if d.get("structural") and d["structural"].get("elastic_modulus_pa") is not None:
        s = d["structural"]
        structural = StructuralProps(
            elastic_modulus=s["elastic_modulus_pa"],
            poisson_ratio=s["poisson_ratio"],
            yield_strength=s["yield_strength_pa"],
            tensile_strength=s["tensile_strength_pa"],
            shear_modulus=s["shear_modulus_pa"],
        )

    thermal = None
    if d.get("thermal"):
        t = d["thermal"]
        thermal = ThermalProps(
            thermal_conductivity=t["thermal_conductivity_w_mk"],
            specific_heat=t["specific_heat_j_kgk"],
            thermal_expansion=t["thermal_expansion_1_k"],
            emissivity=t["emissivity"],
        )

    fire = None
    if d.get("fire"):
        f = d["fire"]
        fire = FireProps(
            rating_class=f["rating_class"],
            fire_resistance_hours=f["fire_resistance_hours"],
        )

    return BIMMaterial(
        name=d["name"],
        category=d["category"],
        render_appearance=appearance,
        structural=structural,
        thermal=thermal,
        fire=fire,
        density=d["density_kg_m3"],
        source=d["source"],
    )


# ---------------------------------------------------------------------------
# IfcMaterialLayerSet
# ---------------------------------------------------------------------------

@dataclass
class MaterialLayer:
    """A single layer in a material layer set.

    Parameters
    ----------
    material_name:
        Key into :data:`~kerf_bim.materials_catalogue.CATALOGUE`.
    thickness_mm:
        Layer thickness in mm.
    is_ventilated:
        True for air-gap / ventilated cavity layers.
    """
    material_name: str
    thickness_mm: float
    is_ventilated: bool = False


def layer_set_to_ifc_dict(
    set_name: str,
    layers: List[MaterialLayer],
) -> dict:
    """Serialise a list of :class:`MaterialLayer` to an
    ``IfcMaterialLayerSet`` dict.

    Returns::

        {
          "ifc_entity": "IfcMaterialLayerSet",
          "name":       str,
          "total_thickness_mm": float,
          "layers": [
            {
              "material": <material_to_ifc_dict(...)>,
              "thickness_mm": float,
              "is_ventilated": bool,
            },
            ...
          ],
        }
    """
    layer_dicts: List[dict] = []
    total_t = 0.0
    for lay in layers:
        mat_result = find_material(lay.material_name)
        mat_dict: Optional[dict] = None
        if mat_result["ok"]:
            mat_dict = material_to_ifc_dict(mat_result["material"])
        else:
            # Unknown material — emit a minimal placeholder
            mat_dict = {
                "ifc_entity": "IfcMaterial",
                "name": lay.material_name,
                "category": "unknown",
            }
        layer_dicts.append({
            "material":      mat_dict,
            "thickness_mm":  lay.thickness_mm,
            "is_ventilated": lay.is_ventilated,
        })
        total_t += lay.thickness_mm

    return {
        "ifc_entity":         "IfcMaterialLayerSet",
        "name":               set_name,
        "total_thickness_mm": total_t,
        "layers":             layer_dicts,
    }


from typing import Optional  # noqa: E402


# ---------------------------------------------------------------------------
# PBR appearance bridge for the hero renderer
# ---------------------------------------------------------------------------

def pbr_appearance_dict(material_name: str) -> Optional[dict]:
    """Return the PBR appearance dict for the Kerf hero renderer.

    Parameters
    ----------
    material_name:
        Material key (case-insensitive lookup).

    Returns
    -------
    dict with PBR properties, or ``None`` if the material is not in the
    catalogue.

    The dict shape matches the ``heroShot.js`` material spec::

        {
          "color":     [r, g, b],     # linear [0-1]
          "metallic":  float,
          "roughness": float,
          "ior":       float,
          "opacity":   float,
          "normal_map": str | None,
        }
    """
    result = find_material(material_name)
    if not result["ok"]:
        return None
    r = result["material"].render_appearance
    return {
        "color":      list(r.base_color),
        "metallic":   r.metallic,
        "roughness":  r.roughness,
        "ior":        r.ior,
        "opacity":    r.opacity,
        "normal_map": r.normal_map,
    }


# ---------------------------------------------------------------------------
# Convenience: build an IfcMaterialLayerSet from a compound-wall
# ---------------------------------------------------------------------------

def wall_material_layer_set(wall_type: Any) -> dict:
    """Build an ``IfcMaterialLayerSet`` dict from a
    :class:`~kerf_bim.walls.CompoundWall` type.

    Parameters
    ----------
    wall_type:
        A :class:`kerf_bim.walls.CompoundWall` instance.

    Returns
    -------
    dict — as produced by :func:`layer_set_to_ifc_dict`.
    """
    layers = [
        MaterialLayer(
            material_name=lay.material,
            thickness_mm=lay.thickness,
            is_ventilated=(lay.function == "air_gap"),
        )
        for lay in wall_type.layers
    ]
    return layer_set_to_ifc_dict(wall_type.name, layers)
