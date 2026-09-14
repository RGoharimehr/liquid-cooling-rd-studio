"""Commercial pipe dimensions and the declared design flow for each circuit.

Flow is derived here once, from the configuration's own fluid properties and
selected flow basis, so the graph and `preliminary_sizing` cannot report two
different design flows for the same circuit. Pressure loss belongs to
`preliminary_sizing`; there is no network or pump solver anywhere in this
package.
"""
import math
# Commercial dimensions in inches. Copper Development Association Type L table;
# carbon steel ASME B36.10M Schedule 40 dimensions as reproduced by manufacturer.
COPPER = [(1,1.125,.050),(1.25,1.375,.055),(1.5,1.625,.060),(2,2.125,.070),
          (2.5,2.625,.080),(3,3.125,.090),(3.5,3.625,.100),(4,4.125,.110),
          (5,5.125,.125),(6,6.125,.140)]
STEEL = [(2,2.375,.154),(2.5,2.875,.203),(3,3.5,.216),(3.5,4,.226),
         (4,4.5,.237),(5,5.563,.258),(6,6.625,.280),(8,8.625,.322),
         (10,10.75,.365),(12,12.75,.406),(14,14,.438),
         (16,16,.500),(18,18,.562),(20,20,.594),(24,24,.688)]
# NPS 16–24 are cross-checked against Weldbend's Schedule 40 reducer
# dimensions (OD, ID and wall). These dimensions do not establish pressure rating.
STEEL_DIMENSION_SOURCE = 'https://weldbend.com/catalog.pdf'
# ASME B36.19M Schedule 10S stainless, the TCS header material CloudScale 3.4/3.5
# frames its erosion-corrosion and pipe-selection discussion around.
STAINLESS = [(1,1.315,.109),(1.25,1.66,.109),(1.5,1.9,.109),(2,2.375,.109),
             (2.5,2.875,.120),(3,3.5,.120),(3.5,4,.120),(4,4.5,.120),
             (5,5.563,.134),(6,6.625,.134),(8,8.625,.148),(10,10.75,.165),
             (12,12.75,.180),(14,14,.188),(16,16,.188)]
CATALOGUES = {'copper_type_l':(COPPER,'ASTM B88 Type L (CDA dimensions)'),
              'carbon_steel_sch40':(STEEL,'ASME B36.10M Schedule 40 (manufacturer dimensions)'),
              'stainless_sch10':(STAINLESS,'ASME B36.19M Schedule 10S')}


def _fluid(c, service):
    """Properties as entered for this design, never a hard-coded formulation."""
    prefix = service.lower()
    return (getattr(c, prefix + '_density_kg_m3'), getattr(c, prefix + '_specific_heat_J_kgK'),
            getattr(c, prefix + '_delta_K'))


def heat_flows(c):
    """Declared heat and volumetric flow per circuit, on the selected basis.

    TCS follows `flow_input_mode`: either a prescribed L/min per liquid kW, or
    the rate form of the heat equation at the entered temperature rise. FWS and
    CWS are always heat balance. `preliminary_sizing.evaluate` derives the same
    numbers the same way and the two are checked against each other.
    """
    from air_cooling import heat_ledger
    ledger = heat_ledger(c)
    heat_rack = c.rack_power_W * c.liquid_fraction
    heat_total = heat_rack * c.rows * c.racks_per_row
    duty_units = c.cdu_count - c.redundancy
    t_rho, t_cp, t_dK = _fluid(c, 'tcs')
    f_rho, f_cp, f_dK = _fluid(c, 'fws')
    if c.flow_input_mode == 'lpm_per_kw':
        tcs_total = heat_total / 1000. * c.flow_lpm_per_kw / 60000.
        basis = f'{c.flow_lpm_per_kw:g} L/min per liquid kW (prescribed)'
    else:
        tcs_total = heat_total / (t_rho * t_cp * t_dK)
        basis = f'heat balance at {t_dK:g} K rise'
    t_mass = tcs_total * t_rho
    fws_cdu_total = heat_total / (f_rho * f_cp * f_dK)
    plant_mass = ledger['chiller_W'] / (f_cp * f_dK)
    racks = c.rows * c.racks_per_row
    return {'rack_heat_W': heat_rack, 'row_heat_W': heat_rack * c.racks_per_row,
            'total_heat_W': heat_total, 'air_heat_W': ledger['air_W'], 'chiller_heat_W': ledger['chiller_W'],
            'cdu_duty_heat_W': heat_total / duty_units,
            'cdu_duty_basis': 'Hall liquid heat divided by installed minus requested simultaneous outages. '
                              'Independent cooling pods are allocated separately in preliminary_sizing.',
            'tcs_flow_basis': basis,
            'implied_tcs_delta_K': heat_total / (t_rho * t_cp * tcs_total) if tcs_total else None,
            'tcs_total_mass_kg_s': t_mass, 'tcs_total_m3_s': tcs_total,
            'fws_total_mass_kg_s': plant_mass, 'fws_total_m3_s': plant_mass / f_rho,
            'fws_cdu_total_m3_s': fws_cdu_total,
            'rack_mass_kg_s': t_mass / racks, 'rack_m3_s': tcs_total / racks,
            'row_mass_kg_s': t_mass / c.rows, 'row_m3_s': tcs_total / c.rows,
            'cdu_secondary_mass_kg_s': t_mass / duty_units,
            'cdu_secondary_m3_s': tcs_total / duty_units,
            'cdu_primary_mass_kg_s': fws_cdu_total * f_rho / duty_units,
            'cdu_primary_m3_s': fws_cdu_total / duty_units}


