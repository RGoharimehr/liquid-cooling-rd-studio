PROPERTY_EXPLANATIONS = {
    "nominal_size_mm": "Nominal pipe size (NPS/DN equivalent) governs hydraulic diameter and expected flow velocity, pressure drop, and connector interoperability.",
    "flow_coefficient_value": "Cv/Kv quantifies valve/strainer conductance; larger values produce lower pressure drop at a given flow by Bernoulli-based flow relations.",
    "capacity_kw": "Cooling capacity in kW represents the sensible+latent heat removal rate and directly constrains thermal load support.",
    "capacity_tons": "Tons of refrigeration are a legacy capacity unit; 1 TR = 3.5168525 kW, commonly used in HVAC/chiller catalogs.",
    "connection_type": "Connection type (NPT/FPT/ODF/ODS/SW/BW) determines mechanical join method, leak integrity, and field serviceability.",
    "material": "Wetted material compatibility (e.g., stainless steel, copper alloys) affects corrosion, coolant chemistry stability, and lifetime reliability.",
    "pressure_rating_bar": "Maximum working pressure rating bounds safe operation and must exceed system design pressure with engineering margin.",
    "install_connection_time_min": "Estimated connection time captures installation complexity and affects deployment window and service downtime planning.",
    "max_temperature_c": "Maximum fluid temperature bounds the coolant operating envelope; elastomer seals such as EPDM usually set this limit, not the metal body.",
    "verification_status": "\"verified\" means every figure in the row was read from the cited vendor document. \"unverified\" means the row has not been checked against a source. \"disputed\" means it was checked and the vendor literature does not support it.",
    "estimated_price_usd": "Estimated price is optional market guidance; many industrial components require quote-based pricing rather than public list prices.",
}

COMPONENT_EXPLANATIONS = {
    "valve": "Valves regulate or isolate flow in refrigeration or liquid-cooling loops; selection is driven by size, Cv/Kv, pressure class, and connection standard.",
    "strainer": "Strainers protect pumps/valves and microchannel exchangers by trapping particles; Kv and mesh geometry control filtration vs pressure loss tradeoff.",
    "filter_dryer": "Filter-dryers remove moisture, acids, and debris from refrigerant loops; proper sizing avoids excess pressure drop while preserving contaminant capture.",
    "cdu": "A Coolant Distribution Unit (CDU) hydraulically decouples facility and IT coolant loops, providing pump control, heat exchange, and monitoring.",
    "quick_disconnect": "Universal Quick Disconnects (UQD/UQDB) are dry-break couplings that join server cold plates and manifolds to the rack loop; Cv sets the pressure drop per connection, and OCP UQD sizing (UQD02-UQD10) governs interoperability between vendors.",
    "chiller": "Chillers reject data-center heat to ambient/water loops and deliver controlled supply temperature; capacity and lift drive efficiency and operating envelope.",
}

BASELINE_REFERENCES = {
    "ocp": "OCP liquid-cooling guidance emphasizes interoperable manifolds, quality monitoring, and operational safety for high-density compute.",
    "uqd": "The OCP Universal Quick Disconnect specification defines interchangeable coupling sizes (UQD02-UQD10) so cold plates, manifolds, and CDUs from different vendors can be mixed without custom fittings.",
    "ashrae": "ASHRAE TC 9.9 thermal guidance defines allowable/recommended environmental envelopes and best practices for data-center cooling design.",
}


def explain_property(name: str) -> str:
    return PROPERTY_EXPLANATIONS.get(name, "No explanation available for this property.")


def explain_category(category: str) -> str:
    return COMPONENT_EXPLANATIONS.get(category.lower(), "No explanation available for this category.")
