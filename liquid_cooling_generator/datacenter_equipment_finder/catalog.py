from __future__ import annotations

import csv
from importlib.resources import files
from pathlib import Path
from typing import Iterable, Optional

from .models import EquipmentComponent


# The catalog's categories are a controlled vocabulary. Adding one is a deliberate
# change: matching, the schema hints and the explanations all need to know about it.
KNOWN_CATEGORIES = {
    "valve",
    "strainer",
    "filter_dryer",
    "cdu",
    "chiller",
    "quick_disconnect",
}

# Plausible names a model may produce for an existing category. Mapping these is safe;
# anything outside the vocabulary is rejected rather than guessed at.
CATEGORY_ALIASES = {
    "coolant_distribution_unit": "cdu",
    "cooling_distribution_unit": "cdu",
    "coolant_distribution_units": "cdu",
    "quick_disconnect_coupling": "quick_disconnect",
    "quick_connect": "quick_disconnect",
    "coupling": "quick_disconnect",
    "filter_drier": "filter_dryer",
    "filter_dryers": "filter_dryer",
    "valves": "valve",
    "strainers": "strainer",
    "chillers": "chiller",
}


FIELD_NAMES = [
    "brand",
    "category",
    "component_subtype",
    "series_name",
    "component_name",
    "nominal_size_mm",
    "nominal_size_inch",
    "flow_coefficient_type",
    "flow_coefficient_value",
    "capacity_kw",
    "capacity_tons",
    "connection_type",
    "connection_standard",
    "material",
    "pressure_rating_bar",
    "max_temperature_c",
    "coolant_compatibility",
    "estimated_price_usd",
    "install_connection_time_min",
    "part_number",
    "source_catalog",
    "source_page",
    "datasheet_url",
    "baseline_references",
    "verification_status",
]


def _to_float(value: str) -> Optional[float]:
    stripped = (value or "").strip()
    if not stripped:
        return None
    return float(stripped)


def _to_str(value: str) -> Optional[str]:
    stripped = (value or "").strip()
    return stripped or None


class EquipmentCatalog:
    def __init__(self, components: Iterable[EquipmentComponent]):
        self.components = list(components)

    @classmethod
    def default_csv_path(cls) -> Path:
        return Path(str(files("datacenter_equipment_finder.data").joinpath("equipment_catalog.csv")))

    @classmethod
    def from_csv(cls, path: str | Path | None = None) -> "EquipmentCatalog":
        csv_path = Path(path) if path else cls.default_csv_path()
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            missing = [name for name in FIELD_NAMES if name not in fieldnames]
            if missing:
                raise ValueError(f"Missing required CSV columns: {missing}")

            components = []
            for row in reader:
                components.append(
                    EquipmentComponent(
                        brand=row["brand"].strip(),
                        category=row["category"].strip(),
                        component_subtype=_to_str(row["component_subtype"]),
                        series_name=row["series_name"].strip(),
                        component_name=row["component_name"].strip(),
                        nominal_size_mm=_to_float(row["nominal_size_mm"]),
                        nominal_size_inch=_to_float(row["nominal_size_inch"]),
                        flow_coefficient_type=_to_str(row["flow_coefficient_type"]),
                        flow_coefficient_value=_to_float(row["flow_coefficient_value"]),
                        capacity_kw=_to_float(row["capacity_kw"]),
                        capacity_tons=_to_float(row["capacity_tons"]),
                        connection_type=_to_str(row["connection_type"]),
                        connection_standard=_to_str(row["connection_standard"]),
                        material=_to_str(row["material"]),
                        pressure_rating_bar=_to_float(row["pressure_rating_bar"]),
                        max_temperature_c=_to_float(row["max_temperature_c"]),
                        coolant_compatibility=_to_str(row["coolant_compatibility"]),
                        estimated_price_usd=_to_float(row["estimated_price_usd"]),
                        install_connection_time_min=_to_float(row["install_connection_time_min"]),
                        part_number=row["part_number"].strip(),
                        source_catalog=_to_str(row["source_catalog"]),
                        source_page=_to_str(row["source_page"]),
                        datasheet_url=_to_str(row["datasheet_url"]),
                        baseline_references=_to_str(row["baseline_references"]),
                        verification_status=_to_str(row.get("verification_status", "")) or "unverified",
                    )
                )
        return cls(components)
