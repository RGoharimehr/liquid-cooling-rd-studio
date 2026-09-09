# Preliminary liquid-cooling sizing basis

Reviewed 2026-09-07. This is an implementation reference for **prescribed-flow preliminary sizing**. It describes methods and inputs; it is not evidence that every method is implemented or that a generated network has been balanced or commissioned.

## 1. Flow from liquid heat load

Use distinct variables for thermal power `P_heat` (W) and volumetric flow `Q` (m³/s).

```text
P_liquid_W = rack_electrical_power_W * liquid_fraction
Q_L_min = specific_flow_L_min_per_kW * P_liquid_W / 1000
Q_m3_s = Q_L_min / 60000

Alternative heat-balance basis:
Q_m3_s = P_heat_W / (rho_kg_m3 * cp_J_kg_K * delta_T_K)
Implied delta_T_K = P_heat_W / (rho_kg_m3 * cp_J_kg_K * Q_m3_s)
```

Offer **either** prescribed specific flow **or** heat-balance flow as the selected basis. If both specific flow and a temperature difference are supplied, report their consistency; do not silently combine incompatible inputs.

The [OCP OAI System Liquid Cooling Guidelines, March 2023, §1.3](https://www.opencompute.org/documents/oai-system-liquid-cooling-guidelines-in-ocp-template-mar-3-2023-update-pdf) give a PG25 example range of 1.25–2.0 L/min per kW and a typical target of 1.5 at approximately 10 K rise. That document concerns OAI equipment; this is an **example preset**, not a universal data-center requirement. The supplied ASHRAE chapter 6, §6.1.1, page 4 likewise uses 1.5 L/min per kW for a representative two-CPU PG25 system.

The [OCP Modular TCS planning white paper, Appendix B](https://www.opencompute.org/documents/ocp-wp-submittal-modular-tcs-at-cloudscale-design-delivery-selection-guidance-dlm1-docx-pdf) supports comparison of flow, fluid, temperature difference, and pipe dimensions. Its prose writes the heat equation in energy units; the implementation must use the **rate** form above with W and kg/s.

Aggregate downstream prescribed flows through rack, row, and pod collectors. Equal flow sharing across active parallel pumps/CDUs is a declared allocation assumption. Size an equipment branch for the selected duty case; do not divide by installed spare units when they are assumed isolated. Network-rack air loads and residual compute air loads do not automatically enter TCS heat.

FWS heat includes the declared load transferred through each CDU. For a water-cooled chiller, condenser heat also includes compressor input: with a supplied cooling COP, `P_condenser = P_evaporator * (1 + 1/COP)`. Pump heat and other loads require an explicit inclusion basis. Without compressor input/COP, evaporator heat alone is only a lower bound, so complete tower duty and CWS flow remain unresolved.

## 2. Pipe selection and pressure-loss screening

```text
D_required_m = sqrt(4 * Q_m3_s / (pi * velocity_limit_m_s))
v_m_s = 4 * Q_m3_s / (pi * selected_internal_diameter_m²)
Re = rho_kg_m3 * v_m_s * selected_internal_diameter_m / mu_Pa_s
delta_p_pipe_Pa = f_Darcy * (length_m / internal_diameter_m) * rho * v² / 2
delta_p_fitting_Pa = K * rho * v_reference² / 2
```

Select the smallest available **actual internal diameter** satisfying the selected velocity limit. Round upward through the chosen pipe/material catalogue, then recalculate velocity and fittings. Nominal size is not internal diameter. If no size fits, report catalogue exhaustion; never cap at the largest size and mark it passing.

The [ASHRAE 2025 Handbook—Fundamentals, chapter 22, Design Equations](https://handbook.ashrae.org/Handbooks/F25/SI/F25_Ch22/F25_Ch22_si.aspx) supports Darcy–Weisbach with Reynolds number, roughness, and Colebrook/Moody friction factors. It also distinguishes fitting coefficients and service/operating-hour velocity guidance. **Selected velocity caps, roughness allowances, generic fitting K values, and equipment pressure budgets remain declared project assumptions unless tied to a specific reviewed source and applicability.**

Use `f_Darcy = 64/Re` for fully developed laminar circular-pipe flow. The [ASHRAE 2025 Fluid Flow chapter](https://handbook.ashrae.org/Handbooks/F25/SI/F25_Ch03/F25_Ch03_si.aspx) describes `Re < 2300` as laminar and predictions between 2300 and 10000 as unreliable. Flag that range. A 4000 transition cutoff must not be presented as ASHRAE's threshold.

For turbulent screening, use Colebrook:

```text
1/sqrt(f_Darcy) = -2 * log10(epsilon/(3.7*D) + 2.51/(Re*sqrt(f_Darcy)))
```

A per-segment friction-factor iteration does not solve the network. If using the explicit Swamee–Jain approximation, identify the correlation and its applicability; its primary reference is [Swamee and Jain, 1976, pp. 657–664](https://doi.org/10.1061/JYCEAJ.0004542). Do not use a turbulent-only correlation for laminar flow or present a transition blend as a verified result.

Implementation requirements:

- Preserve each fitting coefficient's reference bore and flow direction, especially tee run/branch paths and reducers. A constant K across every size is an approximation.
- Count each loss once: explicit fitting K, equivalent length, or a vendor curve—not several simultaneously.
- Keep component curves/budgets separate from straight-pipe losses. Missing equipment loss is unknown, not zero.
- Handle zero prescribed flow without division by zero; report no-flow status. Reject nonpositive density, viscosity, bore, temperature difference, or required-flow velocity cap.
- Use temperature- and concentration-qualified fluid properties. [Dow's FLUIDFILE calculator](https://www.dow.com/en-us/market/mkt-building-construction/sub-build-heating-cooling-refrigeration/heat-transfer-fluids-calculators.html) explicitly distinguishes temperature, concentration, and concentration basis. Do not silently reuse a single PG25 property set after changing temperature or glycol fraction; require a reviewed property table or user-supplied values with provenance.

## 3. Pump duty estimate

```text
P_hydraulic_W = Q_m3_s * delta_p_pump_Pa
H_m = delta_p_pump_Pa / (rho_kg_m3 * 9.80665)
P_electrical_W = P_hydraulic_W / eta_wire_to_water
```

The distinction between head, pump performance curves, and efficiency is documented by [Grundfos, Pump Curves](https://www.grundfos.com/solutions/learn/research-and-insights/pump-curves) and [Grundfos, Basic Hydraulics](https://www.grundfos.com/ca/learn/ecademy/all-courses/basic-hydraulics-and-pump-performance/basic-hydraulics). Pump-only efficiency gives shaft power; it does not include motor/drive losses. Require `0 < efficiency <= 1` and label whether the supplied efficiency covers the complete electrical-to-fluid chain.

Derive a screening pressure budget from the most demanding complete supply/load/return path at the **prescribed** flows. Never sum every parallel branch's pressure loss. Enumerate valid circuit paths; do not find a path across a thermal coupling between fluids. A graph with unresolved flow allocation or equipment losses must report a partial estimate rather than a completed pump selection.

Closed TCS/FWS elevation rises are offset by descending return columns: do not add the sum of all riser elevations to circulating pump head. Static fill pressure is a separate input/check. An open cooling-tower circuit needs basin-to-distribution/nozzle elevation and discharge requirements. These distinctions are described by [ASHRAE, Hydronic Heating and Cooling, Closed Water Systems](https://handbook.ashrae.org/Handbooks/S16/IP/s16_ch13/s16_ch13_ip.aspx) and [ASHRAE, Centrifugal Pumps](https://handbook.ashrae.org/Handbooks/S20/IP/s20_ch44/s20_ch44_ip.aspx). Unknown tower static lift/nozzle requirements mean incomplete CWS pump duty.

Do not claim the estimate proves a pump operating point, balanced branch flows, NPSH margin, minimum-flow controls, or transient performance. Export the duty estimate and its assumptions for downstream simulation and vendor selection.

## 4. Valve Kv/Cv from allocated pressure drop

For the simplified single-phase liquid relation:

```text
Q_m3_h = 3600 * Q_m3_s
delta_p_bar = delta_p_Pa / 100000
SG = rho_fluid / rho_reference_water
Kv_required = Q_m3_h * sqrt(SG / allocated_delta_p_bar)
Cv_US_required ≈ 1.156 * Kv_required
```

[Spirax Sarco's valve-sizing sheet, page 5](https://content.spiraxsarco.com/-/media/spiraxsarco/international/documents/it/ti/en/5953_5954_7c-400-en.ashx?rev=464a50ced2484cd5bf79dafc5608b49e) provides the liquid Kv equation and highlights viscous-liquid corrections. The [DCV4 datasheet, page 4](https://content.spiraxsarco.com/-/media/spiraxsarco/international/documents/en/ti/dcv4-ti-p134-04-en.ashx?rev=f5642c16121e464785d2417ae1d93237) states the US/UK Cv conversions. Label **Cv (US)** explicitly. Record the reference-water density used for SG; `1000 kg/m³` is a convenient declared approximation.

The allocated valve pressure drop is a project input. It must be positive for nonzero flow. Do not calculate valve drop from a provisional Kv and then use that same drop as independent evidence supporting the selection. Avoid adding both the allocated valve drop and a separate generic K loss for the same valve.

Report **required effective Kv**, distinct from vendor full-open **Kvs**. A candidate catalogue Kvs at or above the required value is only a capacity shortlist; trim characteristic, opening position, authority, minimum-flow control, viscosity, cavitation/flashing limits, pressure rating, and materials still require vendor review. [Spirax Sarco's water-system sizing tutorial](https://www.spiraxsarco.com/learn-about-steam/control-hardware-electric-pneumatic-actuation/control-valve-sizing-for-water-systems) explains why system characteristics and valve authority matter.

## 5. Recommended interface wording and acceptance examples

| UI label | Meaning/status |
| --- | --- |
| Flow basis | Prescribed L/min per kW / heat-balance estimate / manual geometry |
| Specific coolant flow | Project input; optional OAI PG25 example preset |
| Calculated design flow | Prescribed flow allocation, not a solved operating flow |
| Velocity limit | Project criterion with cited guidance and applicability |
| Selected pipe / actual bore | Catalogue size rounded upward to the criterion |
| Pressure loss at prescribed flow | Preliminary pipe, fitting, and equipment breakdown |
| Pump duty estimate | Path pressure budget and approximate electrical input |
| Valve pressure allocation | User-assigned drop used to calculate required effective Kv |
| Vendor data required | A result cannot be completed from current inputs |
| Transition regime | Friction estimate is uncertain in the identified Reynolds range |

Use an independent numeric fixture for unit and formula tests. With **explicit test inputs**, not asserted operating properties: liquid heat 100 kW, ratio 1.5 L/min/kW, density 1000 kg/m³, viscosity 0.001 Pa·s, roughness 0.000045 m, bore 0.050 m, straight length 20 m, fitting K=3:

- Flow = 150 L/min = 0.0025 m³/s; at a 1.5 m/s cap, minimum bore = 0.04606589 m.
- Selected-bore velocity = 1.27323954 m/s; Re = 63661.97724.
- Colebrook Darcy factor = 0.02298248; straight loss = 7451.55721 Pa; fitting loss = 2431.70841 Pa. A different documented friction approximation should use a justified tolerance.
- Separately, an assigned 100000 Pa pump differential and 0.65 wire-to-water efficiency imply 384.61538 W electrical input.
- Separately, an assigned 0.1 bar valve differential with SG=1 implies required Kv = 28.46050 and Cv (US) ≈ 32.90034.

Also test zero flow; invalid fluid properties; unavailable catalogue sizes; laminar/transition/turbulent cases; doubled thermal load; independently sized pods; isolated spares; unknown equipment pressure drops; closed-loop elevation changes; open-tower lift; and valve losses counted exactly once. These checks verify the preliminary calculator, not installation performance.
