"""Adapter for a reference-design generator's schedules.

The upstream studio emits a valve schedule with one row per physical item, already
carrying the loop, nominal size, wetted material and - once preliminary sizing has run
- a required valve Cv at an allocated pressure drop. This turns those rows into the
duty items the selector consumes.

Two things this deliberately does not do:

* It does not invent a duty. A schedule generated in manual geometry mode carries no
  flow, no allocated pressure drop and no Cv, and selecting a valve from nominal size
  alone would look like an engineering result while resting on nothing.
* It does not collapse the loops. A TCS item and an FWS item sit either side of the
  CDU's thermal coupling and are not part of one hydraulic assembly.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from .units import inch_to_mm

# Schedule component types mapped onto the catalogue's controlled vocabulary.
TYPE_TO_CATEGORY: dict[str, tuple[str, Optional[str]]] = {
    "isolation_valve": ("valve", "shutoff_valve"),
    "balancing_valve": ("valve", None),
    "check_valve": ("valve", "check_valve"),
    "control_valve": ("valve", None),
    "quick_disconnect": ("quick_disconnect", None),
    "strainer": ("strainer", None),
    "filter_dryer": ("filter_dryer", None),
    "cdu_primary": ("cdu", None),
    "cdu_secondary": ("cdu", None),
    "cdu_enclosure": ("cdu", None),
}

# Pipe-family codes mapped onto wetted-material families.
MATERIAL_TO_FAMILY = {
    "stainless_sch10": "Stainless Steel",
    "stainless_sch40": "Stainless Steel",
    "copper_type_l": "Copper",
    "copper_type_k": "Copper",
    "carbon_steel_sch40": "Carbon Steel",
    "carbon_steel_sch80": "Carbon Steel",
}

# A schedule says so itself when nothing hydraulic has been assigned.
_UNASSIGNED_MARKERS = ("unassigned", "manual geometry sizing")


def _number(value: str | None) -> Optional[float]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed


def _duty_is_assigned(row: dict[str, str]) -> bool:
    basis = (row.get("hydraulic_result_basis") or "").lower()
    if any(marker in basis for marker in _UNASSIGNED_MARKERS):
        return False
    cv = _number(row.get("valve_Cv"))
    return cv is not None and cv > 0


def duties_from_valve_schedule(path: str | Path) -> list[dict[str, Any]]:
    """Group a valve schedule into one duty item per distinct requirement.

    A 126-row schedule of a 32-rack design holds eight distinct duties. Selecting
    once per row would repeat the same answer 64 times; the tags are carried through
    so each duty still names the items it covers.
    """
    rows = list(csv.DictReader(Path(path).open("r", encoding="utf-8", newline="")))
    grouped: dict[tuple, list[dict[str, str]]] = defaultdict(list)

    for row in rows:
        signature = (
            (row.get("type") or "").strip(),
            (row.get("size_nominal_in") or "").strip(),
            (row.get("service") or "").strip(),
            (row.get("material") or "").strip(),
            (row.get("valve_Cv") or "").strip(),
            (row.get("dp_Pa") or "").strip(),
        )
        grouped[signature].append(row)

    duties: list[dict[str, Any]] = []
    for signature, members in grouped.items():
        kind, size_in, service, material, _, _ = signature
        category, subtype = TYPE_TO_CATEGORY.get(kind, (None, None))
        sample = members[0]
        tags = [m.get("tag") or m.get("component_id") or "" for m in members]

        duty: dict[str, Any] = {
            "tag": f"{service or 'UNSPECIFIED'}-{kind}-{size_in or 'NA'}in",
            "category": category,
            "component_subtype": subtype,
            "loop": service or None,
            "required_material": MATERIAL_TO_FAMILY.get(material),
            "schedule_type": kind,
            "quantity": sum(int(_number(m.get("quantity_each")) or 1) for m in members),
            "tags": tags,
        }

        nominal = _number(size_in)
        if nominal is not None:
            duty["minimum_size_mm"] = round(inch_to_mm(nominal), 2)

        if _duty_is_assigned(sample):
            duty["required_cv"] = _number(sample.get("valve_Cv"))
            duty["allocated_dp_pa"] = _number(sample.get("dp_Pa"))
            duty["design_flow_m3_s"] = _number(sample.get("design_flow_m3_s"))
        else:
            duty["duty_unassigned"] = (
                "the schedule reports "
                f"{(sample.get('hydraulic_result_basis') or 'no hydraulic basis').strip()}"
                " and no valve Cv, so there is no hydraulic duty to select against"
            )

        if category is None:
            duty["unmappable"] = f"schedule type {kind!r} has no catalogue category"

        duties.append(duty)

    duties.sort(key=lambda d: (d["loop"] or "", d.get("schedule_type", ""), d.get("minimum_size_mm") or 0))
    return duties


# The generator computes a required Kv only where one is meaningful. A balancing or
# control valve is sized on its throttling coefficient at an allocated pressure drop;
# an isolation or check valve is on/off, and its full-open Kv is not a design
# constraint. Those are selected on bore, rating and material instead.
THROTTLING_TYPES = {"balancing_valve", "control_valve"}


def duties_from_sizing(
    valve_capacities: list[dict[str, Any]],
    schedule_rows: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Build duties from the generator's own preliminary-sizing output.

    ``valve_capacities`` entries carry ``component_id``, ``Cv_US``, ``Kv_m3_h``,
    ``allocated_dp_Pa`` and ``flow_m3_s``. The schedule, when supplied, adds the loop,
    wetted material and nominal bore for the same tag.
    """
    context: dict[str, dict[str, str]] = {}
    for row in schedule_rows or []:
        tag = (row.get("tag") or row.get("component_id") or "").strip()
        if tag:
            context[tag] = row

    duties: list[dict[str, Any]] = []
    for entry in valve_capacities:
        tag = str(entry.get("component_id") or entry.get("edge_id") or "").strip()
        row = context.get(tag, {})
        kind = (row.get("type") or "").strip()
        category, subtype = TYPE_TO_CATEGORY.get(kind, ("valve", None))

        duty: dict[str, Any] = {
            "tag": tag,
            "edge_id": entry.get("edge_id"),
            "category": category,
            "component_subtype": subtype,
            "loop": (row.get("service") or "").strip() or None,
            "required_material": MATERIAL_TO_FAMILY.get((row.get("material") or "").strip()),
            "schedule_type": kind or None,
            "required_cv": _number(str(entry.get("Cv_US"))) if entry.get("Cv_US") is not None else None,
            "allocated_dp_pa": entry.get("allocated_dp_Pa"),
            "design_flow_m3_s": entry.get("flow_m3_s"),
        }

        nominal = _number(row.get("size_nominal_in"))
        if nominal is not None:
            duty["minimum_size_mm"] = round(inch_to_mm(nominal), 2)

        if kind and kind not in THROTTLING_TYPES:
            # Keep the coefficient out of the requirement so an on/off valve is not
            # judged against a throttling figure it was never sized for.
            duty["required_cv"] = None
            duty["sizing_note"] = (
                f"{kind} is on/off; selected on bore, pressure class and material "
                "rather than a required flow coefficient"
            )

        duties.append({k: v for k, v in duty.items() if v is not None})
    return duties


