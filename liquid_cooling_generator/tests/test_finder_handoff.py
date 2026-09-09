import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import web_api
from parameters import PRESETS
from test_headless_selection import row, SOURCE
from datacenter_equipment_finder.catalog import FIELD_NAMES
import csv

def test_headless_search_keeps_rd_design_and_exports_bound_after_failure():
    config={**PRESETS['compact']['config'],'sizing_mode':'preliminary'}
    applied=json.loads(web_api.preview(json.dumps(config)))
    assert applied['exportable']
    graph=web_api._session[0]
    geometry=json.dumps([graph['components'],graph['edges']],sort_keys=True)
    requirements=deepcopy(graph['metadata']['equipment_requirements'])
    stream=io.StringIO();w=csv.DictWriter(stream,fieldnames=FIELD_NAMES);w.writeheader();w.writerow(row())
    csv_text=stream.getvalue()
    metadata={'source_url':SOURCE,'sha256':hashlib.sha256(csv_text.encode()).hexdigest(),'fetched_at':'2026-09-08T00:00:00Z'}
    report=json.loads(web_api.find_equipment(applied['config_hash'],csv_text,json.dumps(metadata)))
    assert report['config_hash']==applied['config_hash']
    assert report['selected_part_numbers']==[]
    assert graph['metadata']['equipment_requirements']==requirements
    assert json.dumps([graph['components'],graph['edges']],sort_keys=True)==geometry
    with pytest.raises(ValueError,match='another design'):web_api.find_equipment('0'*64,csv_text,json.dumps(metadata))
    for unavailable in [False,True]:
        if unavailable: web_api.finder_unavailable(applied['config_hash'],'Catalogue temporarily unavailable')
        exported=json.loads(web_api.export_file('graph.json',applied['config_hash']))
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(exported['base64']))) as archive:
            assert json.loads(archive.read('equipment_requirements.json'))==requirements
            matches=json.loads(archive.read('equipment_candidates.json'))
            assert matches['applied_config_hash']==applied['config_hash']
            assert matches['status']==('unavailable' if unavailable else 'complete')
            assert json.loads(archive.read('graph.json'))['metadata']['equipment_finder']==matches
