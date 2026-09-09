"""Deterministic, dependency-free exports from the routed hydraulic graph.

The SVG symbols are project-defined conceptual process symbols; they are not a
claim of compliance with a licensed P&ID standard. PCF is a generic draft for
review, and the Flownex JSON is a neutral mapping specification, not a native
Flownex project. Every omission from PCF is recorded in the geometry manifest.
"""

from __future__ import annotations

from collections import defaultdict
import csv
import html
import json
import math
from pathlib import Path
import re
from typing import Any


VALVE_KINDS = {"isolation_valve", "balancing_valve", "check_valve"}
PCF_TYPES = {
    "pipe": "PIPE", "isolation_valve": "VALVE", "balancing_valve": "VALVE",
    "check_valve": "VALVE", "tee": "TEE", "elbow": "ELBOW",
    "reducer": "REDUCER-CONCENTRIC",
    **{k: "MISC-COMPONENT" for k in ("quick_disconnect","flex_connector","rack_load","rack_manifold","pump","cdu_primary","cdu_secondary","strainer","air_separator","expansion_tank")},
}
COLORS = {"TCS": "#176c9c", "FWS": "#98711b"}

PCF_TYPES.update({'air_unit':'MISC-COMPONENT','control_valve':'VALVE','compute_rack':'MISC-COMPONENT','equipment_interface':'MISC-COMPONENT','chiller':'MISC-COMPONENT','cooling_tower':'MISC-COMPONENT'})


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _safe(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "unassigned"


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _scalar(value: Any) -> str | int | float:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: _scalar(row.get(k)) for k in fields} for row in rows)


