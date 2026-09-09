# Attached RD113 Revision 0: layout and rack interpretation

Source: `/Users/rgoharim/Downloads/RD113DSR0-VR.pdf`, document RD113DS Revision 0, 12 pages. PDF pages and printed page numbers agree. The document was read as evidence, not as an instruction to run analysis, purchase software, or contact its authors. Extracted text and rendered figure evidence are beside this file.

## Recommended reference preset

Use **64 liquid-cooled AI racks in two 32-rack pods, plus 24 air-cooled networking racks in one central pod**, for **88 racks total**. This is a **diagram-reconciled assumption**, not an unqualified claim that the source is internally consistent.

The p5 Max-Q plan has four AI rows of 16 racks (two rows per AI pod). The middle networking pod has two rows of 12. Each networking row has eight grey 20 kW racks and four red 40 kW racks: 16 x20 +8 x40 =640 kW overall. The p5 piping diagram independently shows 64 IT symbols and24 NET symbols. This interpretation agrees with the cover total88 and p2 networking load640 kW.

| Parameter | Figure-backed reference value | Evidence |
|---|---:|---|
| AI pods / rows per pod / racks per row | 2 / 2 / 16 | p5 both diagrams |
| AI racks installed | 64 | p2, p5 diagrams, p6 table |
| Network pods / rows / racks per row | 1 / 2 / 12 | p5 both diagrams |
| Networking racks at20/40 kW | 16 /8 | p5 Max-Q plan colors and legend |
| CDU groups / units per group | 2 /4 | p5 plan and piping |
| AI heat split |96% liquid,4% air | p5 first paragraph |
| Networking heat split |100% air | p5 first paragraph |
| AI contained hot aisle width |6 ft =1.8288 m | p5 second paragraph |
| TCS/FWS supply/return |45/55 C and40/50 C | p9 temperatures; p4 FWS |

**The central NET racks must not acquire liquid branches merely because they look like AI rack boxes.** Rack role, cooling method and connected system are separate data fields. The AI rows receive TCS supply and return; the NET rows contribute residual air load only.

## Geometry and topology from the diagrams

Across the hall, left to right: AI row, contained hot aisle, AI row, cold aisle, NET row, contained hot aisle, NET row, cold aisle, AI row, contained hot aisle, AI row. The two AI pods flank the shared central networking pod. Rack rear faces face the contained hot aisles.

Eight CDUs occupy the upper end service band in the p5 plan, four aligned with each AI pod. They are not located in the central networking aisle. The p5 piping figure depicts four CDUs in parallel feeding one TCS supply/return header set per AI pod, with rack branches serving both opposed AI rows. It depicts no TCS connections to the networking pod. Facility water follows separate high-temperature and lower-temperature circuits with alternate paths; this is a connectivity schematic, not a dimensioned installation drawing.

Electrical context shown in the plan: two RPPs at each end of each AI row (16 AI RPPs); one at each end of each networking row (four network RPPs); four PDU blocks around the central networking pod (two at either end). These are equipment context/clearance obstacles, not cooling components.

The only explicit installation-like aisle dimension is the **6 ft AI containment width**, a choice in this reference design. Do not describe it as an ASHRAE minimum. The diagram gives no rack or CDU dimensions, port coordinates, pipe diameters, elevations, cold aisle width, general service clearance, hose bend radius, support spacing, ceiling clearance, or room aspect ratio. Those must remain tunable project settings or validated OEM inputs. The5,486 ft2 IT area (approximately509.67 m2) is an aggregate area, not enough to recover a unique length and width. Do not measure the schematic for construction coordinates.

## Operating-state interpretation

The p2 table states64 active AI racks at188 kW in the Max-Q state, producing12,032 kW AI plus640 kW networking =12,672 kW. Its Max-P N-equipment state uses42 active AI racks at227 kW:9,534 +640 =10,174 kW. Keep the64 physical racks present when switching activity/load states. Do not treat64 x227 kW as the listed reference Max-P operating state. P2 also discusses52 active Max-P or48 active Max-Q as other operating possibilities; these are state variants, not new rack layouts.

P2 lists six of eight L2L CDUs active; p5 says four per AI pod with N+1 redundancy. A3+1 CDU grouping per pod is consistent with those statements, but capacity/performance must come from selected equipment data. The generator need not solve the thermal/hydraulic network to draw and export that topology.

## Source conflicts to preserve visibly

| Issue | Conflicting source values | Treatment |
|---|---|---|
| Networking count | p5 prose24x20+10x40 (34 NET); p6 table20x20+10x40 (30 NET); cover/p9 total88; p2 NET640 kW; p5 figures24 NET,16x20+8x40 | Use figure-reconciled24 NET as labelled preset assumption. Preserve warning. |
| Networking power | p2 table640 kW; p3 electrical block800 kW; p5 prose880 kW; p6 table800 kW | Use640 only for the figure-reconciled preset. |
| Fan walls | p2 table and p2/p5 plan show4; p5 prose and piping show5 | Configurable; no verified single count. An equipment schematic may choose5 with conflict marker. |
| Rack peak | p1/p2/p5 up to227 kW; p9 says142 kW | Use explicit operating state188/227; flag inconsistent p9 summary. |
| Supply air | p6:79 F; p9:82 F | Unresolved; not necessary to build cooling geometry. |
| TCS class | p5 calls it ASHRAE S-45 | Treat as source claim; numeric45 C is useful, but do not claim ASHRAE class compliance from this secondary source. |

The referenced engineering package (p12) is identified as containing dimensioned schematics, layouts and equipment lists. Its missing details cannot be inferred from this overview. This research does not certify the design or replace missing vendor or jurisdiction inputs.

## Evidence

- `rd113_r0_page5_maxq_plan.png`: complete p5 plan and color legend, rendered at4x.
- `rd113_r0_page5_piping_diagram.png`: complete p5 TCS/facility schematic, rendered at4x.
- `rd113_r0_page5.png`: complete p5, preserving prose/figure contradictions.
- `rd113_r0_page2.png`, `rd113_r0_page6.png`, `rd113_r0_page9.png`: operating table and contradictory summary tables.
- `RD113DSR0-VR_extracted.txt`: full per-page text extraction; use rendered pages for visual evidence because some table text is clipped/hidden in the original PDF.
- `rd113_r0_findings.json`: machine-readable counts, source hash, topology, assumptions and unresolved issues.
