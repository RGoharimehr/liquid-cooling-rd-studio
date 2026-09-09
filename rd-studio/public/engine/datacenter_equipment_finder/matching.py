from __future__ import annotations

from typing import Iterable, Optional

from .models import EquipmentComponent, MatchResult
from .units import cv_to_kv, inch_to_mm, kv_to_cv, tons_to_kw

FLOW_COEFFICIENT_CATEGORIES = {"valve", "strainer", "quick_disconnect"}

# A candidate whose value for a requested criterion is unknown is worse than one that
# is merely a poor fit, up to a point: at 0.75 it loses to anything within 75% of the
# target and beats anything further out. Without this, rows with missing data win by
# default, which is how an incomplete row outranks a real match.
UNKNOWN_PENALTY = 0.75

# Criteria are not equally decisive. A CDU or chiller is selected on duty first and
# pipe size second; a valve or quick disconnect is selected on flow coefficient first.
# Weighting them equally lets a part that is 3x off on capacity win because it happens
# to publish a connection size.
WEIGHTS_BY_CATEGORY = {
    "capacity": {"capacity": 2.0, "size": 0.6, "connection": 0.8, "coefficient": 1.0},
    "coefficient": {"capacity": 1.0, "size": 0.8, "connection": 1.0, "coefficient": 2.0},
}


def _weights(category: Optional[str]) -> dict[str, float]:
    key = "coefficient" if (category or "").lower() in FLOW_COEFFICIENT_CATEGORIES else "capacity"
    return WEIGHTS_BY_CATEGORY[key]


# Rows that have not been checked against their source document lose ties but can
# still win on merit. A row the vendor literature actively contradicts is pushed
# further down, but still shown, so a stale catalog entry is visible rather than
# quietly missing.
UNVERIFIED_PENALTY = 0.05
DISPUTED_PENALTY = 0.40

# Above this multiple of a stated requirement the nearest candidate stops being a
# selection and becomes evidence that the catalogue has no suitable size. A valve 32x
# the required Kv satisfies the inequality and would be a poor specification.
GROSS_OVERSIZE_FACTOR = 2.0


def _criterion_delta(value: Optional[float], target: Optional[float]) -> Optional[float]:
    """Relative distance from target, or None when the criterion was not requested."""
    if target is None:
        return None
    if value is None:
        return UNKNOWN_PENALTY
    scale = max(abs(target), 1e-9)
    return abs(value - target) / scale


def _coefficient_for_target(
    component: EquipmentComponent,
    target_cv: Optional[float],
    target_kv: Optional[float],
) -> Optional[float]:
    if component.flow_coefficient_value is None or component.flow_coefficient_type is None:
        return None

    coeff_type = component.flow_coefficient_type.lower()
    coeff = component.flow_coefficient_value

    if target_cv is not None:
        return coeff if coeff_type == "cv" else kv_to_cv(coeff)
    if target_kv is not None:
        return coeff if coeff_type == "kv" else cv_to_kv(coeff)
    return None


def _connection_size_mm(component: EquipmentComponent) -> Optional[float]:
    if component.nominal_size_mm is not None:
        return component.nominal_size_mm
    if component.nominal_size_inch is not None:
        return inch_to_mm(component.nominal_size_inch)
    return None


def _rating_exclusions(
    component: EquipmentComponent,
    required_pressure_bar: Optional[float],
    required_temperature_c: Optional[float],
) -> tuple[bool, list[str]]:
    """Return (excluded, warnings).

    A component is excluded only when its published rating is known to be below the
    stated duty. An unknown rating cannot be proven inadequate, so the row survives
    carrying a warning rather than being silently dropped or silently trusted.
    """
    warnings: list[str] = []

    if required_pressure_bar is not None:
        if component.pressure_rating_bar is None:
            warnings.append(
                f"pressure rating not published; {required_pressure_bar:g} bar duty unconfirmed"
            )
        elif component.pressure_rating_bar < required_pressure_bar:
            return True, warnings

    if required_temperature_c is not None:
        if component.max_temperature_c is None:
            warnings.append(
                f"maximum temperature not published; {required_temperature_c:g} C duty unconfirmed"
            )
        elif component.max_temperature_c < required_temperature_c:
            return True, warnings

    if component.verification_status == "disputed":
        warnings.append("vendor literature does not support this entry; confirm before specifying")
    elif component.verification_status != "verified":
        warnings.append("specifications not verified against a source document")

    return False, warnings


def _oversize_delta(available: Optional[float], required: float) -> Optional[float]:
    """Rank a capacity shortlist by how little it exceeds the requirement.

    Selection against a required value is not a nearest-neighbour problem. A valve
    with Kv below the required figure cannot pass the design flow at the allocated
    pressure drop, so it is not a candidate at all; among those that can, the least
    oversized is the closest fit.
    """
    if available is None:
        return None
    return max(0.0, available - required) / max(abs(required), 1e-9)