def _edge_index(graph: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for edge in graph.get("edges", []):
        grouped[edge["component_id"]].append(edge)
    return grouped


def _sizes(component: dict, edges: list[dict], key: str = "nominal_size_in") -> list[float]:
    values = {float(e[key]) for e in edges if e.get(key) is not None}
    if component.get(key) is not None:
        values.add(float(component[key]))
    if key == "nominal_size_in":
        for mapping_key in ("port_sizes_in", "port_nominal_size_in"):
            values.update(float(v) for v in component.get(mapping_key, {}).values())
    return sorted(values)


def _size_label(component: dict, edges: list[dict]) -> str:
    values = _sizes(component, edges)
    return " × ".join(f"{v:g}" for v in values) + " in nominal" if values else "size not assigned"


def _maximum_port_flow(edges: list[dict], key: str = "flow_m3_s") -> float:
    """A tee's common-port flow is the sum of its two internal edge flows."""
    balance: dict[str, float] = defaultdict(float)
    for edge in edges:
        flow = float(edge.get(key, 0))
        balance[edge["from_node"]] -= flow
        balance[edge["to_node"]] += flow
    return max((abs(q) for q in balance.values()), default=0)


def _component_row(component: dict, edges: list[dict]) -> dict:
    """One BOM row per physical object, irrespective of internal edge count."""
    sizes = _sizes(component, edges)
    materials = sorted({str(e["material"]) for e in edges if e.get("material")})
    if component.get("material"):
        materials = sorted(set(materials) | {str(component["material"])})
    return {
        "component_id": component["id"], "tag": component.get("tag", component["id"]),
        "type": component.get("kind", "unknown"), "size_nominal_in": " x ".join(f"{v:g}" for v in sizes),
        "quantity_each": 1, "service": component.get("service", ""),
        "level": component.get("level", ""), "row": component.get("row", ""),
        "rack": component.get("rack", ""), "cdu": component.get("cdu", ""),
        "material": "; ".join(materials),
        "pipe_centerline_length_m": sum(float(e.get("length_m", 0)) for e in edges) if component.get("kind") == "pipe" else "",
        "internal_hydraulic_length_m": sum(float(e.get("length_m", 0)) for e in edges),
        "flow_m3_s": _maximum_port_flow(edges),
        "design_flow_m3_s": max((abs(float(e.get("design_flow_m3_s", 0))) for e in edges), default=0),
        "dp_Pa": max((float(e.get("dp_Pa", 0)) for e in edges), default=0),
        "K": "; ".join(f"{float(e['K']):g}" for e in edges if e.get("K") is not None),
        "K_reference_id_m": "; ".join(f"{float(e['K_reference_id_m']):g}" for e in edges if e.get("K_reference_id_m") is not None),
        "hydraulic_result_basis": "; ".join(sorted({str(e.get("hydraulic_result_basis", "design_flow_m3_s")) for e in edges})),
        "ports_node_ids": "; ".join(map(str, component.get("ports", []))),
        "installation_attachment": bool(component.get("attachment")),
        "hydraulic_element": not component.get("attachment", False),
        "host_component": component.get("host_component", ""),
        "notes": "Physical item count; flow_m3_s is maximum port flow in all-online operation; design_flow_m3_s and dp_Pa are maximum internal-edge values, not sums of independent scenario maxima. " + str(component.get("notes", "")),
    }


def _emit_schedules(graph: dict, outdir: Path, edge_index: dict) -> dict:
    rows = [_component_row(c, edge_index.get(c["id"], [])) for c in graph.get("components", [])]
    fields = ["component_id", "tag", "type", "size_nominal_in", "quantity_each", "service", "level", "row", "rack", "cdu", "material", "installation_attachment", "hydraulic_element", "host_component", "pipe_centerline_length_m", "internal_hydraulic_length_m", "flow_m3_s", "design_flow_m3_s", "dp_Pa", "K", "K_reference_id_m", "hydraulic_result_basis", "ports_node_ids", "notes"]
    _csv(outdir / "BOM.csv", fields, rows)
    valves = [r for r in rows if r["type"] in VALVE_KINDS]
    by_id = {c["id"]: c for c in graph["components"]}
    for row in valves:
        component = by_id[row["component_id"]]
        closed_in = [s["name"] for s in graph.get("scenarios", []) if component["id"] in s.get("closed_components", [])]
        row["normal_position"] = component.get("normal_position", "Automatic nonreturn" if component["kind"] == "check_valve" else "ASSUMPTION: open or balanced in normal online operation")
        row["closed_in_scenarios"] = "; ".join(closed_in)
        row["valve_Cv"] = component.get("Cv", "")
        row["vendor_selection_status"] = "Unselected; assumed K is not a manufacturer selection"
    _csv(outdir / "valve_schedule.csv", fields + ["normal_position", "closed_in_scenarios", "valve_Cv", "vendor_selection_status"], valves)
    grouped: dict[tuple, dict] = {}
    for row in rows:
        key = tuple(row[k] for k in ("type", "size_nominal_in", "service", "material"))
        if key not in grouped:
            grouped[key] = {k: row[k] for k in ("type", "size_nominal_in", "service", "material")}
            grouped[key].update(quantity_each=0, total_pipe_centerline_length_m=0.0, tags=[])
        item = grouped[key]
        item["quantity_each"] += 1
        item["total_pipe_centerline_length_m"] += float(row["pipe_centerline_length_m"] or 0)
        item["tags"].append(row["tag"])
    totals = [{**v, "tags": "; ".join(v["tags"])} for _, v in sorted(grouped.items())]
    _csv(outdir / "BOM_summary.csv", ["type", "size_nominal_in", "service", "material", "quantity_each", "total_pipe_centerline_length_m", "tags"], totals)
    return {"bom": "BOM.csv", "bom_summary": "BOM_summary.csv", "valve_schedule": "valve_schedule.csv", "physical_component_count": len(rows), "valve_count": len(valves)}


def _group_name(component: dict) -> str:
    if component.get("schematic_group"):
        return str(component["schematic_group"])
    service = component.get("service", "system")
    if component.get("rack") is not None:
        return f"{service}_row_{component.get('row', '?')}_rack_{component['rack']}"
    if component.get("cdu") is not None:
        return f"{service}_CDU_{component['cdu']}"
    if component.get("row") is not None:
        return f"{service}_row_{component['row']}"
    return f"{service}_{component.get('level', 'distribution')}"


def _component_roles(component: dict, edges: list[dict]) -> tuple[set[str], set[str]]:
    incoming = {e["from_node"] for e in edges}
    outgoing = {e["to_node"] for e in edges}
    if not incoming and not outgoing:
        ports = component.get("ports", [])
        incoming.update(ports[:1])
        outgoing.update(ports[1:])
    return incoming, outgoing


def _layout(ids: list[str], connections: list[tuple[str, str, str]]) -> dict[str, tuple[float, float]]:
    """Deterministic layered topology layout; back edges remain visible."""
    parents: dict[str, set[str]] = {i: set() for i in ids}
    children: dict[str, set[str]] = {i: set() for i in ids}
    for a, b, _ in connections:
        if a != b:
            parents[b].add(a)
            children[a].add(b)
    remaining = set(ids)
    ranks = {i: 0 for i in ids}
    placed: set[str] = set()
    while remaining:
        available = sorted(i for i in remaining if not (parents[i] & remaining))
        # A closed cycle needs a drawing cut only; its connection is still drawn.
        if not available:
            available = [min(remaining)]
        for i in available:
            ranks[i] = max((ranks[p] + 1 for p in parents[i] & placed), default=0)
            remaining.remove(i)
            placed.add(i)
    layers: dict[int, list[str]] = defaultdict(list)
    for i in ids:
        layers[ranks[i]].append(i)
    order = {i: float(j) for values in layers.values() for j, i in enumerate(sorted(values))}
    for _ in range(4):
        for rank in sorted(layers):
            layers[rank].sort(key=lambda i: (sum(order[p] for p in parents[i]) / max(1, len(parents[i])) if parents[i] else order[i], i))
            order.update({i: float(j) for j, i in enumerate(layers[rank])})
    return {i: (260.0 + 265.0 * ranks[i], 190.0 + 195.0 * order[i]) for i in ids}


def _symbol(kind: str, x: float, y: float, color: str) -> str:
    """Conventional visual vocabulary, explicitly project-defined legend."""
    wrap = f'<g transform="translate({x:.1f},{y:.1f})" stroke="{color}" stroke-width="2" fill="white">'
    if kind in VALVE_KINDS:
        body = '<path d="M-31 0 H-20 M20 0 H31 M-20 -12 L20 12 V-12 L-20 12 Z"/>'
        if kind == "check_valve":
            body = '<path d="M-31 0 H-18 M18 0 H31 M-18 -12 L11 0 L-18 12 Z M15 -15 V15"/>'
        if kind == "balancing_valve":
            body += '<path d="M0 -2 V-23 M-9 -23 H9"/>'
    elif kind == "tee":
        body = '<path d="M-31 0 H31 M0 0 V25"/><circle r="4" fill="' + color + '"/>'
    elif kind == "elbow":
        body = '<path d="M-31 0 H-8 Q8 0 8 16 V24 M8 0 H31"/>'
    elif kind == "reducer":
        body = '<path d="M-31 0 H-23 M23 0 H31 M-23 -12 L23 -6 V6 L-23 12 Z"/>'
    elif kind == "pipe":
        body = '<path d="M-31 0 H31"/>'
    elif kind in {"cdu_primary", "cdu_secondary"}:
        body = '<rect x="-30" y="-22" width="60" height="44" rx="4"/><path d="M-22 12 L-8 -12 L8 12 L22 -12"/>'
    elif kind == "rack_load":
        body = '<rect x="-31" y="-22" width="62" height="44"/><path d="M-22 0 H-15 L-9 -10 L2 10 L11 -10 L18 0 H25"/>'
    elif kind == "rack_manifold":
        body = '<rect x="-29" y="-12" width="58" height="24"/><path d="M-16 12 V22 M0 12 V22 M16 12 V22"/>'
    elif kind == "pump":
        body = '<circle r="24"/><path d="M-12 -16 L18 0 L-12 16 Z M-31 0 H-24 M24 0 H31"/>'
    elif kind == "quick_disconnect":
        body = '<path d="M-31 0 H-8 M8 0 H31 M-8 -16 V16 M8 -16 V16 M-18 -9 H-8 M8 9 H18"/>'
    elif kind == "strainer":
        body = '<path d="M-31 0 H-20 M20 0 H31 M-20 -14 H20 V14 H-20 Z M-12 -10 L10 10 M-4 -10 L16 8 M-16 -4 L0 10"/>'
    elif kind == "boundary":
        body = '<path d="M-30 -17 H16 L31 0 L16 17 H-30 Z"/>'
    else:
        body = '<rect x="-30" y="-20" width="60" height="40" rx="4"/>'
    return wrap + body + "</g>"


def _svg_sheet(name: str, components: list[dict], edge_index: dict, node_sheets: dict[str, set[str]], component_sheets: dict[str, str], graph: dict) -> str:
    ids = [c["id"] for c in components]
    lookup = {c["id"]: c for c in components}
    producers: dict[str, set[str]] = defaultdict(set)
    consumers: dict[str, set[str]] = defaultdict(set)
    for component in components:
        ins, outs = _component_roles(component, edge_index.get(component["id"], []))
        for node in ins:
            consumers[node].add(component["id"])
        for node in outs:
            producers[node].add(component["id"])
    connections = sorted({(a, b, n) for n in producers for a in producers[n] for b in consumers.get(n, set()) if a != b})
    positions = _layout(ids, connections)
    width = max(1250, int(max((p[0] for p in positions.values()), default=0)) + 310)
    height = max(590, int(max((p[1] for p in positions.values()), default=0)) + 220)
    title = name.replace("_", " ")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
           f'<title id="title">{_esc(title)} — conceptual P&amp;ID</title>',
           '<desc id="description">Every symbol represents one graph component. Arrows follow hydraulic graph edges. Labeled off-sheet ports with identical node IDs are connected. Symbols are project-defined, not certified construction documentation.</desc>',
           '<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7Z" fill="#465a6c"/></marker></defs>',
           '<style>text{font-family:Arial,Helvetica,sans-serif;fill:#213442}.title{font-size:23px;font-weight:700}.sub{font-size:12px;fill:#536879}.tag{font-size:13px;font-weight:700}.detail{font-size:10px;fill:#4c6474}.port{font-size:10px;fill:#5b6474}.wire{fill:none;stroke:#465a6c;stroke-width:1.7;marker-end:url(#arrow)}.halo{paint-order:stroke;stroke:white;stroke-width:5px;stroke-linejoin:round}</style>',
           f'<rect width="{width}" height="{height}" fill="white"/>',
           f'<rect width="{width}" height="103" fill="#edf3f5"/>',
           f'<text class="title" x="30" y="38">{_esc(title)}</text>',
           '<text class="sub" x="30" y="62">CONCEPTUAL P&amp;ID · Project-defined symbols · SI hydraulic values, nominal pipe sizes in inches</text>',
           '<text class="sub" x="30" y="82">Arrows and displayed flow: all CDUs online. Same-node off-sheet connectors are one hydraulic junction. See graph and schedule for N+1 isolation states.</text>']
    for index, (a, b, node) in enumerate(connections):
        ax, ay = positions[a]
        bx, by = positions[b]
        if bx > ax:
            mx = (ax + bx) / 2 + ((index % 3) - 1) * 8
            path = f"M{ax + 33:g},{ay:g} H{mx:g} V{by:g} H{bx - 35:g}"
            tx, ty = mx, min(ay, by) - 7
        else:
            rail = height - 116 + (index % 4) * 14
            path = f"M{ax + 33:g},{ay:g} H{ax + 77:g} V{rail:g} H{bx - 77:g} V{by:g} H{bx - 35:g}"
            tx, ty = (ax + bx) / 2, rail - 5
        out.append(f'<path class="wire" d="{path}"/>')
        out.append(f'<text class="port halo" text-anchor="middle" x="{tx:g}" y="{ty:g}">{_esc(node)}</text>')
    for component in components:
        cid = component["id"]
        x, y = positions[cid]
        edges = edge_index.get(cid, [])
        ins, outs = _component_roles(component, edges)
        color = COLORS.get(str(component.get("service", "")), "#405268")
        branch_edges = [e for e in edges if e.get("kind") == "tee_branch"]
        branch_nodes = set()
        if component.get("kind") == "tee" and branch_edges and len(component.get("ports", [])) == 3:
            branch_nodes.add(component["ports"][2])
        # Port stubs carry sheet references; all graph nodes survive partitioning.
        for direction, ports, locally_connected in ((-1, ins, producers), (1, outs, consumers)):
            stubs = [n for n in sorted(ports) if not (locally_connected.get(n, set()) - {cid}) or (node_sheets.get(n, set()) - {name})]
            for j, node in enumerate(stubs):
                refs = sorted(node_sheets.get(node, set()) - {name})
                label = ", ".join(refs) if refs else "graph boundary"
                shown = ", ".join(ref.split("_", 1)[0] for ref in refs) if refs else "boundary"
                if node in branch_nodes:
                    bx, by = x + 91, y + 104
                    path = f"M{x:g},{y + 25:g} H{bx:g} V{by:g}" if direction > 0 else f"M{bx:g},{by:g} V{y + 25:g} H{x:g}"
                    out.append(f'<path class="wire" d="{path}"/>')
                    out.append(f'<circle cx="{bx:g}" cy="{by:g}" r="3" fill="white" stroke="{color}"/>')
                    out.append(f'<text class="port halo" x="{bx + 8:g}" y="{by - 2:g}">{_esc(node)}</text>')
                    out.append(f'<text class="detail halo" x="{bx + 8:g}" y="{by + 13:g}"><title>{_esc(label)}</title>{_esc(shown)}</text>')
                    continue
                dy = (j - (len(stubs) - 1) / 2) * 35
                tip = x + direction * 108
                anchor = x + direction * 33
                start, end = ((tip, y + dy), (anchor, y)) if direction < 0 else ((anchor, y), (tip, y + dy))
                out.append(f'<path class="wire" d="M{start[0]:g},{start[1]:g} L{end[0]:g},{end[1]:g}"/>')
                out.append(f'<circle cx="{tip:g}" cy="{y + dy:g}" r="3" fill="white" stroke="{color}"/>')
                align = "end" if direction < 0 else "start"
                out.append(f'<text class="port halo" text-anchor="{align}" x="{tip:g}" y="{y + dy - 9:g}">{_esc(node)}</text>')
                # Full reference remains in title for long sheet names.
                out.append(f'<text class="detail halo" text-anchor="{align}" x="{tip:g}" y="{y + dy + 17:g}"><title>{_esc(label)}</title>{_esc(shown)}</text>')
        out.append(f'<g id="{_safe(cid)}"><title>{_esc(json.dumps(component, sort_keys=True))}</title>')
        out.append(_symbol(component.get("kind", "unknown"), x, y, color))
        out.append(f'<text class="tag halo" text-anchor="middle" x="{x:g}" y="{y - 39:g}">{_esc(component.get("tag", cid))}</text>')
        out.append(f'<text class="detail halo" text-anchor="middle" x="{x:g}" y="{y + 42:g}">{_esc(component.get("kind", "unknown").replace("_", " "))}</text>')
        out.append(f'<text class="detail halo" text-anchor="middle" x="{x:g}" y="{y + 57:g}">{_esc(_size_label(component, edges))}</text>')
        flow = _maximum_port_flow(edges)
        out.append(f'<text class="detail halo" text-anchor="middle" x="{x:g}" y="{y + 72:g}">{flow * 1000:.3f} L/s design · { _esc(component.get("service", ""))}</text></g>')
    out.append(f'<path d="M30 {height - 62} H{width - 30}" stroke="#cbd7de"/>')
    out.append(f'<text class="sub" x="30" y="{height - 40}">{len(components)} physical components · Symbol and connectivity coverage checked in pid_manifest.json · Lengths and elevations: geometry_network.json</text>')
    out.append(f'<text class="sub" x="30" y="{height - 21}">CDU primary/secondary exchange heat only; separate hydraulic ports are preserved. This sheet excludes detailed instrumentation, vents, drains and controls unless represented in the graph.</text>')
    out.append("</svg>\n")
    return "\n".join(out)


