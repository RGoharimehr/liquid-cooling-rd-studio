from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .models import EquipmentComponent

# End connections that mate directly, or that the industry treats as the same joint.
# Grouped by family so that vendor wording differences do not read as incompatibility.
_CONNECTION_FAMILIES: list[set[str]] = [
    {"NPT", "FPT", "MPT", "THREADED", "PIPE THREAD"},
    {"ODF", "ODS", "SOLDER", "BRAZED"},
    {"SW", "SOCKET WELD", "BW", "BUTT WELD", "WELD"},
    {"FLANGED", "FLANGE", "OVAL FLANGE"},
    {"TRI-CLAMP", "TRI CLAMP", "SANITARY FLANGE", "HYGIENIC FLANGE", "CLAMP"},
    {"GROOVED", "VICTAULIC"},
    {"ORB", "SAE STRAIGHT THREAD", "SAE"},
    {"UQD", "BLIND MATE", "HOSE BARB", "QUICK DISCONNECT"},
]

# Wetted-material families. "SS303", "303 Stainless Steel" and "Stainless Steel" all
# describe austenitic stainless; comparing the raw strings reports a mismatch between
# two parts made of the same thing.
_MATERIAL_FAMILIES: dict[str, tuple[str, ...]] = {
    "stainless steel": ("stainless", "ss3", "ss 3", "ss4", "316", "304", "303", "austenitic"),
    "copper": ("copper", "cu ", "c12200"),
    "brass/bronze": ("brass", "bronze"),
    "carbon steel": ("carbon steel", "cold resistant steel", "p285", "g20mn5", "steel"),
    "cast iron": ("cast iron", "gray iron", "grey iron", "astm a126"),
    "aluminium": ("aluminium", "aluminum"),
    "polymer": ("polymer", "epdm", "ptfe", "peek", "nylon"),
}

# Coolant families, so that "Water/EGW/PGW" and "Water/Glycol" are recognised as the
# same duty rather than a mismatch.
_COOLANT_FAMILIES: dict[str, tuple[str, ...]] = {
    "water": ("water", "dw", "pw"),
    "glycol": ("glycol", "egw", "pgw", "eg", "pg", "ethylene", "propylene"),
    "dielectric": ("dielectric", "r-1233", "r1233", "r-515", "r515", "novec", "fluorinert"),
    "hfc/hcfc": ("hfc", "hcfc", "r134", "r404", "r410", "r407", "r22"),
    "ammonia": ("ammonia", "nh3", "r717"),
    "co2": ("co2", "r744"),
}

# Material families that are routinely used together on the same line. A bronze or
# brass valve body on a copper line is ordinary hydronic practice, so a copper
# requirement should not reject it; the substitution is still reported.
COMPATIBLE_MATERIAL_FAMILIES: dict[str, set[str]] = {
    "copper": {"copper", "brass/bronze"},
    "brass/bronze": {"brass/bronze", "copper"},
    "carbon steel": {"carbon steel", "stainless steel", "cast iron"},
    "stainless steel": {"stainless steel"},
    "cast iron": {"cast iron", "carbon steel"},
}


def acceptable_material_families(required: str) -> set[str]:
    """Families that satisfy a stated wetted-material requirement."""
    families = _material_families(required) or {required.strip().lower()}
    acceptable: set[str] = set()
    for family in families:
        acceptable |= COMPATIBLE_MATERIAL_FAMILIES.get(family, {family})
    return acceptable


# Dissimilar metals sharing a wetted loop invite galvanic attack. This is an advisory,
# not an incompatibility: it depends on coolant chemistry, area ratio and inhibitors.
_GALVANIC_PAIRS = {
    frozenset({"copper", "carbon steel"}),
    frozenset({"brass/bronze", "carbon steel"}),
    frozenset({"copper", "aluminium"}),
    frozenset({"brass/bronze", "aluminium"}),
    frozenset({"stainless steel", "aluminium"}),
}


@dataclass(frozen=True)
class CompatibilityReport:
    is_compatible: bool
    reasons: list[str]
    # Advisories and derived facts that do not by themselves make a selection invalid.
    notes: list[str] = field(default_factory=list)
    # The assembly envelope: the weakest part governs.
    limits: dict[str, Optional[float]] = field(default_factory=dict)


def _classify(value: str | None, families: dict[str, tuple[str, ...]]) -> set[str]:
    if not value:
        return set()
    lowered = value.strip().lower()
    return {name for name, markers in families.items() if any(m in lowered for m in markers)}


def _material_families(value: str | None) -> set[str]:
    found = _classify(value, _MATERIAL_FAMILIES)
    # "Stainless Steel" also contains "steel"; the more specific family wins.
    if "stainless steel" in found:
        found.discard("carbon steel")
    if "cast iron" in found:
        found.discard("carbon steel")
    return found


