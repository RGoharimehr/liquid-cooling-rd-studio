from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .catalog import EquipmentCatalog, FIELD_NAMES
from .compatibility import (
    _material_families,
    acceptable_material_families,
    check_compatibility,
)
from .explanations import explain_category, explain_property
from .matching import find_closest_components


class EquipmentService:
    def __init__(self, catalog: EquipmentCatalog):
        self.catalog = catalog

    @classmethod
    def default(cls) -> "EquipmentService":
        return cls(EquipmentCatalog.from_csv())

    def schema(self) -> dict[str, Any]:
        categories = sorted({c.category for c in self.catalog.components})
        brands = sorted({c.brand for c in self.catalog.components})
        subtypes_by_category = {
            category: sorted(
                {
                    c.component_subtype
                    for c in self.catalog.components
                    if c.category == category and c.component_subtype
                }
            )
            for category in categories
        }
        return {
            "fields": FIELD_NAMES,
            "categories": categories,
            "brands": brands,
            "subtypes_by_category": subtypes_by_category,
            "input_hints": {
                "valve": ["size_mm", "connection_size_mm_or_inch", "component_subtype", "cv_or_kv"],
                "strainer": ["size_mm", "connection_size_mm_or_inch", "kv_or_cv"],
                "quick_disconnect": ["size_mm", "connection_size_mm_or_inch", "component_subtype", "cv_or_kv"],
                "filter_dryer": ["size_mm", "connection_size_mm_or_inch", "capacity_kw_or_tons"],
                "cdu": ["size_mm", "connection_size_mm_or_inch", "component_subtype", "capacity_kw_or_tons"],
                "chiller": ["size_mm", "connection_size_mm_or_inch", "component_subtype", "capacity_kw_or_tons"],
            },
            "duty_limits": {
                "required_pressure_bar": "excludes parts whose published pressure rating is below this",
                "required_temperature_c": "excludes parts whose published maximum temperature is below this",
            },
            "assistant_modes": ["local", "remote", "hybrid"],
        }

    def list_components(
        self,
        *,
        category: str | None = None,
        component_subtype: str | None = None,
        brand: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self.catalog.components
        if category:
            rows = [c for c in rows if c.category.lower() == category.lower()]
        if component_subtype:
            rows = [c for c in rows if (c.component_subtype or "").lower() == component_subtype.lower()]
        if brand:
            rows = [c for c in rows if c.brand.lower() == brand.lower()]
        sliced = rows[max(0, offset) : max(0, offset) + max(1, limit)]
        return [asdict(c) for c in sliced]

    def get_component(self, part_number: str) -> dict[str, Any] | None:
        for c in self.catalog.components:
            if c.part_number.lower() == part_number.lower():
                return asdict(c)
        return None

    def find_components(
        self,
        *,
        category: str | None = None,
        component_subtype: str | None = None,
        brand: str | None = None,
        size_mm: float | None = None,
        cv: float | None = None,
        kv: float | None = None,
        capacity_kw: float | None = None,
        capacity_tons: float | None = None,
        connection_size_mm: float | None = None,
        connection_size_inch: float | None = None,
        required_pressure_bar: float | None = None,
        required_temperature_c: float | None = None,
        required_cv: float | None = None,
        required_kv: float | None = None,
        required_capacity_kw: float | None = None,
        minimum_size_mm: float | None = None,
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        matches = find_closest_components(
            self.catalog.components,
            category=category,
            component_subtype=component_subtype,
            brand=brand,
            target_size_mm=size_mm,
            target_cv=cv,
            target_kv=kv,
            target_capacity_kw=capacity_kw,
            target_capacity_tons=capacity_tons,
            target_connection_size_mm=connection_size_mm,
            target_connection_size_inch=connection_size_inch,
            required_pressure_bar=required_pressure_bar,
            required_temperature_c=required_temperature_c,
            required_cv=required_cv,
            required_kv=required_kv,
            required_capacity_kw=required_capacity_kw,
            minimum_size_mm=minimum_size_mm,
            top_n=top_n,
        )
        return [
            {"score": m.score, "component": asdict(m.component), "warnings": list(m.warnings)}
            for m in matches
        ]

    def select_for_duty(self, items: list[dict[str, Any]], *, top_n: int = 3) -> dict[str, Any]:
        """Shortlist catalogue parts against a design's per-component duties.

        Intended for a design tool that has already sized the network: it supplies a
        required Kv or Cv (US) at its allocated pressure drop, a required capacity, a
        minimum bore and the duty pressure and temperature, and gets back candidates
        that can actually meet them.

        A shortlist is a capacity check only. Trim characteristic, valve authority,
        cavitation limits, materials and vendor review remain outside this tool, as
        does any statement about a balanced or commissioned network.
        """
        results: list[dict[str, Any]] = []
        for item in items:
            # A schedule row with no assigned duty is not a selection problem. Saying
            # so is the answer; shortlisting on nominal bore alone would look like an
            # engineering result and rest on nothing.
            if item.get("duty_unassigned") or item.get("unmappable"):
                results.append(
                    {
                        "tag": item.get("tag"),
                        "loop": item.get("loop"),
                        "quantity": item.get("quantity"),
                        "duty": {k: v for k, v in item.items() if v is not None},
                        "candidates": [],
                        "unmet": [item.get("unmappable") or item["duty_unassigned"]],
                    }
                )
                continue

            matches = self.find_components(
                category=item.get("category"),
                component_subtype=item.get("component_subtype"),
                brand=item.get("brand"),
                required_cv=item.get("required_cv"),
                required_kv=item.get("required_kv"),
                required_capacity_kw=item.get("required_capacity_kw"),
                minimum_size_mm=item.get("minimum_size_mm"),
                required_pressure_bar=item.get("required_pressure_bar"),
                required_temperature_c=item.get("required_temperature_c"),
                connection_size_mm=item.get("connection_size_mm"),
                connection_size_inch=item.get("connection_size_inch"),
                top_n=top_n,
            )
            # Wetted material is a requirement, not a preference: a copper branch
            # fitting does not become acceptable on a stainless line by ranking well.
            required_material = item.get("required_material")
            if required_material:
                wanted = acceptable_material_families(required_material)
                exact = _material_families(required_material)
                kept = []
                for match in matches:
                    material = match["component"].get("material")
                    families = _material_families(material) if material else set()
                    if not families:
                        match["warnings"].append(
                            f"wetted material not published; {required_material} not confirmed"
                        )
                        kept.append(match)
                    elif families & wanted:
                        if not (families & exact):
                            match["warnings"].append(
                                f"{material} on a {required_material} line: an accepted "
                                "substitution, confirm against the project specification"
                            )
                        kept.append(match)
                matches = kept

            unmet: list[str] = []
            if not matches:
                for label, value, unit in (
                    ("required Cv (US)", item.get("required_cv"), ""),
                    ("required Kv", item.get("required_kv"), ""),
                    ("required capacity", item.get("required_capacity_kw"), " kW"),
                    ("minimum bore", item.get("minimum_size_mm"), " mm"),
                    ("duty pressure", item.get("required_pressure_bar"), " bar"),
                    ("duty temperature", item.get("required_temperature_c"), " C"),
                ):
                    if value is not None:
                        unmet.append(f"{label} {value:g}{unit}")
                if item.get("required_material"):
                    unmet.append(f"wetted material {item['required_material']}")
            results.append(
                {
                    "tag": item.get("tag"),
                    "loop": item.get("loop"),
                    "quantity": item.get("quantity"),
                    "duty": {k: v for k, v in item.items() if v is not None},
                    "candidates": matches,
                    "unmet": unmet,
                }
            )

        selected = [
            r["candidates"][0]["component"]["part_number"] for r in results if r["candidates"]
        ]

        # One envelope per hydraulic loop. TCS and FWS meet only across the CDU's
        # thermal coupling, so treating every selected part as one assembly would
        # report a governing pressure for a circuit that does not exist.
        by_loop: dict[str, list[str]] = {}
        for r in results:
            if r["candidates"]:
                loop = r.get("loop") or "unspecified"
                by_loop.setdefault(loop, []).append(
                    r["candidates"][0]["component"]["part_number"]
                )
        assemblies = {
            loop: self.compatibility(parts)
            for loop, parts in by_loop.items()
            if len(parts) > 1
        }
        return {
            "items": results,
            "selected_part_numbers": selected,
            "assemblies_by_loop": assemblies,
            "unresolved": [r["tag"] for r in results if not r["candidates"]],
            "note": (
                "Shortlist by published capacity only. Vendor review of trim, authority, "
                "cavitation, materials and pressure class is still required."
            ),
        }

    def compatibility(
        self,
        part_numbers: list[str],
        *,
        max_connection_time: float | None = None,
        required_material: str | None = None,
        required_connection_standard: str | None = None,
        required_coolant: str | None = None,
        required_pressure_bar: float | None = None,
        required_temperature_c: float | None = None,
    ) -> dict[str, Any]:
        selected = [
            c for c in self.catalog.components if c.part_number.lower() in {p.lower() for p in part_numbers}
        ]
        report = check_compatibility(
            selected,
            max_install_connection_time_min=max_connection_time,
            required_material=required_material,
            required_connection_standard=required_connection_standard,
            required_coolant=required_coolant,
            required_pressure_bar=required_pressure_bar,
            required_temperature_c=required_temperature_c,
        )
        return {
            "is_compatible": report.is_compatible,
            "reasons": report.reasons,
            "notes": report.notes,
            "limits": report.limits,
            "selected_count": len(selected),
            "requested_count": len(part_numbers),
        }

    def explain(self, *, property_name: str | None = None, category: str | None = None) -> dict[str, str]:
        if property_name:
            return {"type": "property", "name": property_name, "explanation": explain_property(property_name)}
        if category:
            return {"type": "category", "name": category, "explanation": explain_category(category)}
        return {"type": "error", "name": "", "explanation": "Provide property_name or category."}
