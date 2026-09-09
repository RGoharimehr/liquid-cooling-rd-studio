from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EquipmentComponent:
    brand: str
    category: str
    component_subtype: Optional[str]
    series_name: str
    component_name: str
    nominal_size_mm: Optional[float]
    nominal_size_inch: Optional[float]
    flow_coefficient_type: Optional[str]
    flow_coefficient_value: Optional[float]
    capacity_kw: Optional[float]
    capacity_tons: Optional[float]
    connection_type: Optional[str]
    connection_standard: Optional[str]
    material: Optional[str]
    pressure_rating_bar: Optional[float]
    max_temperature_c: Optional[float]
    coolant_compatibility: Optional[str]
    estimated_price_usd: Optional[float]
    install_connection_time_min: Optional[float]
    part_number: str
    source_catalog: Optional[str]
    source_page: Optional[str]
    datasheet_url: Optional[str]
    baseline_references: Optional[str]
    # "verified": every figure was read from the cited document.
    # "unverified": not yet checked against a source.
    # "disputed": checked, and the vendor literature does not support it.
    verification_status: str = "unverified"


@dataclass(frozen=True)
class MatchResult:
    component: EquipmentComponent
    score: float
    # Non-fatal caveats: an unpublished rating that could not be checked against
    # the stated duty, or a row whose specs are unverified.
    warnings: tuple[str, ...] = ()
