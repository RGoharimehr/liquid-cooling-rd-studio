"""Headless tool uses RD requirements without recalculating or altering them."""
import csv
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datacenter_equipment_finder.catalog import FIELD_NAMES
from headless_selection import select_requirements, SelectionInputError

SOURCE='https://raw.githubusercontent.com/RGoharimehr/DATA-CENTER-EQUIPMENT-FINDER/main/src/datacenter_equipment_finder/data/equipment_catalog.csv'

def row(part='MATCH', **changes):
    values=dict.fromkeys(FIELD_NAMES,'')
    values.update(brand='Test',category='valve',component_subtype='shutoff_valve',series_name='Fixture',component_name='Test valve',nominal_size_mm='50',nominal_size_inch='2',material='Stainless Steel',pressure_rating_bar='10',max_temperature_c='100',coolant_compatibility='Water',part_number=part,source_catalog='Synthetic test source',source_page='1',datasheet_url='https://example.com/test.pdf',verification_status='verified',connection_type='FLANGED',connection_standard='ASME B16.5')
    values.update(changes);return values

def requirement(kind='isolation_valve', **changes):
    item={'id':'REQ:V1','component_id':'V1','kind':kind,'category':'valve','supported_by_finder':True,'ready_for_matching':True,'circuit_ids':['FWS'],'ports':[{'nominal_nps_in':2,'pipe_id_m':.050419,'connection_type':'FLANGED','connection_standard':'ASME B16.5'}],
          'fluid_sides':[{'circuit_id':'FWS','design_flow_m3_s':.002,'minimum_pressure_rating_Pa':600000,'temperature':{'required_max_temperature_C':50},'fluid':{'name':'water'},'required_material':'Stainless Steel'}]}
    item.update(changes)
    return {'schema_version':'1.0','config_hash':'a'*64,'ready_for_matching':True,'requirements':[item]}

def query(req, rows):
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=FIELD_NAMES);writer.writeheader();writer.writerows(rows)
    text=stream.getvalue()
    return select_requirements(req,text,{'source_url':SOURCE,'sha256':hashlib.sha256(text.encode()).hexdigest(),'fetched_at':'2026-09-08T00:00:00Z'})

def test_nominal_match_keeps_real_bore_separate_and_never_resizes():
    req=requirement();before=deepcopy(req)
    result=query(req,[row(),row('TOO-LARGE',nominal_size_mm='80',nominal_size_inch='3')])
    assert [c['component']['part_number'] for c in result['items'][0]['candidates']]==['MATCH']
    assert req==before
    assert result['selected_part_numbers']==[]

def test_material_filter_precedes_shortlist_limit():
    result=query(requirement(),[row(str(i),material='Copper') for i in range(4)]+[row('FIFTH')])
    assert result['items'][0]['candidates'][0]['component']['part_number']=='FIFTH'

def test_balancing_role_does_not_select_shutoff_and_finder_does_not_invent_kv():
    req=requirement('balancing_valve',throttling={'required_Kv_m3_h':100,'required_Cv_US':115.6,'allocated_dp_Pa':20000})
    result=query(req,[row(flow_coefficient_type='Kv',flow_coefficient_value='110')])
    assert result['items'][0]['candidates']==[]
    assert result['items'][0]['exclusions']['functional_role']==1

def test_known_capacity_ranks_before_missing_even_with_common_qualifications():
    req=requirement('balancing_valve',throttling={'required_Kv_m3_h':100,'required_Cv_US':115.6,'allocated_dp_Pa':20000})
    result=query(req,[row('UNKNOWN',component_subtype='balancing_valve'),row('KNOWN',component_subtype='balancing_valve',flow_coefficient_type='Kv',flow_coefficient_value='110')])
    candidates=result['items'][0]['candidates']
    assert candidates[0]['component']['part_number']=='KNOWN'
    assert all(c['status']=='tentative' for c in candidates)

def test_unknown_rating_never_counts_as_qualified():
    result=query(requirement(),[row(pressure_rating_bar='')])
    assert result['summary']['qualified']==0
    assert result['summary']['tentative']==1

def test_independent_catalogue_update_changes_results_without_rd_change():
    req=requirement();one=query(req,[row('FIRST')]);two=query(req,[row('UPDATED')])
    assert one['config_hash']==two['config_hash']
    assert one['requirements_sha256']==two['requirements_sha256']
    assert one['catalogue_sha256']!=two['catalogue_sha256']
    assert two['items'][0]['candidates'][0]['component']['part_number']=='UPDATED'

def test_missing_duty_or_inconsistent_dimensions_prevent_matching():
    for req in [requirement(ready_for_matching=False),dict(requirement(),ready_for_matching=False)]:
        result=query(req,[row()]);assert result['summary']['with_candidates']==0

def test_fluid_species_requirement_is_not_satisfied_by_water_word():
    req=requirement();req['requirements'][0]['fluid_sides'][0]['fluid']={'name':'water / propylene glycol','pg_volume_fraction':.25}
    result=query(req,[row()]);assert not result['items'][0]['candidates']

def test_disputed_and_unsupported_items_remain_unresolved():
    assert not query(requirement(),[row(verification_status='disputed')])['items'][0]['candidates']
    result=query(requirement('pump',category='pump',supported_by_finder=False),[row()])
    assert result['summary']['unresolved']==1

@pytest.mark.parametrize('change',[{'flow_coefficient_value':'NaN','flow_coefficient_type':'Cv'},{'pressure_rating_bar':'-2'},{'datasheet_url':'javascript:alert(1)'},{'verification_status':'certified'}])
def test_malformed_database_fails_visibly(change):
    with pytest.raises(SelectionInputError):query(requirement(),[row(**change)])

def test_hash_mismatch_rejected():
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=FIELD_NAMES);writer.writeheader();writer.writerow(row())
    with pytest.raises(SelectionInputError,match='SHA-256'):
        select_requirements(requirement(),stream.getvalue(),{'source_url':SOURCE,'sha256':'0'*64})

def test_multicircuit_generic_fluid_rating_cannot_exclude_the_other_side():
    req=requirement('cdu',category='cdu',thermal_duty={'required_capacity_W':500000})
    req['requirements'][0]['fluid_sides'].append({'circuit_id':'TCS-P01','design_flow_m3_s':.003,'minimum_pressure_rating_Pa':600000,'temperature':{'required_max_temperature_C':45},'fluid':{'name':'water / propylene glycol'}})
    result=query(req,[row(category='cdu',component_subtype='',capacity_kw='1050',coolant_compatibility='Propylene Glycol 25%')])
    assert result['items'][0]['candidates']
    candidate=result['items'][0]['candidates'][0]
    assert candidate['status']=='tentative'
    assert any('Per-circuit coolant' in note for note in candidate['limitations'])

def test_manual_velocity_exceedance_remains_a_tentative_candidate_limitation():
    req = requirement(unresolved=[{'code':'MANUAL_VELOCITY_LIMIT_EXCEEDED',
                                  'detail':'Manual bore gives 5.2 m/s above the 1.5 m/s criterion; review size or demand.'}])
    report = query(req, [row()])
    candidates = report['items'][0]['candidates']
    assert candidates
    assert all(candidate['status'] == 'tentative' for candidate in candidates)
    assert all(any('Manual bore gives 5.2' in note for note in candidate['limitations']) for candidate in candidates)
