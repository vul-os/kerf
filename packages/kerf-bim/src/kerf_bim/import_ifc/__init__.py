"""
kerf_bim.import_ifc — IFC → .bim importer (Tier 1).

Public surface:
    parse_ifc_file(path: Path) -> IFCImportResult
    IFCImportResult, IFCImportError, IFCOpenShellNotInstalled
"""
from kerf_bim.import_ifc.parser import parse_ifc_file
from kerf_bim.import_ifc.types import IFCImportResult, IFCImportError, IFCOpenShellNotInstalled

__all__ = [
    "parse_ifc_file",
    "IFCImportResult",
    "IFCImportError",
    "IFCOpenShellNotInstalled",
]