# The fields that decide whether a previous choice is still valid. Geometry moves,
# renamed tags and configuration hashes are deliberately absent: a 0.25 m pod move
# changes the applied hash and changes nothing about what part fits.
_DUTY_FIELDS = (
    "category",
    "component_subtype",
    "schedule_type",
    "loop",
    "required_cv",
    "required_kv",
    "required_capacity_kw",
    "minimum_size_mm",
    "required_material",
    "required_pressure_bar",
    "required_temperature_c",
)


def duty_fingerprint(duty: dict[str, Any]) -> str:
    """A short digest of everything that determines whether a part still fits.

    Keyed on the requirement rather than the configuration hash, so a decision
    survives an Apply that did not change the duty, and does not survive one that did.
    Numbers are rounded before hashing so that floating-point noise in a recomputed
    but unchanged duty does not invalidate a decision.
    """
    parts: list[str] = []
    for field in _DUTY_FIELDS:
        value = duty.get(field)
        if isinstance(value, (int, float)):
            parts.append(f"{field}={round(float(value), 6):g}")
        elif value is not None:
            parts.append(f"{field}={value}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _decision_still_valid(
    decision: dict[str, Any],
    duty: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    """Re-check a carried-forward decision against the current catalogue.

    A decision can be invalidated without the duty changing: the catalogue row may
    have been corrected, marked disputed, or removed since the choice was made.
    """
    if decision.get("choice") != "catalogue":
        return True, None

    part = decision.get("part_number")
    match = next((c for c in candidates if c["component"]["part_number"] == part), None)
    if match is None:
        return False, (
            f"{part} no longer meets this duty in the current catalogue; re-select"
        )
    if match["component"].get("verification_status") == "disputed":
        return False, (
            f"{part} is now marked disputed: vendor literature does not support the "
            "entry; re-select"
        )
    return True, None


def reconcile(
    duties: list[dict[str, Any]],
    selection: dict[str, Any],
    previous_decisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pair what the generator calculated with what the catalogue offers.

    Produces one row per tag with the calculated duty beside the suggested part and an
    unset decision. The design is not published until every row has one: the choice
    between the calculated requirement and a catalogue part belongs to the engineer,
    and a tag the catalogue cannot answer needs a component sourced elsewhere.
    """
    by_tag = {item.get("tag"): item for item in selection.get("items", [])}
    carried = previous_decisions or {}
    rows: list[dict[str, Any]] = []

    for duty in duties:
        tag = str(duty.get("tag") or "")
        result = by_tag.get(tag, {})
        candidates = result.get("candidates", [])
        best = candidates[0] if candidates else None

        calculated = {
            "required_cv_us": duty.get("required_cv"),
            "allocated_dp_pa": duty.get("allocated_dp_pa"),
            "design_flow_m3_s": duty.get("design_flow_m3_s"),
            "minimum_size_mm": duty.get("minimum_size_mm"),
            "required_material": duty.get("required_material"),
            "note": duty.get("sizing_note"),
        }

        suggested: dict[str, Any] | None = None
        if best is not None:
            component = best["component"]
            suggested = {
                "part_number": component["part_number"],
                "brand": component["brand"],
                "description": component["component_name"],
                "flow_coefficient": component["flow_coefficient_value"],
                "flow_coefficient_type": component["flow_coefficient_type"],
                "nominal_size_mm": component["nominal_size_mm"],
                "material": component["material"],
                "pressure_rating_bar": component["pressure_rating_bar"],
                "max_temperature_c": component["max_temperature_c"],
                "datasheet_url": component["datasheet_url"],
                "verification_status": component["verification_status"],
                "oversize": best["score"],
                "warnings": best.get("warnings", []),
                "alternatives": [c["component"]["part_number"] for c in candidates[1:]],
            }

        fingerprint = duty_fingerprint(duty)
        decision = carried.get(tag)
        stale_reason: str | None = None

        if decision is not None:
            if decision.get("duty_fingerprint") != fingerprint:
                stale_reason = (
                    "the duty changed since this was decided; review it against the "
                    "new requirement"
                )
                decision = None
            else:
                still_valid, reason = _decision_still_valid(decision, duty, candidates)
                if not still_valid:
                    stale_reason = reason
                    decision = None

        if decision is not None:
            action = "decided"
        elif suggested is not None:
            action = "choose"
        else:
            action = "source_externally"

        row: dict[str, Any] = {
            "tag": tag,
            "loop": duty.get("loop"),
            "schedule_type": duty.get("schedule_type"),
            "duty_fingerprint": fingerprint,
            "calculated": {k: v for k, v in calculated.items() if v is not None},
            "suggested": suggested,
            # Unset unless a previous decision survived. The engineer picks per component.
            "decision": decision,
            "action_required": action,
            "unmet": result.get("unmet", []),
        }
        if stale_reason:
            row["decision_invalidated"] = stale_reason
        rows.append(row)

    needs_sourcing = [r["tag"] for r in rows if r["action_required"] == "source_externally"]
    undecided = [r["tag"] for r in rows if r["decision"] is None]
    invalidated = [r["tag"] for r in rows if r.get("decision_invalidated")]
    return {
        "rows": rows,
        "needs_external_sourcing": needs_sourcing,
        "undecided": undecided,
        "invalidated": invalidated,
        "carried_forward": [
            r["tag"] for r in rows if r["decision"] is not None and r["tag"] in carried
        ],
        "ready_to_publish": not undecided,
        "note": (
            "Every row needs a decision before the design is published. A suggested "
            "part is a capacity shortlist, not a specification; a tag listed under "
            "needs_external_sourcing has no catalogue answer and requires a component "
            "sourced from vendor literature. Decisions are keyed on the duty, so they "
            "survive an Apply that did not change the requirement and are dropped by "
            "one that did."
        ),
    }


def decisions_from_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collect the decisions from a reviewed report, ready to pass to the next run."""
    return {
        row["tag"]: row["decision"]
        for row in rows
        if row.get("decision") is not None and row.get("tag")
    }


def record_decision(
    row: dict[str, Any],
    choice: str,
    *,
    part_number: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Build a decision for one reviewed row.

    ``choice`` is "catalogue" (take the suggested part), "calculated" (keep the
    generator's requirement and source the part separately), or "external" (a part
    found outside this catalogue).
    """
    if choice not in {"catalogue", "calculated", "external"}:
        raise ValueError(f"unknown choice {choice!r}")
    if choice == "catalogue" and not part_number:
        suggested = row.get("suggested") or {}
        part_number = suggested.get("part_number")
        if not part_number:
            raise ValueError("a catalogue choice needs a part number")
    decision: dict[str, Any] = {
        "choice": choice,
        "duty_fingerprint": row["duty_fingerprint"],
    }
    if part_number:
        decision["part_number"] = part_number
    if note:
        decision["note"] = note
    return decision