def _emit_pid(graph: dict, outdir: Path, edge_index: dict) -> dict:
    directory = outdir / "pid"
    directory.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[dict]] = defaultdict(list)
    for component in graph.get("components", []):
        # A P&ID shows the process, not hangers, braces or drip trays. Installation
        # attachments are carried in the BOM, geometry and IFC instead.
        if component.get("attachment"):
            continue
        groups[_group_name(component)].append(component)
    sheets: dict[str, list[dict]] = {}
    counter = 1
    for group, components in sorted(groups.items()):
        for start in range(0, len(components), 16):
            name = f"P{counter:03d}_{_safe(group)}"
            sheets[name] = components[start:start + 16]
            counter += 1
    component_sheets = {c["id"]: name for name, cs in sheets.items() for c in cs}
    node_sheets: dict[str, set[str]] = defaultdict(set)
    for name, components in sheets.items():
        for component in components:
            for node in component.get("ports", []):
                node_sheets[node].add(name)
    for name, components in sheets.items():
        (directory / f"{name}.svg").write_text(_svg_sheet(name, components, edge_index, node_sheets, component_sheets, graph), encoding="utf-8")
    coupling_filename = "P000_thermal_couplings.svg"
    coupling_height = max(390, 155 + 160 * len(graph.get("couplings", [])))
    couplings = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1300" height="{coupling_height}" viewBox="0 0 1300 {coupling_height}"><style>text{{font-family:Arial,Helvetica,sans-serif;fill:#213442}}</style><rect width="1300" height="{coupling_height}" fill="white"/><rect width="1300" height="92" fill="#edf3f5"/><text x="30" y="36" font-size="23" font-weight="700">P000 · CDU thermal couplings</text><text x="30" y="61" font-size="13">FWS primary and TCS secondary retain separate hydraulic ports. Dashed links transfer heat only.</text><text x="30" y="80" font-size="12">This is a thermal cross reference for the detailed component sheets. Capacity values retain their graph-defined basis.</text>']
    component_lookup = {c["id"]: c for c in graph.get("components", [])}
    for i, coupling in enumerate(graph.get("couplings", [])):
        y = 161 + i * 160
        left = component_lookup[coupling["primary_component"]]
        right = component_lookup[coupling["secondary_component"]]
        for x, component in ((280, left), (1010, right)):
            color = COLORS.get(component.get("service"), "#465a6c")
            couplings.append(_symbol(component["kind"], x, y, color))
            couplings.append(f'<text x="{x}" y="{y - 37}" font-size="14" text-anchor="middle" font-weight="700">{_esc(component["tag"])}</text>')
            couplings.append(f'<text x="{x}" y="{y + 43}" font-size="12" text-anchor="middle">{_esc(component["kind"].replace("_", " "))} · {_esc(component["service"])}</text>')
            sheet = component_sheets[component["id"]]
            couplings.append(f'<a href="{_esc(sheet)}.svg"><text x="{x}" y="{y + 63}" font-size="12" text-anchor="middle" fill="#176c9c">Detailed component sheet: {_esc(sheet.split("_", 1)[0])}</text></a>')
        couplings.append(f'<path d="M980 {y} H311" stroke="#aa7c1c" stroke-width="2" stroke-dasharray="8 5"/><path d="M312 {y} L323 {y - 6} V{y + 6} Z" fill="#aa7c1c"/>')
        heat_label = "All online: " if "scenario_heat_W" in coupling else "Graph heat: "
        couplings.append(f'<text x="645" y="{y - 13}" font-size="15" text-anchor="middle" font-weight="700">{_esc(coupling["id"])} · {heat_label}{float(coupling.get("heat_W", 0)) / 1000:,.3f} kW</text>')
        basis = coupling.get("heat_basis", "Heat transfer value from source graph")
        couplings.append(f'<text x="645" y="{y + 26}" font-size="11" text-anchor="middle">{_esc(basis)}</text>')
        if coupling.get("design_capacity_W") is not None:
            couplings.append(f'<text x="645" y="{y + 43}" font-size="12" text-anchor="middle">Installed N-duty capacity: {float(coupling["design_capacity_W"]) / 1000:,.3f} kW</text>')
    couplings.append(f'<text x="30" y="{coupling_height - 20}" font-size="12">Conceptual thermal mapping · No mass transfer between loops · Installed capacities are not summed as simultaneous operating loads</text></svg>')
    (directory / coupling_filename).write_text("\n".join(couplings), encoding="utf-8")
    coverage = [{"component_id": c["id"], "tag": c.get("tag", c["id"]), "sheet": "pid/" + component_sheets[c["id"]] + ".svg", "edge_ids": [e["id"] for e in edge_index.get(c["id"], [])]} for c in graph.get("components", []) if not c.get("attachment")]
    manifest = {
        "status": "Conceptual process schematic; project-defined symbology, not a certified construction P&ID",
        "component_count": len(coverage), "sheet_count": len(sheets),
        "excluded_installation_attachments": sum(1 for c in graph.get("components", []) if c.get("attachment")),
        "components": coverage,
        "off_sheet_nodes": {n: sorted(names) for n, names in sorted(node_sheets.items()) if len(names) > 1},
        "couplings": graph.get("couplings", []),
        "thermal_coupling_sheet": "pid/" + coupling_filename,
        "limitations": ["Symbols express topology and reference flow. Instrumentation, controls, pipe supports, vents and drains are present only if included in the source graph.", "Off-sheet labels may be abbreviated; hover labels or the manifest gives full sheet references.", "Isolation state depends on scenario; the drawing shows graph connectivity, not a control sequence."],
    }
    _write_json(outdir / "pid_manifest.json", manifest)
    rows = f'<tr><td><a target="sheet" href="{coupling_filename}">P000 CDU thermal couplings</a></td><td>{len(graph.get("couplings", []))} couplings</td><td>Heat exchange cross references; physical items appear in the detailed sheets below.</td></tr>'
    rows += "\n".join(f'<tr><td><a target="sheet" href="{_esc(name)}.svg">{_esc(name.replace("_", " "))}</a></td><td>{len(cs)}</td><td>{_esc(", ".join(c.get("tag", c["id"]) for c in cs))}</td></tr>' for name, cs in sheets.items())
    legend = "\n".join(f'<g transform="translate({(i % 4) * 260 + 60},{(i // 4) * 75 + 40})">{_symbol(kind, 0, 0, "#176c9c")}<text x="42" y="5" font-size="12">{_esc(kind.replace("_", " "))}</text></g>' for i, kind in enumerate(["pipe", "isolation_valve", "balancing_valve", "check_valve", "tee", "reducer", "elbow", "rack_manifold", "rack_load", "cdu_primary", "cdu_secondary", "boundary", "pump", "quick_disconnect", "strainer"]))
    document = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Liquid cooling conceptual P&amp;ID set</title><style>body{{font:15px system-ui,sans-serif;color:#213442;max-width:1400px;margin:32px auto;padding:0 24px}}h1{{font-size:30px}}p{{max-width:1000px;line-height:1.55}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:10px;border-bottom:1px solid #d5e0e6;text-align:left;vertical-align:top}}td:last-child{{max-width:700px;overflow-wrap:anywhere}}a{{color:#176c9c}}.note{{padding:16px;background:#edf3f5;border-left:4px solid #98711b}}svg{{max-width:100%;height:auto}}</style><h1>Liquid cooling · Conceptual P&amp;ID set</h1><p class="note">Generated solely from the routed hydraulic graph. {len(coverage)} tagged physical components across {len(sheets)} sheets. Arrows follow the reference hydraulic direction. The same node ID on multiple sheets denotes one shared junction. Open a sheet and use browser zoom to inspect it.</p><p>Project-defined process symbols are shown below. These drawings are for design development; they do not assert a certified P&amp;ID standard or construction readiness. CDU primary and secondary components are hydraulically isolated and linked only by the graph's heat couplings.</p><svg xmlns="http://www.w3.org/2000/svg" width="1100" height="315" viewBox="0 0 1100 315">{legend}</svg><p><a href="../pid_manifest.json">Component-to-sheet index and cross references</a> · <a href="../geometry_network.json">Complete geometry and connectivity</a> · <a href="../BOM.csv">BOM</a> · <a href="../valve_schedule.csv">Valve schedule</a></p><table><thead><tr><th>Sheet</th><th>Items</th><th>Component tags</th></tr></thead><tbody>{rows}</tbody></table></html>'''
    (directory / "index.html").write_text(document, encoding="utf-8")
    return {"pid_index": "pid/index.html", "pid_manifest": "pid_manifest.json", "pid_sheet_count": len(sheets), "pid_component_count": len(coverage), "pid_thermal_couplings": "pid/" + coupling_filename}


def _xyz(node: dict) -> list[float] | None:
    xyz = node.get("xyz_m")
    if not isinstance(xyz, (list, tuple)) or len(xyz) != 3:
        return None
    try:
        values = [float(v) for v in xyz]
    except (TypeError, ValueError):
        return None
    return values if all(math.isfinite(v) for v in values) else None


def _port_bore(component: dict, node_id: str, edges: list[dict]) -> float | None:
    direct = component.get("port_nominal_size_in", component.get("port_sizes_in", {}))
    if isinstance(direct, dict) and direct.get(node_id) is not None:
        return float(direct[node_id])
    values = [float(e["nominal_size_in"]) for e in edges if node_id in (e.get("from_node"), e.get("to_node")) and e.get("nominal_size_in") is not None]
    if values:
        return max(values)
    if component.get("nominal_size_in") is not None:
        return float(component["nominal_size_in"])
    return None


def _emit_geometry(graph: dict, outdir: Path, edge_index: dict) -> dict:
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    geometry = {
        "format": "liquid-cooling-neutral-geometry/2.0", "coordinate_unit": "m",
        "nominal_size_unit": "in", "outside_diameter_unit": "m",
        "nodes": graph.get("nodes", []), "components": graph.get("components", []),
        "edges": graph.get("edges", []), "couplings": graph.get("couplings", []),
        "metadata": graph.get("metadata", {}),
        "limitations": ["Centerline routing and hydraulic ports are represented; manufacturer envelopes, supports, access clearances and fabrication tolerances require detailed design.", "A tee is one physical component with multiple internal hydraulic edges; do not extrude its edges as duplicate tee fittings.", "This neutral JSON preserves every object even when its generic PCF mapping is unsupported."],
    }
    _write_json(outdir / "geometry_network.json", geometry)
    streams: dict[str, list[str]] = {}
    emitted: list[dict] = []
    skipped: list[dict] = []
    portable=[]
    for component in graph.get('components',[]):
        if component.get('service')=='EQUIPMENT' and len(component.get('ports',[]))>2:
            for i,e in enumerate(edge_index.get(component['id'],[]),1):
                portable.append({**component,'id':component['id']+':PATH'+str(i),'tag':component['tag']+':PATH'+str(i),
                    'kind':'equipment_interface','service':e['service'],'ports':[e['from_node'],e['to_node']],
                    'nominal_size_in':e['nominal_size_in'],'parent_equipment':component['id']})
        elif component.get('service')=='EQUIPMENT' and edge_index.get(component['id']):
            portable.append({**component,'service':edge_index[component['id']][0]['service']})
        else:portable.append(component)
    for component in portable:
        cid = component["id"]
        tag = component.get("tag", cid)
        kind = component.get("kind", "unknown")
        ports = component.get("ports", [])
        edges = edge_index.get(cid, [])
        reason = ""
        coordinates = [_xyz(nodes.get(p, {})) for p in ports]
        bores = [_port_bore(component, p, edges) for p in ports]
        if kind not in PCF_TYPES:
            reason = f"No portable generic PCF mapping for {kind}; retained in geometry_network.json."
        elif len(ports) != (3 if kind == "tee" else 2):
            reason = f"Expected {'three' if kind == 'tee' else 'two'} ports for {kind}; found {len(ports)}."
        elif any(x is None for x in coordinates):
            reason = "One or more port coordinates are missing or non-finite."
        elif any(b is None or b <= 0 for b in bores):
            reason = "One or more port nominal bores are missing or nonpositive."
        elif len({tuple(x) for x in coordinates if x is not None}) != len(coordinates):
            reason = "Coincident physical port positions; finite fabrication envelope is not defined."
        if reason:
            skipped.append({"component_id": cid, "tag": tag, "kind": kind, "reason": reason, "ports": ports})
            continue
        service = str(component.get("service", "system"))
        if service not in streams:
            streams[service] = ["UNITS-BORE INCH", "UNITS-CO-ORDS MM", "UNITS-WEIGHT KGS", "UNITS-BOLT-DIA MM", "UNITS-BOLT-LENGTH MM", "PIPELINE-REFERENCE " + _safe(service), "    PIPELINE-ATTRIBUTE1 DRAFT_GENERIC_NOT_IMPORTER_VALIDATED"]
        lines = [PCF_TYPES[kind], "    COMPONENT-IDENTIFIER " + _safe(cid), "    COMPONENT-ATTRIBUTE1 " + _safe(tag), "    COMPONENT-ATTRIBUTE2 " + _safe(kind), "    COMPONENT-ATTRIBUTE3 " + _safe(component.get("material", edges[0].get("material", "unspecified") if edges else "unspecified"))]
        # PCF uses nominal inch bores independently of millimetre coordinates (Hexagon PCF guide).
        for i, (point, bore) in enumerate(zip(coordinates, bores)):
            keyword = "BRANCH1-POINT" if kind == "tee" and i == 2 else "END-POINT"
            lines.append("    " + keyword + " " + " ".join(f"{v * 1000:.6f}" for v in point) + f" {bore:.6f}")
        if kind in {"tee", "elbow"}:
            center = component.get("center_xyz_m", component.get("center_m"))
            if center is None:
                # Declared geometric midpoint only, not a manufacturer's center.
                center = [(coordinates[0][j] + coordinates[1][j]) / 2 for j in range(3)]
            lines.append("    CENTRE-POINT " + " ".join(f"{float(v) * 1000:.6f}" for v in center))
            lines.append("    COMPONENT-ATTRIBUTE4 CENTERLINE_GEOMETRY_REQUIRES_FABRICATION_REVIEW")
        streams[service].extend(lines)
        emitted.append({"component_id": cid, "parent_component_id": component.get('parent_equipment',cid), "tag": tag, "pcf_type": PCF_TYPES[kind], "file": "network_" + _safe(service) + ".pcf", "port_nominal_bores_in": bores})
    files = []
    for service, lines in sorted(streams.items()):
        filename = "network_" + _safe(service) + ".pcf"
        (outdir / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
        files.append(filename)
    manifest = {
        "format": "generic PCF draft", "validation_status": "Not validated in a licensed PCF importer; not fabrication-ready",
        "source_component_count": len(graph.get("components", [])), "emitted_component_count": len(emitted),
        "omitted_component_count": len(skipped), "files": files, "emitted": emitted, "omitted": skipped,
        "complete_geometry_file": "geometry_network.json",
        "units": {"PCF_coordinates": "mm", "PCF_nominal_bores": "inches, commercial nominal size; not actual internal diameter", "neutral_geometry_coordinates": "m"},
        "limitations": ["Generic PCF has no validated vendor SKEY/library mapping, material catalogue, weld preparation, end-connection specification, support design or fabrication envelope.", "Inline equipment/manifolds use labelled MISC-COMPONENT placeholders to preserve endpoint continuity. These require target-library remapping. Non-fluid objects remain in IFC and JSON.", "Center points are geometric construction points unless supplied in the graph; fabrication centers and takeouts must be reviewed.", "Nominal bores are retained in inches (UNITS-BORE INCH), independent of millimetre coordinates. Pipe/tube catalogue mapping remains importer-specific.", "Reducers carry explicit graph port_sizes_in or port_nominal_size_in when supplied; edge-only fallback values may be identical at both ends."],
    }
    _write_json(outdir / "geometry_export_manifest.json", manifest)
    return {"geometry_network": "geometry_network.json", "geometry_manifest": "geometry_export_manifest.json", "pcf_files": files, "pcf_emitted_component_count": len(emitted), "pcf_omitted_component_count": len(skipped)}


def _emit_flownex(graph: dict, outdir: Path) -> dict:
    network = {
        "format": "liquid-cooling-neutral-simulation-network/1.0",
        "target": "Revit 2026 native add-in → official Flownex Revit Network Builder (SE 2025 Release 3); target validation pending",
        "native_project": False, "runnable_in_flownex": False,
        "units": {"coordinates": "m", "length": "m", "internal_diameter": "m", "flow": "m3/s", "pressure_drop": "Pa", "heat": "W", "temperature": "degC"},
        "nodes": graph.get("nodes", []), "physical_components": graph.get("components", []),
        "hydraulic_elements": graph.get("edges", []), "thermal_couplings": graph.get("couplings", []),
        "operating_scenarios": graph.get("scenarios", []), "hydraulic_results": graph.get("hydraulics", {}),
        "metadata": graph.get("metadata", {}), "provenance": graph.get("provenance", {}),
        "mapping_rules": {
            "pipe": "Map each edge once to a pipe element with routed length, ID and roughness.",
            "valve": "Map resistance to the selected valve element; manufacturer Cv/K-vs-position data supersede assumed K.",
            "tee": "Preserve one three-port physical tee; two internal edges are a hydraulic approximation, not two physical tee fittings. Review branch/run loss treatment.",
            "rack_load": "Map aggregated heat load and declared resistance; detailed cold-plate/parallel-distribution curves are absent unless supplied.",
            "cdu": "Keep primary and secondary networks hydraulically distinct; exchange only heat through thermal_couplings.",
            "direction": "from_node and to_node define reference flow; scenarios define active CDU/valve states.",
            "hydraulic_result_basis": "Top-level design_flow_m3_s and design-basis pressure/velocity results are independent per-edge design envelopes. They are not a simultaneous mass-conserving operating network. Use flow_m3_s with operating_results for all-online operation, or recompute the requested scenario from flow_basis and active CDU states.",
            "loss_reference": "Preserve K_reference_id_m when supplied; K is referenced to that bore's velocity head, which can differ from edge id_m at reducers.",
            "thermal_result_basis": "Coupling heat_W is the graph-declared operating heat; preserve design_capacity_W separately and apply scenario_heat_W for scenario heat transfer. Never sum independent installed CDU capacities as simultaneous operating heat.",
        },
        "missing_for_native_runnable_model": [
            "Installed Flownex version, licensed API/import specification, component library identifiers and an adapter validated in that version.",
            "Manufacturer CDU pump curves, control strategy, minimum flow, HX UA/effectiveness or performance map, and primary/secondary pressure-loss curves.",
            "Manufacturer rack/cold-plate/manifold pressure-drop-vs-flow curves and valve Cv/K-vs-position data.",
            "A validated fluid property correlation/table for the actual PG product and concentration convention over the simulated temperature range.",
            "Absolute pressure/reference boundary conditions, expansion vessel/pressurization details and operating controls for a solvable pressure network.",
            "Scenario-specific valve states, pump controls and load allocation mapped to native element controls; prescribed design flows are not a solved nonlinear network.",
        ],
    }
    _write_json(outdir / "flownex_network.json", network)
    return {"flownex_network": "flownex_network.json", "flownex_native_runnable": False}


def emit_all(graph: dict, outdir: Path, profile=None) -> dict:
    """Emit all graph-derived deliverables and return relative-file manifest.

    Raises ValueError if physical IDs/tags or endpoint references are invalid.
    Intentional geometry export gaps are reported rather than raised, because
    ideal hydraulic fittings can legitimately lack a fabrication envelope.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    components = graph.get("components", [])
    ids = [c["id"] for c in components]
    tags = [c.get("tag") for c in components]
    node_ids = {n["id"] for n in graph.get("nodes", [])}
    if len(ids) != len(set(ids)) or None in tags or "" in tags or len(tags) != len(set(tags)):
        raise ValueError("Emission requires unique component IDs and unique nonempty physical component tags")
    for component in components:
        if any(p not in node_ids for p in component.get("ports", [])):
            raise ValueError(f"Component {component['id']} references an unknown node")
    for edge in graph.get("edges", []):
        if edge.get("component_id") not in set(ids) or edge.get("from_node") not in node_ids or edge.get("to_node") not in node_ids:
            raise ValueError(f"Edge {edge.get('id')} references an unknown component or endpoint")
    edge_index = _edge_index(graph)
    manifest = {"source": "Single routed hydraulic graph", "status": "Engineering reference draft; not construction documentation"}
    manifest.update(_emit_schedules(graph, outdir, edge_index))
    manifest.update(_emit_geometry(graph, outdir, edge_index))
    manifest.update(_emit_pid(graph, outdir, edge_index))
    manifest.update(_emit_flownex(graph, outdir))
    from ifc4 import emit_ifc
    manifest.update(emit_ifc(graph, outdir, profile))
    from mesh import emit_mesh
    manifest.update(emit_mesh(graph, outdir))
    _write_json(outdir / "emission_manifest.json", manifest)
    return manifest
