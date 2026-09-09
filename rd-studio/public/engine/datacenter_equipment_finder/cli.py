from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from dataclasses import replace

from .assistant import default_assistant_config, run_assistant_query
from .catalog import EquipmentCatalog
from .catalog_tools import build_sqlite_database, download_catalogs
from .compatibility import check_compatibility
from .dataset_pipeline import build_catalog_from_vendor_sources
from .explanations import explain_category, explain_property
from .matching import find_closest_components
from .pdf_catalog import build_database_from_pdf
from .rd_studio import duties_from_sizing, duties_from_valve_schedule, reconcile
from .service import EquipmentService
from .web import run_server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dcef", description="Data Center Equipment Finder")
    sub = parser.add_subparsers(dest="command", required=True)

    f = sub.add_parser("find", help="Find closest components")
    f.add_argument("--category", required=False)
    f.add_argument("--component-subtype", required=False)
    f.add_argument("--brand", required=False)
    f.add_argument("--size-mm", type=float, required=False)
    f.add_argument("--cv", type=float, required=False)
    f.add_argument("--kv", type=float, required=False)
    f.add_argument("--capacity-kw", type=float, required=False)
    f.add_argument("--capacity-tons", type=float, required=False)
    f.add_argument("--connection-size-mm", type=float, required=False)
    f.add_argument("--connection-size-inch", type=float, required=False)
    f.add_argument("--required-pressure-bar", type=float, default=None,
                   help="Exclude parts rated below this working pressure")
    f.add_argument("--required-temperature-c", type=float, default=None,
                   help="Exclude parts rated below this maximum temperature")
    f.add_argument("--top-n", type=int, default=5)

    c = sub.add_parser("compat", help="Check compatibility for part numbers")
    c.add_argument("part_numbers", nargs="+", help="Part numbers to evaluate")
    c.add_argument("--max-connection-time", type=float)
    c.add_argument("--required-material")
    c.add_argument("--required-connection-standard")
    c.add_argument("--required-coolant")
    c.add_argument("--required-pressure-bar", type=float, default=None,
                   help="System pressure the whole assembly must withstand")
    c.add_argument("--required-temperature-c", type=float, default=None,
                   help="Coolant temperature the whole assembly must withstand")

    sel = sub.add_parser(
        "select",
        help="Shortlist parts against a design's per-component duties (JSON in, JSON out)",
    )
    source = sel.add_mutually_exclusive_group(required=True)
    source.add_argument("--duty", help="Path to a duty spec, or - for stdin")
    source.add_argument("--schedule", help="Path to a reference-design valve schedule CSV")
    sel.add_argument("--top-n", type=int, default=3)

    rec = sub.add_parser(
        "reconcile",
        help="Pair the generator's calculated duties with catalogue suggestions for review",
    )
    rec.add_argument("--sizing", required=True,
                     help="Preliminary sizing JSON, or - for stdin; uses its valve_capacities")
    rec.add_argument("--schedule", help="Valve schedule CSV, for loop, material and bore")
    rec.add_argument("--decisions",
                     help="Previous decisions JSON, carried forward where the duty is unchanged")
    rec.add_argument("--top-n", type=int, default=3)

    sub.add_parser("schema", help="Show the categories, subtypes and brands available")

    e = sub.add_parser("explain", help="Explain a property or category")
    e.add_argument("--property", dest="property_name")
    e.add_argument("--category")

    a = sub.add_parser("assist", help="Hybrid AI request parser and matcher")
    a.add_argument("--query", required=True)
    a.add_argument("--mode", default="hybrid", choices=["local", "remote", "hybrid"])

    s = sub.add_parser("serve", help="Run web interface and JSON API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--api-key", default=None, help="Optional API key required on X-API-Key header")
    s.add_argument("--rate-limit-per-minute", type=int, default=None, help="Per-client requests/minute for API")

    b = sub.add_parser("build-catalog", help="Build packaged catalog from vendor CSV sources")
    b.add_argument("--source-dir", default="src/datacenter_equipment_finder/data/vendors")
    b.add_argument("--output-file", default="src/datacenter_equipment_finder/data/equipment_catalog.csv")

    sc = sub.add_parser("sync-catalogs", help="Download catalog/datasheet files from catalog URLs")
    sc.add_argument("--csv-path", default="src/datacenter_equipment_finder/data/equipment_catalog.csv")
    sc.add_argument("--output-dir", default="src/datacenter_equipment_finder/data/catalog_downloads")
    sc.add_argument("--limit", type=int, default=None)

    db = sub.add_parser("build-db", help="Build SQLite database from catalog CSV")
    db.add_argument("--csv-path", default="src/datacenter_equipment_finder/data/equipment_catalog.csv")
    db.add_argument("--db-path", default="src/datacenter_equipment_finder/data/equipment_catalog.sqlite")

    pdf = sub.add_parser("build-db-from-pdf", help="Extract catalog rows from PDF and build CSV/SQLite output")
    pdf.add_argument("pdf_path")
    pdf.add_argument("--db-path", required=True)
    pdf.add_argument("--csv-path", default=None)
    pdf.add_argument("--max-pages", type=int, default=None)
    pdf.add_argument("--timeout", type=int, default=None,
                     help="Seconds to wait for the local model (default 600, or DCEF_PDF_AI_TIMEOUT_SECONDS)")
    pdf.add_argument("--strict", action="store_true",
                     help="Fail if any extracted row is unusable, instead of keeping the good ones")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "find":
        service = EquipmentService.default()
        schema = service.schema()
        for value, field, valid in (
            (args.category, "category", schema["categories"]),
            (args.brand, "brand", schema["brands"]),
        ):
            if value and value.lower() not in {v.lower() for v in valid}:
                print(f"Unknown {field} {value!r}. Available: {', '.join(valid)}")
                return 2
        if args.component_subtype:
            subtypes = sorted({s for group in schema["subtypes_by_category"].values() for s in group})
            if args.component_subtype.lower() not in {v.lower() for v in subtypes}:
                print(
                    f"Unknown component subtype {args.component_subtype!r}. "
                    f"Available: {', '.join(subtypes)}"
                )
                return 2
        if (args.cv is not None or args.kv is not None) and (args.category or "").lower() in {"cdu", "chiller", "filter_dryer"}:
            parser.error(f"--cv/--kv are not applicable for category '{args.category}'")
        catalog = EquipmentCatalog.from_csv()
        matches = find_closest_components(
            catalog.components,
            category=args.category,
            component_subtype=args.component_subtype,
            brand=args.brand,
            target_size_mm=args.size_mm,
            target_cv=args.cv,
            target_kv=args.kv,
            target_capacity_kw=args.capacity_kw,
            target_capacity_tons=args.capacity_tons,
            target_connection_size_mm=args.connection_size_mm,
            target_connection_size_inch=args.connection_size_inch,
            required_pressure_bar=args.required_pressure_bar,
            required_temperature_c=args.required_temperature_c,
            top_n=args.top_n,
        )
        if not matches:
            limits = []
            if args.required_pressure_bar is not None:
                limits.append(f"{args.required_pressure_bar:g} bar")
            if args.required_temperature_c is not None:
                limits.append(f"{args.required_temperature_c:g} C")
            detail = f" rated for {' and '.join(limits)}" if limits else ""
            print(f"No catalog component matches this request{detail}.")
            return 1
        for i, m in enumerate(matches, start=1):
            c = m.component
            print(
                f"{i}. {c.part_number} | {c.brand} {c.category} | size_mm={c.nominal_size_mm} "
                f"| coeff={c.flow_coefficient_type}:{c.flow_coefficient_value} | cap_kw={c.capacity_kw} "
                f"| conn={c.connection_type} | material={c.material} | score={m.score:.4f}"
            )
            for warning in m.warnings:
                print(f"     warning: {warning}")
        return 0

    if args.command == "select":
        if args.schedule:
            try:
                items = duties_from_valve_schedule(args.schedule)
            except (OSError, csv.Error) as exc:
                print(f"select failed: could not read the schedule ({exc})")
                return 2
            selection = EquipmentService.default().select_for_duty(items, top_n=args.top_n)
            print(json.dumps(selection, indent=2))
            return 1 if selection["unresolved"] else 0

        raw = sys.stdin.read() if args.duty == "-" else Path(args.duty).read_text(encoding="utf-8")
        try:
            spec = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"select failed: duty spec is not valid JSON ({exc})")
            return 2
        parsed_items = spec.get("items") if isinstance(spec, dict) else spec
        if not isinstance(parsed_items, list):
            print("select failed: expected a JSON list of duty items, or an object with an 'items' list")
            return 2
        selection = EquipmentService.default().select_for_duty(parsed_items, top_n=args.top_n)
        print(json.dumps(selection, indent=2))
        return 1 if selection["unresolved"] else 0

    if args.command == "reconcile":
        raw = sys.stdin.read() if args.sizing == "-" else Path(args.sizing).read_text(encoding="utf-8")
        try:
            sizing = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"reconcile failed: sizing JSON is not valid ({exc})")
            return 2
        capacities = sizing.get("valve_capacities") if isinstance(sizing, dict) else sizing
        if not isinstance(capacities, list):
            print("reconcile failed: expected a 'valve_capacities' list in the sizing JSON")
            return 2

        schedule_rows = None
        if args.schedule:
            with Path(args.schedule).open("r", encoding="utf-8", newline="") as handle:
                schedule_rows = list(csv.DictReader(handle))

        duties = duties_from_sizing(capacities, schedule_rows)
        previous = None
        if args.decisions:
            previous = json.loads(Path(args.decisions).read_text(encoding="utf-8"))
        service = EquipmentService.default()
        reconciliation = reconcile(
            duties, service.select_for_duty(duties, top_n=args.top_n), previous
        )
        print(json.dumps(reconciliation, indent=2))
        return 1 if reconciliation["needs_external_sourcing"] else 0

    if args.command == "schema":
        schema = EquipmentService.default().schema()
        print("categories:")
        for category in schema["categories"]:
            subtypes = schema["subtypes_by_category"].get(category, [])
            hints = schema["input_hints"].get(category, [])
            print(f"  {category}")
            if subtypes:
                print(f"    subtypes: {', '.join(subtypes)}")
            if hints:
                print(f"    select on: {', '.join(hints)}")
        print(f"\nbrands: {', '.join(schema['brands'])}")
        print(f"\nduty limits: {', '.join(schema['duty_limits'])}")
        return 0

    if args.command == "compat":
        catalog = EquipmentCatalog.from_csv()
        selected = [
            c for c in catalog.components if c.part_number.lower() in {p.lower() for p in args.part_numbers}
        ]
        report = check_compatibility(
            selected,
            max_install_connection_time_min=args.max_connection_time,
            required_material=args.required_material,
            required_connection_standard=args.required_connection_standard,
            required_coolant=args.required_coolant,
            required_pressure_bar=args.required_pressure_bar,
            required_temperature_c=args.required_temperature_c,
        )
        missing = {p.lower() for p in args.part_numbers} - {c.part_number.lower() for c in selected}
        for part in sorted(missing):
            print(f"! not in catalog: {part}")
        print(f"compatible={report.is_compatible}")
        for reason in report.reasons:
            print(f"- {reason}")
        for note in report.notes:
            print(f"  note: {note}")
        return 0 if report.is_compatible and not missing else 1

    if args.command == "explain":
        if args.property_name:
            print(explain_property(args.property_name))
        elif args.category:
            print(explain_category(args.category))
        else:
            parser.error("Provide --property or --category")
        return 0

    if args.command == "assist":
        result = run_assistant_query(
            args.query,
            EquipmentService.default(),
            mode=args.mode,
        )
        filters = {
            key: value
            for key, value in result["filters"].items()
            if value not in (None, "", []) and key != "checks"
        }
        print("interpreted as: " + ", ".join(f"{k}={v}" for k, v in filters.items()))
        for check in result["checks"]:
            print(f"  note: {check}")
        if not result["matches"]:
            print("no matching component")
            return 1
        print()
        for i, match in enumerate(result["matches"], start=1):
            c = match["component"]
            print(
                f"{i}. {c['part_number']} | {c['brand']} {c['category']} "
                f"| size_mm={c['nominal_size_mm']} "
                f"| coeff={c['flow_coefficient_type']}:{c['flow_coefficient_value']} "
                f"| cap_kw={c['capacity_kw']} | score={match['score']:.4f}"
            )
            for warning in match.get("warnings", []):
                print(f"     warning: {warning}")
        return 0

    if args.command == "serve":
        run_server(
            host=args.host,
            port=args.port,
            api_key=args.api_key,
            rate_limit_per_minute=args.rate_limit_per_minute,
        )
        return 0

    if args.command == "build-catalog":
        errors = build_catalog_from_vendor_sources(args.source_dir, args.output_file)
        if errors:
            print("Catalog validation failed:")
            for err in errors:
                print(f"- {err}")
            return 2
        print(f"Catalog built: {args.output_file}")
        return 0

    if args.command == "sync-catalogs":
        summary = download_catalogs(args.csv_path, args.output_dir, limit=args.limit)
        for entry in summary["results"]:
            if entry["status"] == "downloaded":
                size_kb = entry["bytes"] / 1024
                print(f"  ok       {size_kb:8.0f} KB  {entry['url']}")
                if entry.get("warning"):
                    print(f"           warning: {entry['warning']}")
            elif entry["status"] == "skipped":
                print(f"  present            {entry['url']}")
            else:
                print(f"  FAILED   {entry.get('error', 'unknown error')}  {entry['url']}")
        print(
            f"\n{summary['downloaded']} downloaded, {summary['skipped']} already present, "
            f"{summary['failed']} failed, {summary['total']} total"
        )
        return 0 if summary["failed"] == 0 else 1

    if args.command == "build-db":
        count = build_sqlite_database(args.csv_path, args.db_path)
        print(f"Rows loaded into SQLite: {count}")
        return 0

    if args.command == "build-db-from-pdf":
        try:
            summary = build_database_from_pdf(
                args.pdf_path,
                args.db_path,
                csv_path=args.csv_path,
                max_pages=args.max_pages,
                strict=args.strict,
                config=(
                    replace(default_assistant_config(), pdf_timeout_seconds=args.timeout)
                    if args.timeout
                    else None
                ),
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"build-db-from-pdf failed: {exc}")
            return 2
        print(
            f"Extracted {summary['rows']} rows from {summary['pdf_path']}\n"
            f"  csv:    {summary['csv_path']}\n"
            f"  sqlite: {summary['sqlite_path']}\n"
            + (
                f"  {summary['rejected']} row(s) rejected, written to "
                f"{summary['rejected_path']}\n"
                if summary["rejected"]
                else ""
            ) +
            "Rows are marked unverified: a model extraction is not a checked "
            "transcription. Confirm them against the datasheet before use."
        )
        return 0

    return 1
