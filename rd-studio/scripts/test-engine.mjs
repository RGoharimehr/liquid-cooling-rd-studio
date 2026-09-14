import {loadPyodide} from 'pyodide';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {CATALOGUE_URL, FINDER_REVISION} from '../public/finder-catalog.js';
const base=path.resolve('public/engine');
const py=await loadPyodide({indexURL:path.resolve('node_modules/pyodide')});
py.FS.mkdirTree('/engine');
for(const name of JSON.parse(fs.readFileSync(path.join(base,'manifest.json'),'utf8'))){const target='/engine/'+name;py.FS.mkdirTree(path.dirname(target));py.FS.writeFile(target,fs.readFileSync(path.join(base,name)));}
py.runPython("import sys; sys.path.insert(0, '/engine')");

// The manifest is what the browser worker fetches, so a module missing from it is
// missing from the studio even though it is right there in the repository. That is
// invisible to a preset run: it only shows up when a panel reaches for the module.
const listed=new Set(JSON.parse(fs.readFileSync(path.join(base,'manifest.json'),'utf8')));
const onDisk=fs.readdirSync(base).filter(name=>name.endsWith('.py'));
for(const name of onDisk) assert(listed.has(name),`${name} is on disk but absent from the browser manifest`);
for(const name of fs.readdirSync(path.join(base,'datacenter_equipment_finder')).filter(n=>n.endsWith('.py')))
  assert(listed.has('datacenter_equipment_finder/'+name),`datacenter_equipment_finder/${name} is absent from the browser manifest`);
py.runPython("import datacenter_equipment_finder, headless_selection, web_api");
console.log('engine imports PASS',listed.size,'manifest entries');

const catalog=JSON.parse(fs.readFileSync('public/catalog.json','utf8'));
// The finder panel is the one call path that leaves the engine package and enters
// the pinned selector. Run it against a stub catalogue so a break is a CI failure
// rather than a traceback in the browser panel.
const FIELDS='brand,category,component_subtype,series_name,component_name,nominal_size_mm,nominal_size_inch,flow_coefficient_type,flow_coefficient_value,capacity_kw,capacity_tons,connection_type,connection_standard,material,pressure_rating_bar,max_temperature_c,coolant_compatibility,estimated_price_usd,install_connection_time_min,part_number,source_catalog,source_page,datasheet_url,baseline_references,verification_status';
const STUB_ROW='Stub,valve,shutoff_valve,S1,Ball Valve DN100,100,4,Kv,320,,,flanged,ASME B16.5,stainless,16,120,PG25;water,1200,45,STUB-BV-100,Stub catalogue,12,https://example.invalid/bv,,unverified';
{
  const preset=catalog.presets.compact;
  py.globals.set('config_json',JSON.stringify(preset.config));
  const applied=JSON.parse(await py.runPythonAsync("from web_api import preview\npreview(config_json)"));
  py.globals.set('config_hash',applied.config_hash);
  const csv=[FIELDS,STUB_ROW].join('\n')+'\n';
  py.globals.set('catalogue_csv',csv);
  // Only the rows are stubbed. The selector checks provenance and re-digests the
  // text it is handed, so the snapshot identity is the real published catalogue
  // and the digest is the one these rows actually hash to.
  py.globals.set('catalogue_metadata_json',JSON.stringify({source_url:CATALOGUE_URL,
    sha256:createHash('sha256').update(csv,'utf8').digest('hex'),
    fetched_at:new Date().toISOString(),finder_revision:FINDER_REVISION,bytes:Buffer.byteLength(csv)}));
  const report=JSON.parse(await py.runPythonAsync("from web_api import find_equipment\nfind_equipment(config_hash, catalogue_csv, catalogue_metadata_json)"));
  assert.notEqual(report.status,'unavailable');
  assert(Array.isArray(report.items)&&report.items.length>0,'the finder returned no component duties');
  console.log('find_equipment PASS',report.items.length,'duties against a stub catalogue');
}
for(const [key,preset] of Object.entries(catalog.presets)){
 py.globals.set('config_json',JSON.stringify(preset.config));
 const start=Date.now();const raw=await py.runPythonAsync("from web_api import generate\ngenerate(config_json)");
 const data=JSON.parse(raw);assert(data.files['network.ifc'].includes('IFC4'));assert(data.files['network_TCS.pcf'].includes('MISC-COMPONENT'));assert(data.files['BOM.csv']);assert(Buffer.from(data.zip,'base64').subarray(0,2).toString()==='PK');
 assert.equal(data.graph.components.filter(c=>c.kind==='compute_rack').length,preset.config.rows*preset.config.racks_per_row);
 console.log(key,'PASS',data.graph.components.length,'objects',Math.round((Date.now()-start)/1000)+'s',Math.round(raw.length/1024/1024)+' MB API payload');
}
