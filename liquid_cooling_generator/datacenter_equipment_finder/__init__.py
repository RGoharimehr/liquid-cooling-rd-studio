"""Data Center Equipment Finder.

The selection core - catalogue, matching, compatibility, duty selection and the
reference-design adapter - imports nothing outside the standard library, so it runs
anywhere a plain Python interpreter does, including a Pyodide worker in a browser
alongside a design engine.

The assistant (rapidfuzz) and PDF ingestion (pypdf) are loaded on first use, so
importing this package does not require them to be installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .catalog import EquipmentCatalog
from .catalog_tools import build_sqlite_database, download_catalogs
from .compatibility import check_compatibility
from .dataset_pipeline import build_catalog_from_vendor_sources
from .matching import find_closest_components
from .rd_studio import duties_from_valve_schedule
from .service import EquipmentService

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from .assistant import run_assistant_query
    from .pdf_catalog import (
        build_database_from_pdf,
        extract_catalog_rows_from_pdf,
        extract_pdf_text,
        write_catalog_csv,
    )

# name -> module that provides it, imported on first attribute access.
_LAZY = {
    "run_assistant_query": ".assistant",
    "build_database_from_pdf": ".pdf_catalog",
    "extract_catalog_rows_from_pdf": ".pdf_catalog",
    "extract_pdf_text": ".pdf_catalog",
    "write_catalog_csv": ".pdf_catalog",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    "EquipmentCatalog",
    "EquipmentService",
    "build_catalog_from_vendor_sources",
    "build_database_from_pdf",
    "build_sqlite_database",
    "check_compatibility",
    "download_catalogs",
    "duties_from_valve_schedule",
    "extract_catalog_rows_from_pdf",
    "extract_pdf_text",
    "find_closest_components",
    "run_assistant_query",
    "write_catalog_csv",
]
