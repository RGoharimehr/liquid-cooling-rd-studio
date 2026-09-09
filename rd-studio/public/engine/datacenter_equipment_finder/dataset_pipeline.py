from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .catalog import FIELD_NAMES, KNOWN_CATEGORIES


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [name for name in FIELD_NAMES if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} missing required columns: {missing}")
        return [row for row in reader]


def validate_rows(rows: Iterable[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    seen_part_numbers: set[str] = set()

    for idx, row in enumerate(rows, start=1):
        part_number = (row.get("part_number") or "").strip()
        if not part_number:
            errors.append(f"row {idx}: missing part_number")
        else:
            key = part_number.lower()
            if key in seen_part_numbers:
                errors.append(f"row {idx}: duplicate part_number {part_number}")
            seen_part_numbers.add(key)

        for numeric in (
            "nominal_size_mm",
            "nominal_size_inch",
            "flow_coefficient_value",
            "capacity_kw",
            "capacity_tons",
            "pressure_rating_bar",
            "max_temperature_c",
            "estimated_price_usd",
            "install_connection_time_min",
        ):
            value = (row.get(numeric) or "").strip()
            if value:
                try:
                    float(value)
                except ValueError:
                    errors.append(f"row {idx}: invalid float for {numeric}={value}")

        category = (row.get("category") or "").strip().lower()
        if not category:
            errors.append(f"row {idx}: missing category")
        elif category not in KNOWN_CATEGORIES:
            errors.append(
                f"row {idx}: unknown category {category!r} "
                f"(expected one of {', '.join(sorted(KNOWN_CATEGORIES))})"
            )

        # Every row has to say where it came from. Without this a row can enter the
        # catalog with no traceable source at all.
        if not (row.get("source_catalog") or "").strip():
            errors.append(f"row {idx}: missing source_catalog")

        # The finder selects on capacity, size or flow coefficient. A row carrying
        # none of them can never be returned by a search, so it is not a usable entry.
        if not any(
            (row.get(field) or "").strip()
            for field in (
                "capacity_kw",
                "capacity_tons",
                "nominal_size_mm",
                "nominal_size_inch",
                "flow_coefficient_value",
            )
        ):
            errors.append(
                f"row {idx}: no capacity, size or flow coefficient - nothing to match on"
            )

        data_url = (row.get("datasheet_url") or "").strip().lower()
        if data_url and not data_url.startswith(("http://", "https://")):
            errors.append(f"row {idx}: invalid datasheet_url {data_url}")

    return errors


def build_catalog_from_vendor_sources(source_dir: str | Path, output_file: str | Path) -> list[str]:
    source_path = Path(source_dir)
    output_path = Path(output_file)
    source_files = sorted(source_path.glob("*.csv"))
    if not source_files:
        raise ValueError(f"No vendor csv files found in {source_path}")

    rows: list[dict[str, str]] = []
    for file in source_files:
        rows.extend(_read_csv(file))

    errors = validate_rows(rows)
    if errors:
        return errors

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
        writer.writeheader()
        writer.writerows(rows)
    return []