def _connection_family(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    normalized = value.strip().upper()
    for family in _CONNECTION_FAMILIES:
        if normalized in family:
            return frozenset(family)
    return frozenset({normalized})


def _connections_compatible(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True
    fa, fb = _connection_family(a), _connection_family(b)
    return bool(fa & fb)


def check_compatibility(
    components: Iterable[EquipmentComponent],
    *,
    max_install_connection_time_min: float | None = None,
    required_material: str | None = None,
    required_connection_standard: str | None = None,
    required_coolant: str | None = None,
    required_pressure_bar: float | None = None,
    required_temperature_c: float | None = None,
) -> CompatibilityReport:
    parts = list(components)
    reasons: list[str] = []
    notes: list[str] = []

    # --- assembly envelope: the lowest-rated component governs the whole loop -------
    pressures = [(p, p.pressure_rating_bar) for p in parts if p.pressure_rating_bar is not None]
    temperatures = [(p, p.max_temperature_c) for p in parts if p.max_temperature_c is not None]

    governing_pressure = min((v for _, v in pressures), default=None)
    governing_temperature = min((v for _, v in temperatures), default=None)

    if governing_pressure is not None and len(pressures) > 1:
        weakest = min(pressures, key=lambda item: item[1])[0]
        notes.append(
            f"Assembly is limited to {governing_pressure:g} bar by {weakest.part_number}"
        )
    if governing_temperature is not None and len(temperatures) > 1:
        weakest = min(temperatures, key=lambda item: item[1])[0]
        notes.append(
            f"Assembly is limited to {governing_temperature:g} C by {weakest.part_number}"
        )

    if required_pressure_bar is not None:
        for p, rating in pressures:
            if rating < required_pressure_bar:
                reasons.append(
                    f"Pressure rating too low: {p.part_number} is rated {rating:g} bar, "
                    f"system requires {required_pressure_bar:g} bar"
                )
        for p in parts:
            if p.pressure_rating_bar is None:
                notes.append(f"{p.part_number} publishes no pressure rating; confirm it against the duty")

    if required_temperature_c is not None:
        for p, tmax in temperatures:
            if tmax < required_temperature_c:
                reasons.append(
                    f"Temperature rating too low: {p.part_number} tops out at {tmax:g} C, "
                    f"system requires {required_temperature_c:g} C"
                )
        for p in parts:
            if p.max_temperature_c is None:
                notes.append(f"{p.part_number} publishes no maximum temperature; confirm it against the duty")

    # --- end connections ------------------------------------------------------------
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            a, b = parts[i], parts[j]
            if not _connections_compatible(a.connection_type, b.connection_type):
                reasons.append(
                    f"Connection mismatch: {a.part_number} ({a.connection_type}) "
                    f"vs {b.part_number} ({b.connection_type})"
                )
            a_std = (a.connection_standard or "").strip().lower()
            b_std = (b.connection_standard or "").strip().lower()
            if a_std and b_std and a_std != b_std and _connections_compatible(a.connection_type, b.connection_type):
                notes.append(
                    f"Different connection standards: {a.part_number} ({a.connection_standard}) "
                    f"vs {b.part_number} ({b.connection_standard}); verify dimensional interchange"
                )

    # --- wetted materials -------------------------------------------------------------
    if required_material:
        wanted = _material_families(required_material) or {required_material.strip().lower()}
        for p in parts:
            if not p.material:
                continue
            families = _material_families(p.material)
            if families and not (families & wanted):
                reasons.append(
                    f"Material mismatch: {p.part_number} is {p.material} "
                    f"({'/'.join(sorted(families))}), required {required_material}"
                )

    present_families: dict[str, list[str]] = {}
    for p in parts:
        for family in _material_families(p.material):
            present_families.setdefault(family, []).append(p.part_number)
    for pair in _GALVANIC_PAIRS:
        if pair <= set(present_families):
            a_family, b_family = sorted(pair)
            notes.append(
                f"Dissimilar metals in one wetted loop: {a_family} "
                f"({', '.join(present_families[a_family])}) with {b_family} "
                f"({', '.join(present_families[b_family])}); check galvanic protection and inhibitors"
            )

    # --- coolant ----------------------------------------------------------------------
    if required_coolant:
        wanted = _classify(required_coolant, _COOLANT_FAMILIES)
        for p in parts:
            if not p.coolant_compatibility:
                continue
            supported = _classify(p.coolant_compatibility, _COOLANT_FAMILIES)
            if wanted and supported and not (wanted & supported):
                reasons.append(
                    f"Coolant mismatch: {p.part_number} supports {p.coolant_compatibility}, "
                    f"required {required_coolant}"
                )
            elif not wanted and required_coolant.strip().lower() not in p.coolant_compatibility.lower():
                reasons.append(
                    f"Coolant mismatch: {p.part_number} supports {p.coolant_compatibility}, "
                    f"required {required_coolant}"
                )

    if required_connection_standard:
        expected = required_connection_standard.strip().lower()
        for p in parts:
            if p.connection_standard and p.connection_standard.strip().lower() != expected:
                reasons.append(
                    f"Connection standard mismatch: {p.part_number} standard={p.connection_standard}, "
                    f"required={required_connection_standard}"
                )

    # --- installation -----------------------------------------------------------------
    if max_install_connection_time_min is not None:
        for p in parts:
            if (
                p.install_connection_time_min is not None
                and p.install_connection_time_min > max_install_connection_time_min
            ):
                reasons.append(
                    f"Connection time too high: {p.part_number} requires {p.install_connection_time_min} min"
                )

    # --- provenance --------------------------------------------------------------------
    for p in parts:
        if p.verification_status == "disputed":
            notes.append(f"{p.part_number}: vendor literature does not support this entry")
        elif p.verification_status != "verified":
            notes.append(f"{p.part_number}: specifications not verified against a source document")

    return CompatibilityReport(
        is_compatible=not reasons,
        reasons=reasons,
        notes=notes,
        limits={
            "governing_pressure_bar": governing_pressure,
            "governing_temperature_c": governing_temperature,
        },
    )