def find_closest_components(
    components: Iterable[EquipmentComponent],
    *,
    category: Optional[str] = None,
    component_subtype: Optional[str] = None,
    brand: Optional[str] = None,
    target_size_mm: Optional[float] = None,
    target_cv: Optional[float] = None,
    target_kv: Optional[float] = None,
    target_capacity_kw: Optional[float] = None,
    target_capacity_tons: Optional[float] = None,
    target_connection_size_mm: Optional[float] = None,
    target_connection_size_inch: Optional[float] = None,
    required_pressure_bar: Optional[float] = None,
    required_temperature_c: Optional[float] = None,
    required_cv: Optional[float] = None,
    required_kv: Optional[float] = None,
    required_capacity_kw: Optional[float] = None,
    minimum_size_mm: Optional[float] = None,
    top_n: int = 5,
) -> list[MatchResult]:
    if target_capacity_tons is not None and target_capacity_kw is None:
        target_capacity_kw = tons_to_kw(target_capacity_tons)
    if target_connection_size_inch is not None and target_connection_size_mm is None:
        target_connection_size_mm = inch_to_mm(target_connection_size_inch)

    scored: list[MatchResult] = []
    for c in components:
        if category and c.category.lower() != category.lower():
            continue
        if component_subtype and (c.component_subtype or "").lower() != component_subtype.lower():
            continue
        if brand and c.brand.lower() != brand.lower():
            continue

        excluded, warnings = _rating_exclusions(c, required_pressure_bar, required_temperature_c)
        if excluded:
            continue

        # --- capacity requirements: below the requirement is not a candidate --------
        required_coefficient = required_cv if required_cv is not None else required_kv
        oversize: list[float] = []

        if required_coefficient is not None:
            if c.category.lower() not in FLOW_COEFFICIENT_CATEGORIES:
                continue
            available = _coefficient_for_target(c, required_cv, required_kv)
            if available is None:
                warnings.append(
                    "flow coefficient not published; cannot confirm it meets the "
                    f"required {'Cv (US)' if required_cv is not None else 'Kv'} "
                    f"of {required_coefficient:g}"
                )
            elif available < required_coefficient:
                continue
            else:
                delta = _oversize_delta(available, required_coefficient)
                if delta is not None:
                    oversize.append(delta)
                if available > GROSS_OVERSIZE_FACTOR * required_coefficient:
                    warnings.append(
                        f"flow coefficient is {available / required_coefficient:.1f}x the "
                        "requirement; the catalogue may hold no closer size"
                    )

        if required_capacity_kw is not None:
            if c.capacity_kw is None:
                warnings.append(
                    f"capacity not published; cannot confirm it meets {required_capacity_kw:g} kW"
                )
            elif c.capacity_kw < required_capacity_kw:
                continue
            else:
                delta = _oversize_delta(c.capacity_kw, required_capacity_kw)
                if delta is not None:
                    oversize.append(delta)
                if c.capacity_kw > GROSS_OVERSIZE_FACTOR * required_capacity_kw:
                    warnings.append(
                        f"capacity is {c.capacity_kw / required_capacity_kw:.1f}x the "
                        "requirement; the catalogue may hold no closer size"
                    )

        if minimum_size_mm is not None:
            bore = _connection_size_mm(c)
            if bore is None:
                warnings.append(
                    f"nominal size not published; cannot confirm it meets {minimum_size_mm:g} mm"
                )
            elif bore < minimum_size_mm:
                continue
            else:
                delta = _oversize_delta(bore, minimum_size_mm)
                if delta is not None:
                    oversize.append(delta)

        # Each requested criterion contributes its relative error. The score is the
        # weighted mean, so it stays comparable between queries that constrain
        # different things, and 0.10 means "about 10% off across the board".
        w = _weights(c.category)
        weighted = 0.0
        total_weight = 0.0

        def add(delta: Optional[float], weight: float) -> None:
            nonlocal weighted, total_weight
            if delta is not None:
                weighted += weight * delta
                total_weight += weight

        add(_criterion_delta(c.nominal_size_mm, target_size_mm), w["size"])
        add(_criterion_delta(_connection_size_mm(c), target_connection_size_mm), w["connection"])

        target_coeff = target_cv if target_cv is not None else target_kv
        if target_coeff is not None and c.category.lower() in FLOW_COEFFICIENT_CATEGORIES:
            add(
                _criterion_delta(_coefficient_for_target(c, target_cv, target_kv), target_coeff),
                w["coefficient"],
            )

        add(_criterion_delta(c.capacity_kw, target_capacity_kw), w["capacity"])

        if oversize:
            # Requirements dominate: a shortlist is ordered by fit above the
            # requirement, with any preference terms acting only as a tie-break.
            requirement_score = sum(oversize) / len(oversize)
            preference_score = weighted / total_weight if total_weight else 0.0
            score = requirement_score + 0.1 * preference_score
        else:
            score = weighted / total_weight if total_weight else 0.0
        if c.verification_status == "disputed":
            score += DISPUTED_PENALTY
        elif c.verification_status != "verified":
            score += UNVERIFIED_PENALTY

        scored.append(MatchResult(component=c, score=score, warnings=tuple(warnings)))

    return sorted(scored, key=lambda m: m.score)[: max(1, top_n)]
