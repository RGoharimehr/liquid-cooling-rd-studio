"""Headless, conservative adapter for RD duties and a freshly supplied CSV.

The caller fetches the public catalogue. This module never fetches, loads a bundled
database, calculates RD duties, or silently selects the first candidate. The pinned
finder remains responsible for numeric duty ranking; this adapter constrains its
candidate pool and distinguishes incomplete evidence from a checked shortlist.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from dataclasses import fields
from fractions import Fraction
from urllib.parse import urlparse

from datacenter_equipment_finder.catalog import EquipmentCatalog, FIELD_NAMES, KNOWN_CATEGORIES
from datacenter_equipment_finder.models import EquipmentComponent
from datacenter_equipment_finder.service import EquipmentService

ENGINE_REVISION = "c2180b8a37b1ce711c963e5422b59ac8e4f7d219"
SCHEMA_VERSION = "1.0"
MAX_CSV_BYTES = 10_000_000
MAX_ROWS = 20_000
NUMERIC_FIELDS = {
    "nominal_size_mm", "nominal_size_inch", "flow_coefficient_value", "capacity_kw",
    "capacity_tons", "pressure_rating_bar", "max_temperature_c", "estimated_price_usd",
    "install_connection_time_min",
}
# Nominal designations only: these are NOT physical inside diameters.
DN_TO_NPS = {6: .125, 8: .25, 10: .375, 15: .5, 20: .75, 25: 1., 32: 1.25,
             40: 1.5, 50: 2., 65: 2.5, 80: 3., 90: 3.5, 100: 4., 125: 5.,
             150: 6., 200: 8., 250: 10., 300: 12., 350: 14., 400: 16.,
             450: 18., 500: 20., 600: 24.}
ROLE_SUBTYPES = {
    "isolation_valve": {"shutoff_valve"}, "shutoff_valve": {"shutoff_valve"},
    "check_valve": {"check_valve"}, "balancing_valve": {"balancing_valve"},
    "control_valve": {"control_valve", "pressure_independent_control_valve"},
    "strainer": {"line_strainer"}, "line_strainer": {"line_strainer"},
    "quick_disconnect": {"hand_mate_uqd"},
}


class SelectionInputError(ValueError):
    """Input is invalid; retain any previous result visibly as stale in the UI."""


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _number(value, label, *, positive=False):
    if value is None:
        return None
    if isinstance(value, bool):
        raise SelectionInputError(f"{label}: expected a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SelectionInputError(f"{label}: expected a finite number") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise SelectionInputError(f"{label}: expected a finite {'positive ' if positive else ''}number")
    return result


def _url(value):
    try:
        parsed = urlparse(value)
        return bool(parsed.scheme in {"https", "http"} and parsed.hostname
                    and not parsed.username and not parsed.password)
    except (ValueError, TypeError):
        return False


def parse_catalogue(csv_text, metadata):
    """Fail closed on schema changes or corrupt data; no partial-row fallback."""
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise SelectionInputError("Catalogue CSV is empty; fetch the public CSV and retry")
    raw = csv_text.encode("utf-8")
    if len(raw) > MAX_CSV_BYTES:
        raise SelectionInputError("Catalogue exceeds the 10 MB input limit")
    if not isinstance(metadata, dict):
        raise SelectionInputError("Catalogue metadata must be an object")
    source = metadata.get("source_url", "")
    if not _url(source) or urlparse(source).scheme != "https" or urlparse(source).hostname not in {
        "raw.githubusercontent.com", "github.com", "api.github.com",
    }:
        raise SelectionInputError("Catalogue source_url must identify a public HTTPS GitHub resource")
    if urlparse(source).query or urlparse(source).fragment:
        raise SelectionInputError("Catalogue source_url must not contain query credentials or fragments")
    digest = hashlib.sha256(raw).hexdigest()
    expected = metadata.get("sha256") or metadata.get("expected_sha256")
    if expected and expected != digest:
        raise SelectionInputError("Catalogue SHA-256 does not match the fetched CSV")
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")), strict=True)
    header = reader.fieldnames or []
    if len(header) != len(set(header)) or set(header) != set(FIELD_NAMES):
        missing = sorted(set(FIELD_NAMES) - set(header))
        extra = sorted(set(header) - set(FIELD_NAMES))
        raise SelectionInputError(f"Unsupported catalogue schema; missing={missing}, unexpected={extra}, duplicate_headers={len(header) != len(set(header))}")
    components, seen = [], set()
    try:
        for line, row in enumerate(reader, 2):
            if line > MAX_ROWS + 1:
                raise SelectionInputError("Catalogue exceeds the 20,000-row limit")
            if None in row or any(v is None for v in row.values()):
                raise SelectionInputError(f"Catalogue row {line}: incorrect column count")
            clean = {k: v.strip() for k, v in row.items()}
            for key in ("brand", "category", "component_name", "part_number", "source_catalog", "datasheet_url"):
                if not clean[key]:
                    raise SelectionInputError(f"Catalogue row {line}: missing {key}")
            if clean["category"] not in KNOWN_CATEGORIES:
                raise SelectionInputError(f"Catalogue row {line}: unknown category {clean['category']!r}; finder core update required")
            if clean["verification_status"] not in {"verified", "unverified", "disputed"}:
                raise SelectionInputError(f"Catalogue row {line}: invalid verification_status")
            if not _url(clean["datasheet_url"]):
                raise SelectionInputError(f"Catalogue row {line}: invalid datasheet_url")
            part = clean["part_number"].casefold()
            if part in seen:
                raise SelectionInputError(f"Catalogue row {line}: duplicate part_number {clean['part_number']}")
            seen.add(part)
            values = {k: (v or None) for k, v in clean.items()}
            for key in NUMERIC_FIELDS:
                values[key] = _number(values[key], f"Catalogue row {line} {key}")
                if values[key] is not None and key != "max_temperature_c" and values[key] < 0:
                    raise SelectionInputError(f"Catalogue row {line}: negative {key}")
                if values[key] == 0 and key not in {"max_temperature_c", "estimated_price_usd", "install_connection_time_min"}:
                    raise SelectionInputError(f"Catalogue row {line}: zero {key}")
            if values["max_temperature_c"] is not None and values["max_temperature_c"] < -273.15:
                raise SelectionInputError(f"Catalogue row {line}: temperature below absolute zero")
            coefficient = values["flow_coefficient_type"]
            if coefficient is not None and coefficient not in {"Cv", "Kv"}:
                raise SelectionInputError(f"Catalogue row {line}: flow coefficient type must be Cv or Kv")
            if bool(coefficient) != (values["flow_coefficient_value"] is not None):
                raise SelectionInputError(f"Catalogue row {line}: coefficient type/value must appear together")
            kw, tons = values["capacity_kw"], values["capacity_tons"]
            if kw is not None and tons is not None and abs(kw - tons * 3.5168525) > .02 * kw:
                raise SelectionInputError(f"Catalogue row {line}: inconsistent kW and refrigeration tons")
            mm, inch = values["nominal_size_mm"], values["nominal_size_inch"]
            if mm and inch and not (math.isclose(mm, 25.4 * inch, rel_tol=.05)
                                    or math.isclose(DN_TO_NPS.get(mm, -1), inch, abs_tol=1e-6)):
                raise SelectionInputError(f"Catalogue row {line}: inconsistent nominal mm/inch designations")
            if not any(values[k] is not None for k in ("capacity_kw", "capacity_tons", "nominal_size_mm", "nominal_size_inch", "flow_coefficient_value")):
                raise SelectionInputError(f"Catalogue row {line}: no numeric selection attribute")
            # The original dataclass is the sole catalogue model, not a parallel DB.
            components.append(EquipmentComponent(**{f.name: values[f.name] for f in fields(EquipmentComponent)}))
    except csv.Error as exc:
        raise SelectionInputError(f"Malformed catalogue CSV: {exc}") from exc
    if not components:
        raise SelectionInputError("Catalogue has no equipment rows")
    provenance = {k: metadata[k] for k in ("source_url", "fetched_at", "repository_commit", "etag") if k in metadata}
    provenance.update(sha256=digest, row_count=len(components), engine_revision=ENGINE_REVISION,
                      verification_counts=dict(Counter(c.verification_status for c in components)))
    return components, provenance


def normalize_nps(value=None, *, dn=None):
    """Resolve an explicit NPS or DN designation. Never infer an actual bore."""
    if dn is not None:
        parsed_dn = _number(dn, "nominal DN", positive=True)
        mapped = DN_TO_NPS.get(parsed_dn)
        if mapped is None:
            raise SelectionInputError(f"Unsupported nominal DN {dn}; provide explicit NPS")
        if value is None:
            return mapped
    if value is None:
        return None
    try:
        text = str(value).strip().removeprefix("NPS ").rstrip('"').strip()
        result = sum(float(Fraction(part)) for part in text.split())
    except (ValueError, ZeroDivisionError) as exc:
        raise SelectionInputError(f"Invalid nominal NPS {value!r}") from exc
    result = _number(result, "nominal NPS", positive=True)
    if not any(math.isclose(result, v, abs_tol=1e-6) for v in DN_TO_NPS.values()):
        raise SelectionInputError(f"Unsupported nominal NPS {value!r}; actual bore is not nominal size")
    if dn is not None and not math.isclose(result, mapped, abs_tol=1e-6):
        raise SelectionInputError("Inconsistent requirement NPS and DN designations")
    return result


def _material(value):
    text = (value or "").lower().replace("_", " ")
    if "stainless" in text or re.search(r"\bss\s*3|\b(?:303|304|316)\b", text):
        return "stainless steel"
    if "copper" in text:
        return "copper"
    if "brass" in text or "bronze" in text:
        return "brass/bronze"
    if "cast iron" in text or "gray iron" in text or "grey iron" in text:
        return "cast iron"
    if "steel" in text:
        return "carbon steel"
    if "alumin" in text:
        return "aluminium"
    return None


def _fluid(value):
    text = (value or "").casefold()
    kinds = set()
    if "water" in text or text in {"dw", "pw"}:
        kinds.add("water")
    if "propylene" in text or re.search(r"\bpg(?:w|\d|\b)", text):
        kinds.add("pg")
    if "ethylene" in text or re.search(r"\beg(?:w|\d|\b)", text):
        kinds.add("eg")
    if "glycol" in text and not kinds.intersection({"pg", "eg"}):
        kinds.add("glycol_unspecified")
    if re.search(r"refrigerant|r-?\d|hfc|hcfc|ammonia|co2|nh3|dielectric", text):
        kinds.add("other_fluid")
    return kinds


def _fluid_check(required, available):
    """Return (known mismatch, limitation). Water in PGW does not imply water-only duty."""
    name = required.get("name") if isinstance(required, dict) else required
    want, have = _fluid(name), _fluid(available)
    if not name:
        return False, "RD coolant specification is missing"
    if not available or not have or not want:
        return False, "Coolant compatibility is not established from the catalogue terminology"
    if "pg" in want or "eg" in want:
        species = "pg" if "pg" in want else "eg"
        if species not in have:
            if "glycol_unspecified" in have:
                return False, "Catalogue lists generic glycol; species, concentration and inhibitor package require vendor confirmation"
            return True, None
        return False, "Glycol concentration, inhibitor package and seals require vendor confirmation"
    if "glycol_unspecified" in want:
        return (not bool(have & {"pg", "eg", "glycol_unspecified"}), "RD glycol species/concentration is unspecified")
    if "water" in want:
        return "water" not in have, None
    if (name or "").casefold() == (available or "").casefold():
        return False, None
    return False, "Specific fluid compatibility requires vendor confirmation"


def _collect_duty(item):
    sides = item.get("fluid_sides") or []
    ports = item.get("ports") or []
    if not isinstance(sides, list) or not all(isinstance(x, dict) for x in sides):
        raise SelectionInputError(f"{item['id']}: fluid_sides must contain objects")
    if not isinstance(ports, list) or not all(isinstance(x, dict) for x in ports):
        raise SelectionInputError(f"{item['id']}: ports must contain objects")
    nps = {normalize_nps(p.get("nominal_nps_in"), dn=p.get("nominal_dn")) for p in ports}
    nps.discard(None)
    pressures, temperatures, materials, fluids, standards, connections = [], [], [], [], [], []
    missing = [issue['detail'] for issue in item.get('unresolved', [])
               if issue.get('code') == 'MANUAL_VELOCITY_LIMIT_EXCEEDED' and issue.get('detail')]
    for side in sides:
        pressure = _number(side.get("minimum_pressure_rating_Pa"), "minimum_pressure_rating_Pa", positive=True)
        temperature = _number((side.get("temperature") or {}).get("required_max_temperature_C"), "required_max_temperature_C")
        if pressure is None:
            missing.append("RD design pressure/minimum pressure rating is unassigned; pumping differential is not a pressure rating")
        else:
            pressures.append(pressure / 100_000)
        if temperature is None:
            missing.append("RD maximum fluid temperature is unassigned")
        else:
            temperatures.append(temperature)
        fluids.append(side.get("fluid") or {})
        specified = side.get("required_material") or item.get("required_material")
        if specified:
            materials.append(specified)
        elif side.get("connected_pipe_materials"):
            missing.append("Wetted-material and seal specification requires review; connected pipe material alone does not specify an accessory alloy")
    if not sides:
        missing.append("RD fluid-side operating conditions are missing")
    for port in ports:
        if port.get("connection_standard"):
            standards.append(port["connection_standard"])
        if port.get("connection_type"):
            connections.append(port["connection_type"])
    if not standards:
        missing.append("Mating connection standard is unassigned")
    if not nps:
        missing.append("Nominal connection size is missing; physical bore is not substituted")
    for node, keys in ((item.get("throttling") or {}, ("required_Cv_US", "required_Kv_m3_h", "allocated_dp_Pa")),
                       (item.get("thermal_duty") or {}, ("required_capacity_W",))):
        for key in keys:
            _number(node.get(key), key, positive=True)
    throttle, thermal = item.get("throttling") or {}, item.get("thermal_duty") or {}
    kv, cv = throttle.get("required_Kv_m3_h"), throttle.get("required_Cv_US")
    if kv is not None and cv is not None and not math.isclose(float(cv), float(kv) * 1.1561, rel_tol=.005):
        raise SelectionInputError(f"{item['id']}: inconsistent required Kv and Cv (US)")
    kwargs = {
        "required_kv": float(kv) if kv is not None else None,
        "required_cv": float(cv) if cv is not None and kv is None else None,
        "required_capacity_kw": float(thermal["required_capacity_W"]) / 1000 if thermal.get("required_capacity_W") is not None else None,
        "required_pressure_bar": max(pressures) if pressures else None,
        "required_temperature_c": max(temperatures) if temperatures else None,
    }
    return dict(sides=sides, ports=ports, nps=nps, fluids=fluids, materials=materials,
                standards=standards, connections=connections, missing=missing, kwargs=kwargs)


def _candidate_filter(component, item, duty):
    """All definite incompatibilities are removed before limiting the shortlist."""
    notes = list(duty["missing"])
    if component.verification_status == "disputed":
        return "disputed_source", notes
    if component.verification_status != "verified":
        notes.append("Catalogue row is not verified against its cited source")
    category = item["category"]
    subtype = item.get("subtype") or item.get("component_subtype")
    role = item.get("kind")
    allowed = ROLE_SUBTYPES.get(role) or ({subtype} if subtype else None)
    if allowed and component.component_subtype not in allowed:
        return "functional_role", notes
    if not allowed and category in {"valve", "quick_disconnect"}:
        return "functional_role_unspecified", notes
    if category == "cdu":
        name = component.component_name.lower().replace("-", " ")
        if "liquid to air" in name or "two phase" in name or component.component_subtype == "liquid_to_air_cdu":
            return "heat_transfer_architecture", notes
    multi = category in {"cdu", "chiller"}
    if multi:
        notes.append("Capacity-only candidate: operating-point performance, per-circuit flows/pressure drops, port sizes, pressure/temperature ratings and hydraulic separation are not represented by this catalogue")
        # Its one generic rating/connection must not be applied to FWS and TCS/CWS.
    elif len(duty["nps"]) == 1:
        wanted = next(iter(duty["nps"]))
        have = component.nominal_size_inch
        if have is None and component.nominal_size_mm is not None:
            have = DN_TO_NPS.get(component.nominal_size_mm)
        if have is None:
            notes.append("Catalogue nominal NPS/DN connection designation is unavailable or ambiguous")
        elif not math.isclose(wanted, have, abs_tol=1e-6):
            return "nominal_connection_size", notes
    elif len(duty["nps"]) > 1:
        notes.append("Different port sizes cannot be verified from one generic catalogue nominal size")
    for required in duty["materials"]:
        wanted, have = _material(required), _material(component.material)
        if not component.material or not have or not wanted:
            notes.append(f"Wetted material {required} is not confirmed")
        elif wanted != have:
            return "material", notes
        elif "stainless" in wanted:
            required_grade = re.search(r"(?:303|304|316)L?", required, re.I)
            actual_grade = re.search(r"(?:303|304|316)L?", component.material, re.I)
            if required_grade and actual_grade and required_grade[0].casefold() != actual_grade[0].casefold():
                return "material_grade", notes
            if required_grade and not actual_grade:
                notes.append(f"Required stainless grade {required_grade[0]} is not published")
    for fluid in duty["fluids"]:
        if multi:
            notes.append("Per-circuit coolant compatibility is unresolved: the catalogue's generic fluid rating is not assigned to an FWS, TCS or condenser-water side")
            continue
        mismatch, note = _fluid_check(fluid, component.coolant_compatibility)
        if mismatch:
            return "coolant", notes
        if note:
            notes.append(note)
    for key, requirements in (("connection_standard", duty["standards"]), ("connection_type", duty["connections"])):
        for required in requirements:
            available = getattr(component, key)
            if multi or not available:
                notes.append(f"{key} {required} is not confirmed for each required port")
            elif re.sub(r"[^a-z0-9]", "", available.lower()) != re.sub(r"[^a-z0-9]", "", required.lower()):
                return key, notes
    if category == "strainer":
        notes.append("Filtration mesh, clean/dirty loss and service access require vendor confirmation")
    if category == "quick_disconnect":
        notes.append("Mating half/profile, seal chemistry and spill/air-ingress limits require vendor confirmation")
    if role in {"balancing_valve", "control_valve"}:
        notes.append("Required Kv is a conductance check; trim/rangeability, authority, cavitation and actuator duty require vendor confirmation")
    return None, notes


def select_requirements(requirements, catalogue_csv_text, catalogue_metadata):
    """Return snapshot-bound shortlists, retaining missing evidence as tentative.

    ``qualified`` means the declared preliminary catalogue checks passed; it is
    never procurement approval or proof of geometry, hydraulics or redundancy.
    """
    if not isinstance(requirements, dict) or requirements.get("schema_version") != SCHEMA_VERSION:
        raise SelectionInputError("Unsupported RD requirements schema; expected 1.0")
    config_hash = requirements.get("config_hash")
    if not isinstance(config_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", config_hash):
        raise SelectionInputError("Requirements must carry the applied configuration SHA-256")
    items = requirements.get("requirements")
    if not isinstance(items, list) or len(items) > 20_000:
        raise SelectionInputError("requirements must be an array of at most 20,000 items")
    if not all(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] for item in items):
        raise SelectionInputError("Each requirement needs a stable nonempty id")
    if len({item["id"] for item in items}) != len(items):
        raise SelectionInputError("Requirement IDs must be unique")
    try:
        requirement_hash = _hash(requirements)
    except (TypeError, ValueError) as exc:
        raise SelectionInputError("Requirements must contain finite JSON data") from exc
    components, provenance = parse_catalogue(catalogue_csv_text, catalogue_metadata)
    top_n = requirements.get("top_n", 3)
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= 20:
        raise SelectionInputError("top_n must be an integer from 1 to 20")
    binding = dict(config_hash=config_hash, requirements_sha256=requirement_hash,
                   catalogue_sha256=provenance["sha256"], engine_revision=ENGINE_REVISION)
    result = dict(schema_version=SCHEMA_VERSION, **binding, catalogue=provenance, items=[], unresolved=[],
                  selected_part_numbers=[], scope="Preliminary catalogue shortlist; no automatic selection, geometry replacement, hydraulic solving or procurement approval")
    for item in items:
        output = dict(id=item["id"], component_id=item.get("component_id"), kind=item.get("kind"),
                      category=item.get("category"), circuit_ids=item.get("circuit_ids", []),
                      quantity=item.get("quantity", 1), candidates=[], unresolved=[],
                      exclusions={}, binding=dict(binding))
        result["items"].append(output)
        category = item.get("category")
        if requirements.get("ready_for_matching") is False:
            output["unresolved"].append("RD matching preconditions failed; apply a design with consistent calculated duties and nominal sizes")
        elif item.get("supported_by_finder") is False or category not in KNOWN_CATEGORIES:
            output["unresolved"].append(f"No supported catalogue role for {item.get('kind') or category}; RD duty is retained")
        elif category == "filter_dryer":
            output["unresolved"].append("Refrigerant filter-dryers are outside the direct-to-chip water/glycol scope")
        elif item.get("ready_for_matching") is False:
            output["unresolved"].append("RD duty or physical interface is incomplete; resolve the component requirements before matching")
        if output["unresolved"]:
            result["unresolved"].append(item["id"])
            continue
        duty = _collect_duty(item)
        pool, notes_by_part, excluded = [], {}, Counter()
        for component in components:
            if component.category != category:
                continue
            reason, notes = _candidate_filter(component, item, duty)
            if reason:
                excluded[reason] += 1
            else:
                pool.append(component)
                notes_by_part[component.part_number] = notes
        # Do not call select_for_duty: it limits before material filtering and can
        # identify its first result as selected. Use the original numeric matcher.
        numeric = dict(duty["kwargs"])
        if category in {"cdu", "chiller"}:
            numeric["required_pressure_bar"] = None
            numeric["required_temperature_c"] = None
        ranked = EquipmentService(EquipmentCatalog(pool)).find_components(
            category=category, top_n=max(1, len(pool)), **numeric)
        excluded["published_duty_below_requirement"] += len(pool) - len(ranked)
        for match in ranked:
            component = match["component"]
            notes = list(dict.fromkeys(notes_by_part[component["part_number"]] + match.get("warnings", [])))
            # Original warnings include oversize and unpublished ratings: neither
            # should be surfaced as a clean recommendation by this wrapper.
            status = "tentative" if notes else "qualified"
            unknown_duty_values = sum('not published' in warning or 'cannot confirm' in warning or 'unconfirmed' in warning for warning in match.get('warnings', []))
            output["candidates"].append(dict(component=component, score=match["score"], status=status, unknown_duty_values=unknown_duty_values,
                                               limitations=notes, binding=dict(binding),
                                               qualification_scope="Declared preliminary catalogue checks only"))
        output["candidates"].sort(key=lambda c: (c["status"] != "qualified", c['unknown_duty_values'], c["score"], c["component"]["part_number"]))
        output["candidates"] = output["candidates"][:top_n]
        output["exclusions"] = {k: v for k, v in excluded.items() if v}
        output["qualified_count"] = sum(c["status"] == "qualified" for c in output["candidates"])
        if not output["candidates"]:
            output["unresolved"].append("No catalogue candidate matches the required functional role and declared duty/compatibility filters")
        elif not output["qualified_count"]:
            output["unresolved"].append("Tentative candidates only; missing or conditional vendor/project evidence must be resolved")
        if output["unresolved"]:
            result["unresolved"].append(item["id"])
    result['status'] = 'complete'
    result['applied_config_hash'] = config_hash
    result['summary'] = {'items':len(result['items']),
        'with_candidates':sum(bool(i['candidates']) for i in result['items']),
        'qualified':sum(bool(i.get('qualified_count')) for i in result['items']),
        'tentative':sum(bool(i['candidates']) and not i.get('qualified_count') for i in result['items']),
        'unresolved':len(result['unresolved'])}
    return result
