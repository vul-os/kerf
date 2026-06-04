# Parcels & Subdivision Layout

> LandXML-based parcel import/export, lot-area computation, and subdivision layout geometry for civil land development.

**Module**: `packages/kerf-civil/src/kerf_civil/landxml.py`, `tools_hydraulics.py`
**Shipped**: Wave 9A4
**LLM tools**: `civil_landxml_import`, `civil_landxml_export`

---

## What it is

Subdivision design involves dividing a parent parcel into lots that satisfy minimum frontage, lot area, and access requirements. LandXML 1.2 is the interchange format used between survey instruments, civil design software (Civil 3D, 12d), and local authority GIS. This module parses and emits LandXML for alignments, TIN surfaces, and parcel boundary geometry.

## How to use it

### From chat

> "Import this LandXML file and give me the area of each parcel in the subdivision. Which lots are smaller than 300 m²?"

### From Python

```python
from kerf_civil.landxml import parse_landxml, parcels_to_dicts

with open("subdivision.xml") as f:
    xml_str = f.read()

result = parse_landxml(xml_str)
for parcel in result["parcels"]:
    print(parcel["name"], ":", parcel["area_m2"], "m²")

small = [p for p in result["parcels"] if p["area_m2"] < 300]
print("Undersized lots:", [p["name"] for p in small])
```

### From an LLM tool spec

```json
{"xml_str": "<LandXML ...>...</LandXML>",
 "action": "import"}
```

## How it works

`parse_landxml` uses Python's built-in `xml.etree.ElementTree` to walk the LandXML 1.2 schema. `<Alignments>` elements are parsed as sequences of `CoordGeom` elements (Line, Curve). `<Surfaces>` are read from `<Pnts>` + `<Faces>` sub-elements and returned as node/triangle arrays compatible with `kerf_civil.tin.TIN`. `<Parcels>` are parsed from boundary line sequences and their areas are computed via the Shoelace formula. Export serialises the same structures back to a valid LandXML 1.2 string.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `parse_landxml(xml_str)` | `dict` | Parse LandXML → alignments, surfaces, parcels |
| `export_landxml(alignments, surfaces, parcels)` | `str` | Serialise to LandXML 1.2 XML |
| `parcel_area_m2(boundary_points)` | `float` | Shoelace polygon area |

`parse_landxml` returns: `{"ok": bool, "alignments": [...], "surfaces": [...], "parcels": [...]}`.

## Example

```python
from kerf_civil.landxml import parse_landxml

xml = """<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2">
  <Parcels><Parcel name="Lot1"><CoordGeom>
    <Line><Start>0 0</Start><End>20 0</End></Line>
    <Line><Start>20 0</Start><End>20 15</End></Line>
    <Line><Start>20 15</Start><End>0 15</End></Line>
    <Line><Start>0 15</Start><End>0 0</End></Line>
  </CoordGeom></Parcel></Parcels></LandXML>"""
r = parse_landxml(xml)
print(r["parcels"][0]["area_m2"])  # 300.0
```

## Honest caveats

The parser covers LandXML 1.2 linear/circular geometry only — cubic spiral and NURBS curve elements are silently skipped. Complex parcel topologies with internal boundaries or holes are not supported. The LandXML namespace URI must be exactly `http://www.landxml.org/schema/LandXML-1.2`; v1.1 files need namespace adjustment before import.

## References

- LandXML.org (2008). *LandXML 1.2 Schema Reference*. landxml.org.
- Autodesk (2022). *Civil 3D LandXML Export Guide*.
