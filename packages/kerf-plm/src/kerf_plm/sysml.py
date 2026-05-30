"""
kerf_plm.sysml — MBSE / SysML 1.x digital-thread support.

Provides:
  - Requirement, DesignElement, TestCase  dataclasses
  - TraceabilityMatrix                    build + query coverage
  - export_xmi(matrix, path, sysml_version)  SysML 1.6 / 1.7 XMI export
  - import_xmi(path) -> TraceabilityMatrix   round-trip parser

SysML XMI namespaces (OMG spec):
  1.6  — http://www.omg.org/spec/SysML/20181001/
  1.7  — http://www.omg.org/spec/SysML/20191001/

Caveat: implements the subset of the OMG SysML 1.x XMI schema needed for
requirements-to-design-to-test traceability.  Not OMG-certified; SysML 2.0
is explicitly out of scope.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Namespace constants
# ---------------------------------------------------------------------------

_NS_SYSML = {
    "1.6": "http://www.omg.org/spec/SysML/20181001/",
    "1.7": "http://www.omg.org/spec/SysML/20191001/",
}
_NS_REQUIREMENTS = "http://www.omg.org/spec/SysML/20181001/Requirements"
_NS_UML = "http://www.omg.org/spec/UML/20161101"
_NS_XMI = "http://www.omg.org/spec/XMI/20131001"

_SUPPORTED_VERSIONS = frozenset(_NS_SYSML.keys())


# ---------------------------------------------------------------------------
# Data-model dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Requirement:
    """An MBSE requirement node.

    Attributes
    ----------
    id          : unique string id (e.g. "REQ-001")
    text        : requirement text
    parent_id   : id of parent requirement (for derived requirements); None = root
    satisfied_by: design element ids that satisfy this requirement
    verified_by : test case ids that verify this requirement
    """
    id: str
    text: str
    parent_id: Optional[str] = None
    satisfied_by: list[str] = field(default_factory=list)
    verified_by: list[str] = field(default_factory=list)


@dataclass
class DesignElement:
    """A SysML Block / Part / Connector design element.

    Attributes
    ----------
    id          : unique string id
    kind        : one of 'block', 'part', 'connector'
    name        : human-readable name
    properties  : arbitrary key-value metadata dict
    allocated_to: test case ids allocated to this element
    """
    id: str
    kind: str          # 'block' | 'part' | 'connector'
    name: str
    properties: dict[str, str] = field(default_factory=dict)
    allocated_to: list[str] = field(default_factory=list)

    def __post_init__(self):
        valid_kinds = {"block", "part", "connector"}
        if self.kind not in valid_kinds:
            raise ValueError(
                f"DesignElement.kind must be one of {valid_kinds}; got {self.kind!r}"
            )


@dataclass
class TestCase:
    """A test case that verifies one or more requirements.

    Attributes
    ----------
    id       : unique string id
    name     : human-readable name
    verifies : list of requirement ids this test case verifies
    """
    id: str
    name: str
    verifies: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# TraceabilityMatrix
# ---------------------------------------------------------------------------

class TraceabilityMatrix:
    """Requirements-to-design-to-test traceability graph.

    Build from lists of Requirement, DesignElement, TestCase objects.
    Provides forward/reverse lookup and coverage reporting.
    """

    def __init__(
        self,
        requirements: list[Requirement],
        design_elements: list[DesignElement],
        test_cases: list[TestCase],
    ):
        self.requirements: dict[str, Requirement] = {r.id: r for r in requirements}
        self.design_elements: dict[str, DesignElement] = {d.id: d for d in design_elements}
        self.test_cases: dict[str, TestCase] = {t.id: t for t in test_cases}

    # ------------------------------------------------------------------
    # Lookup queries
    # ------------------------------------------------------------------

    def requirements_for(self, design_id: str) -> list[str]:
        """Return ids of requirements satisfied by a given design element."""
        return [
            r.id
            for r in self.requirements.values()
            if design_id in r.satisfied_by
        ]

    def tests_for(self, requirement_id: str) -> list[str]:
        """Return ids of tests that verify a given requirement.

        Checks both Requirement.verified_by and TestCase.verifies so the
        matrix is consistent regardless of which side was populated.
        """
        req = self.requirements.get(requirement_id)
        req_vb = set(req.verified_by) if req else set()

        tc_vb = {
            tc.id
            for tc in self.test_cases.values()
            if requirement_id in tc.verifies
        }

        return sorted(req_vb | tc_vb)

    # ------------------------------------------------------------------
    # Coverage report
    # ------------------------------------------------------------------

    def coverage_report(self) -> dict:
        """Compute traceability coverage.

        Returns
        -------
        {
          "covered"   : int,   # requirements satisfied by >=1 design AND verified by >=1 test
          "uncovered" : int,   # requirements with no design satisfaction or no test verification
          "total"     : int,
          "coverage_pct": float,  # covered/total * 100
          "orphaned_requirements": list[str],  # satisfied by no design
          "unverified_requirements": list[str], # verified by no test
          "orphaned_tests": list[str],          # verify no requirement
        }
        """
        orphaned_reqs: list[str] = []       # no design satisfies them
        unverified_reqs: list[str] = []     # no test verifies them
        covered_ids: set[str] = set()

        for req_id, req in self.requirements.items():
            # Check design satisfaction
            has_design = bool(req.satisfied_by) or any(
                req_id in d.allocated_to for d in self.design_elements.values()
            )
            # Check test verification
            has_test = bool(self.tests_for(req_id))

            if not has_design:
                orphaned_reqs.append(req_id)
            if not has_test:
                unverified_reqs.append(req_id)
            if has_design and has_test:
                covered_ids.add(req_id)

        # Orphaned tests: test cases that reference no valid requirement
        orphaned_tests: list[str] = []
        for tc_id, tc in self.test_cases.items():
            if not tc.verifies:
                orphaned_tests.append(tc_id)
                continue
            # All referenced requirements must exist
            if not any(rid in self.requirements for rid in tc.verifies):
                orphaned_tests.append(tc_id)

        total = len(self.requirements)
        covered = len(covered_ids)
        coverage_pct = (covered / total * 100.0) if total > 0 else 0.0

        return {
            "covered": covered,
            "uncovered": total - covered,
            "total": total,
            "coverage_pct": round(coverage_pct, 2),
            "orphaned_requirements": sorted(orphaned_reqs),
            "unverified_requirements": sorted(unverified_reqs),
            "orphaned_tests": sorted(orphaned_tests),
        }


# ---------------------------------------------------------------------------
# XMI export
# ---------------------------------------------------------------------------

def export_xmi(
    matrix: TraceabilityMatrix,
    path: str | Path,
    sysml_version: str = "1.7",
) -> None:
    """Export a TraceabilityMatrix to a SysML 1.x XMI file.

    Parameters
    ----------
    matrix        : TraceabilityMatrix to export
    path          : output file path
    sysml_version : '1.6' or '1.7' (default '1.7')

    XML namespaces used
    -------------------
    xmi   : http://www.omg.org/spec/XMI/20131001
    uml   : http://www.omg.org/spec/UML/20161101
    sysml : http://www.omg.org/spec/SysML/20181001/  (1.6)
            http://www.omg.org/spec/SysML/20191001/  (1.7)
    requirements : http://www.omg.org/spec/SysML/20181001/Requirements

    Structure
    ---------
    <xmi:XMI>
      <uml:Model>
        <packagedElement type="uml:Package" name="Requirements">
          <packagedElement type="requirements::Requirement" ...>
            <text>...</text>
          </packagedElement>
          ...
        </packagedElement>
        <packagedElement type="uml:Package" name="Design">
          <packagedElement type="sysml::Block" .../>
          ...
        </packagedElement>
        <packagedElement type="uml:Package" name="Tests">
          <packagedElement type="uml:TestCase" .../>
          ...
        </packagedElement>
        <!-- Satisfy links: requirement → design -->
        <packagedElement type="sysml::Satisfy" .../>
        <!-- Verify links: test → requirement -->
        <packagedElement type="sysml::Verify" .../>
      </uml:Model>
    </xmi:XMI>
    """
    if sysml_version not in _SUPPORTED_VERSIONS:
        raise ValueError(
            f"Unsupported SysML version {sysml_version!r}. "
            f"Supported: {sorted(_SUPPORTED_VERSIONS)}"
        )

    sysml_ns = _NS_SYSML[sysml_version]

    # Register namespaces to get clean prefixes in output
    ET.register_namespace("xmi", _NS_XMI)
    ET.register_namespace("uml", _NS_UML)
    ET.register_namespace("sysml", sysml_ns)
    ET.register_namespace("requirements", _NS_REQUIREMENTS)

    def _xmi(tag): return f"{{{_NS_XMI}}}{tag}"
    def _uml(tag): return f"{{{_NS_UML}}}{tag}"
    def _sysml(tag): return f"{{{sysml_ns}}}{tag}"
    def _req(tag): return f"{{{_NS_REQUIREMENTS}}}{tag}"

    # Root — include explicit xmlns:sysml declaration so the version URI is
    # always present in the output even when no sysml-namespaced tags are used.
    root = ET.Element(_xmi("XMI"), {
        _xmi("version"): "2.5.1",
        "sysml_version": sysml_version,
        # Force the sysml namespace declaration into the root element.
        # ET.register_namespace only emits xmlns:sysml when a sysml-prefixed
        # tag exists; storing it as an attribute ensures it's always present.
        f"xmlns:sysml": sysml_ns,
    })

    # Model
    model = ET.SubElement(root, _uml("Model"), {
        _xmi("id"): "_model",
        "name": "SysMLModel",
    })

    # --- Requirements package ---
    req_pkg = ET.SubElement(model, "packagedElement", {
        _xmi("type"): "uml:Package",
        _xmi("id"): "_pkg_requirements",
        "name": "Requirements",
    })
    for req in matrix.requirements.values():
        attrs = {
            _xmi("type"): "requirements::Requirement",
            _xmi("id"): req.id,
            "name": req.id,
        }
        if req.parent_id:
            attrs["parent"] = req.parent_id
        el = ET.SubElement(req_pkg, "packagedElement", attrs)
        text_el = ET.SubElement(el, "text")
        text_el.text = req.text

    # --- Design package ---
    design_pkg = ET.SubElement(model, "packagedElement", {
        _xmi("type"): "uml:Package",
        _xmi("id"): "_pkg_design",
        "name": "Design",
    })
    for de in matrix.design_elements.values():
        sysml_type = f"sysml::{de.kind.capitalize()}"
        el = ET.SubElement(design_pkg, "packagedElement", {
            _xmi("type"): sysml_type,
            _xmi("id"): de.id,
            "name": de.name,
        })
        for k, v in de.properties.items():
            prop = ET.SubElement(el, "property", {"name": k})
            prop.text = str(v)

    # --- Tests package ---
    tests_pkg = ET.SubElement(model, "packagedElement", {
        _xmi("type"): "uml:Package",
        _xmi("id"): "_pkg_tests",
        "name": "Tests",
    })
    for tc in matrix.test_cases.values():
        ET.SubElement(tests_pkg, "packagedElement", {
            _xmi("type"): "uml:TestCase",
            _xmi("id"): tc.id,
            "name": tc.name,
        })

    # --- Satisfy links (requirement ← design) ---
    satisfy_id = 0
    for req in matrix.requirements.values():
        for de_id in req.satisfied_by:
            satisfy_id += 1
            ET.SubElement(model, "packagedElement", {
                _xmi("type"): "sysml::Satisfy",
                _xmi("id"): f"_satisfy_{satisfy_id}",
                "supplier": req.id,
                "client": de_id,
            })

    # --- Verify links (test → requirement) ---
    verify_id = 0
    for tc in matrix.test_cases.values():
        for req_id in tc.verifies:
            verify_id += 1
            ET.SubElement(model, "packagedElement", {
                _xmi("type"): "sysml::Verify",
                _xmi("id"): f"_verify_{verify_id}",
                "supplier": req_id,
                "client": tc.id,
            })

    # Also emit Verify links defined on Requirement.verified_by (deduplicate)
    existing_verify_pairs = {
        (tc.id, req_id)
        for tc in matrix.test_cases.values()
        for req_id in tc.verifies
    }
    for req in matrix.requirements.values():
        for tc_id in req.verified_by:
            if (tc_id, req.id) not in existing_verify_pairs:
                verify_id += 1
                ET.SubElement(model, "packagedElement", {
                    _xmi("type"): "sysml::Verify",
                    _xmi("id"): f"_verify_{verify_id}",
                    "supplier": req.id,
                    "client": tc_id,
                })

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(path), encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# XMI import
# ---------------------------------------------------------------------------

def import_xmi(path: str | Path) -> TraceabilityMatrix:
    """Import a SysML 1.x XMI file and return a TraceabilityMatrix.

    Auto-detects SysML version from namespace URIs in the document.
    Raises ValueError for unsupported / unrecognised SysML versions.

    Supports the subset produced by export_xmi() and compatible tools.
    """
    tree = ET.parse(str(path))
    root = tree.getroot()

    # --- Detect SysML version from namespace ---
    detected_version: str | None = None
    raw_xml = root.get("{http://www.omg.org/spec/XMI/20131001}version")  # sanity

    # Walk all namespace declarations embedded in tags
    namespaces_found: set[str] = set()
    for elem in tree.iter():
        tag = elem.tag
        if tag.startswith("{"):
            ns = tag[1: tag.index("}")]
            namespaces_found.add(ns)
        for attr_key in elem.attrib:
            if attr_key.startswith("{"):
                ns = attr_key[1: attr_key.index("}")]
                namespaces_found.add(ns)
            # Also scan attribute *values* for type annotations like "sysml::Satisfy"
            # (they don't carry namespace URIs, handled below via sysml_version attr)

    # Check explicit sysml_version attribute on root (written by our exporter)
    explicit_version = root.get("sysml_version")
    if explicit_version:
        if explicit_version not in _SUPPORTED_VERSIONS:
            raise ValueError(
                f"Unsupported SysML version in XMI: {explicit_version!r}. "
                f"Supported: {sorted(_SUPPORTED_VERSIONS)}"
            )
        detected_version = explicit_version
    else:
        for ver, ns_uri in _NS_SYSML.items():
            if ns_uri in namespaces_found or ns_uri.rstrip("/") in namespaces_found:
                detected_version = ver
                break

    if detected_version is None:
        raise ValueError(
            "Cannot determine SysML version from XMI file. "
            "Expected namespace URI from: " + str(sorted(_NS_SYSML.values()))
        )

    sysml_ns = _NS_SYSML[detected_version]

    def _xmi(tag): return f"{{{_NS_XMI}}}{tag}"
    def _uml(tag): return f"{{{_NS_UML}}}{tag}"

    xmi_type_key = _xmi("type")
    xmi_id_key = _xmi("id")

    # --- Collect all packagedElement nodes (depth-first) ---
    requirements: dict[str, Requirement] = {}
    design_elements: dict[str, DesignElement] = {}
    test_cases: dict[str, TestCase] = {}
    satisfy_links: list[tuple[str, str]] = []   # (supplier=req_id, client=de_id)
    verify_links: list[tuple[str, str]] = []    # (supplier=req_id, client=tc_id)

    def _parse_elements(node):
        for elem in node:
            local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            elem_type = elem.get(xmi_type_key, "")
            elem_id = elem.get(xmi_id_key, "")

            # Requirements
            if "Requirement" in elem_type or elem_type == "requirements::Requirement":
                text_node = elem.find("text")
                text = text_node.text or "" if text_node is not None else ""
                parent_id = elem.get("parent") or None
                req = Requirement(id=elem_id, text=text, parent_id=parent_id)
                if elem_id:
                    requirements[elem_id] = req

            # Design elements (Block / Part / Connector)
            elif any(k in elem_type for k in ("::Block", "::Part", "::Connector")):
                kind_raw = elem_type.split("::")[-1].lower()
                if kind_raw not in {"block", "part", "connector"}:
                    kind_raw = "block"
                name = elem.get("name", elem_id)
                props: dict[str, str] = {}
                for prop_el in elem.findall("property"):
                    k = prop_el.get("name", "")
                    v = prop_el.text or ""
                    if k:
                        props[k] = v
                de = DesignElement(id=elem_id, kind=kind_raw, name=name, properties=props)
                if elem_id:
                    design_elements[elem_id] = de

            # Test cases
            elif "TestCase" in elem_type:
                name = elem.get("name", elem_id)
                tc = TestCase(id=elem_id, name=name)
                if elem_id:
                    test_cases[elem_id] = tc

            # Satisfy links
            elif "Satisfy" in elem_type:
                supplier = elem.get("supplier", "")
                client = elem.get("client", "")
                if supplier and client:
                    satisfy_links.append((supplier, client))

            # Verify links
            elif "Verify" in elem_type:
                supplier = elem.get("supplier", "")
                client = elem.get("client", "")
                if supplier and client:
                    verify_links.append((supplier, client))

            # Recurse into packages
            elif "Package" in elem_type or local_tag in ("packagedElement", "Model"):
                _parse_elements(elem)

    # Model is direct child of root
    model = root.find(_uml("Model"))
    if model is None:
        # Fallback: search by local tag name
        for child in root:
            if child.tag.endswith("}Model") or child.tag == "Model":
                model = child
                break

    if model is not None:
        _parse_elements(model)

    # --- Apply satisfy links → Requirement.satisfied_by ---
    for req_id, de_id in satisfy_links:
        if req_id in requirements and de_id not in requirements[req_id].satisfied_by:
            requirements[req_id].satisfied_by.append(de_id)

    # --- Apply verify links → TestCase.verifies ---
    for req_id, tc_id in verify_links:
        if tc_id in test_cases and req_id not in test_cases[tc_id].verifies:
            test_cases[tc_id].verifies.append(req_id)

    return TraceabilityMatrix(
        requirements=list(requirements.values()),
        design_elements=list(design_elements.values()),
        test_cases=list(test_cases.values()),
    )