class NoCatalogueSize(ValueError):
    """A recoverable design limit with enough information to change inputs."""
    def __init__(self, flow, material, cap):
        table, standard = CATALOGUES[material]
        nominal, od, wall = table[-1]
        bore = (od - 2 * wall) * .0254
        maximum = math.pi * bore * bore / 4 * cap
        required = math.sqrt(4 * flow / (math.pi * cap))
        self.diagnostic = {
            'code': 'NO_CATALOGUE_SIZE', 'material': material,
            'flow_m3_s': flow, 'flow_L_min': flow * 60000,
            'velocity_cap_m_s': cap, 'required_id_m': required,
            'largest_supported_nominal_in': nominal, 'largest_supported_id_m': bore,
            'largest_supported_capacity_m3_s': maximum,
            'minimum_parallel_runs_at_largest_size': max(1, math.ceil(flow / maximum)),
            'actions': [
                'Check rack count, heat load and flow-per-kW or temperature-difference inputs for this circuit.',
                'Split the affected circuit into separately routed headers or cooling pods; adding CDUs alone does not reduce shared-main flow.',
                'Select a compatible pipe family with a larger supported bore, or extend the verified dimension catalogue.',
                'Only raise the velocity limit after the project material, erosion, noise and pressure-loss criteria have been reviewed.'],
            'scope': 'Preview retains the previous/manual bore for this family; it is not a valid sized pipe.'}
        super().__init__(f'{flow*60000:,.0f} L/min needs at least {required*1000:.1f} mm inside diameter at {cap:g} m/s. '
            f'{material} currently supports up to NPS {nominal:g} ({bore*1000:.1f} mm ID, {maximum*60000:,.0f} L/min). '
            'Reduce the circuit demand, split its headers, or choose a compatible larger-bore catalogue. The design remains editable.')


def select_size(flow,material,cap):
    """Round up to a commercial bore. `cap` is the CATEGORY velocity cap, not a
    global one: see standards.PipeCategory.velocity_cap_m_s."""
    if material not in CATALOGUES:
        raise ValueError(f'No dimension catalogue for {material!r}')
    if type(flow) not in (int,float) or not math.isfinite(flow) or flow < 0:
        raise ValueError('Pipe sizing flow must be finite and nonnegative')
    if type(cap) not in (int,float) or not math.isfinite(cap) or cap <= 0:
        raise ValueError('Pipe sizing velocity limit must be finite and positive')
    table,std=CATALOGUES[material]
    required=math.sqrt(4*flow/(math.pi*cap))
    for nominal,od,wall in table:
        inner=(od-2*wall)*.0254
        if inner+1e-12 >= required:
            return {'nominal_size_in':nominal,'od_m':od*.0254,'id_m':inner,
                    'wall_m':wall*.0254,'required_id_m':required,'size_standard':std}
    raise NoCatalogueSize(flow,material,cap)
