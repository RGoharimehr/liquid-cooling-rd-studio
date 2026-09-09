import {loadPyodide} from 'pyodide';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const base=path.resolve('public/engine');
const py=await loadPyodide({indexURL:path.resolve('node_modules/pyodide')});
py.FS.mkdirTree('/engine');
for(const name of JSON.parse(fs.readFileSync(path.join(base,'manifest.json'),'utf8'))){const target='/engine/'+name;py.FS.mkdirTree(path.dirname(target));py.FS.writeFile(target,fs.readFileSync(path.join(base,name)));}
py.runPython("import sys; sys.path.insert(0, '/engine')");
const catalog=JSON.parse(fs.readFileSync('public/catalog.json','utf8'));
for(const [key,preset] of Object.entries(catalog.presets)){
 py.globals.set('config_json',JSON.stringify(preset.config));
 const start=Date.now();const raw=await py.runPythonAsync("from web_api import generate\ngenerate(config_json)");
 const data=JSON.parse(raw);assert(data.files['network.ifc'].includes('IFC4'));assert(data.files['network_TCS.pcf'].includes('MISC-COMPONENT'));assert(data.files['BOM.csv']);assert(Buffer.from(data.zip,'base64').subarray(0,2).toString()==='PK');
 assert.equal(data.graph.components.filter(c=>c.kind==='compute_rack').length,preset.config.rows*preset.config.racks_per_row);
 console.log(key,'PASS',data.graph.components.length,'objects',Math.round((Date.now()-start)/1000)+'s',Math.round(raw.length/1024/1024)+' MB API payload');
}
