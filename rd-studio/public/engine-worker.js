// This must be an ES module worker: the in-app browser rejects classic workers.
import {currentCatalogue} from './finder-catalog.js';
let runtimePromise;
let working = false;
let catalogueAbort;
async function checked(url, json = false) {
  const response = await fetch(url, {cache: 'no-cache'});
  if (!response.ok) throw new Error(`Engine asset failed to load (${response.status}): ${url}. Retry or reload the page.`);
  return json ? response.json() : response.text();
}
// Every module the worker enters the engine through. Importing them once here
// reaches the whole tree, so a deployment that uploads the page but drops part of
// /engine fails now, with the deployment named, instead of surfacing a bare Python
// ModuleNotFoundError inside whichever panel first reached for the missing module.
const ENGINE_ENTRY_POINTS = 'web_api, headless_selection, datacenter_equipment_finder, zone_editing, design_actions';
function initialize(requestId) {
  if (!runtimePromise) runtimePromise = (async () => {
    self.postMessage({type: 'status', requestId, message: 'Loading the design engine…'});
    const {loadPyodide} = await import('/pyodide/pyodide.mjs');
    const runtime = await loadPyodide({indexURL: '/pyodide/'});
    const manifest = await checked('/engine/manifest.json', true);
    if (!Array.isArray(manifest)) throw new Error('/engine/manifest.json did not return the engine file list. This deployment is serving something else at that address.');
    runtime.FS.mkdirTree('/engine');
    await Promise.all(manifest.map(async rawName => {
      // A manifest written on Windows carries backslash separators. Browsers
      // normalise those in a URL, so the fetch succeeds, but a backslash is an
      // ordinary character in the virtual filesystem: the file lands beside the
      // package instead of inside it and the package cannot be imported.
      const name = rawName.replace(/\\/g, '/');
      const contents = await checked('/engine/' + name);
      const path = '/engine/' + name;
      runtime.FS.mkdirTree(path.slice(0, path.lastIndexOf('/')));
      runtime.FS.writeFile(path, contents);
    }));
    runtime.runPython("import sys; sys.path.insert(0, '/engine')");
    try {
      runtime.runPython('import ' + ENGINE_ENTRY_POINTS);
    } catch (error) {
      const detail = String(error.message || error).trim().split('\n').at(-1);
      throw new Error(`This deployment is serving an incomplete design engine (${detail}). Redeploy the studio after running rd-studio/scripts/sync-engine.py.`);
    }
    return runtime;
  })().catch(error => { runtimePromise = undefined; throw error; });
  return runtimePromise;
}
self.onmessage = async ({data}) => {
  const {requestId, action} = data;
  if (action === 'cancel_finder') { catalogueAbort?.abort(); return; }
  if (working) { self.postMessage({type: 'error', requestId, message: 'A design operation is already running.'}); return; }
  working = true;
  try {
    const runtime = await initialize(requestId);
    if (['export','zone_edit','find_equipment'].includes(action) && data.appliedConfig) {
      runtime.globals.set('config_hash', data.configHash);
      runtime.globals.set('applied_config_json', JSON.stringify(data.appliedConfig));
      runtime.globals.set('equipment_report_json', JSON.stringify(data.equipmentReport || null));
      await runtime.runPythonAsync('from web_api import ensure_session\nensure_session(config_hash, applied_config_json, equipment_report_json)');
    }
    if (action === 'preview') {
      self.postMessage({type: 'status', requestId, message: 'Building and checking the network…'});
      runtime.globals.set('config_json', JSON.stringify(data.config));
      const result = JSON.parse(await runtime.runPythonAsync('from web_api import preview\npreview(config_json)'));
      self.postMessage({type: 'result', requestId, result});
    } else if (action === 'optimize_routes') {
      self.postMessage({type:'status',requestId,message:'Comparing three plant corridor routes and checking geometry…'});
      runtime.globals.set('config_json',JSON.stringify(data.config));
      const proposal=JSON.parse(await runtime.runPythonAsync('from web_api import optimize_routes\noptimize_routes(config_json)'));
      self.postMessage({type:'optimization',requestId,proposal});
    } else if (action === 'zone_edit') {
      self.postMessage({type:'status',requestId,message:'Checking placement and rerouting the zone…'});
      runtime.globals.set('config_hash', data.configHash);
      runtime.globals.set('edit_json',JSON.stringify(data.edit));
      const proposal=JSON.parse(await runtime.runPythonAsync('from web_api import apply_zone_edit\napply_zone_edit(config_hash, edit_json)'));
      self.postMessage({type:'zone_edit',requestId,configHash:data.configHash,proposal});
    } else if (action === 'find_equipment') {
      catalogueAbort = new AbortController();
      const timeout = setTimeout(()=>catalogueAbort?.abort(),20000);
      runtime.globals.set('config_hash', data.configHash);
      try {
        self.postMessage({type:'status',requestId,message:'Design applied · finding equipment for RD-calculated duties…'});
        const catalogue = await currentCatalogue(catalogueAbort.signal);
        runtime.globals.set('catalogue_csv',catalogue.csv);
        runtime.globals.set('catalogue_metadata_json',JSON.stringify(catalogue.metadata));
        const report=JSON.parse(await runtime.runPythonAsync('from web_api import find_equipment\nfind_equipment(config_hash, catalogue_csv, catalogue_metadata_json)'));
        self.postMessage({type:'equipment',requestId,configHash:data.configHash,report});
      } catch(error) {
        const message=error.name==='AbortError'?'Equipment search stopped. Retry when ready; the applied design and downloads are available.':String(error.message||error).trim().split('\n').at(-1);
        runtime.globals.set('finder_error',message);
        const report=JSON.parse(runtime.runPython('from web_api import finder_unavailable\nfinder_unavailable(config_hash, finder_error)'));
        self.postMessage({type:'equipment',requestId,configHash:data.configHash,report});
      } finally {clearTimeout(timeout);catalogueAbort=undefined;}
    } else if (action === 'export') {
      self.postMessage({type: 'status', requestId, message: 'Preparing the selected download…'});
      runtime.globals.set('export_name', data.name);
      runtime.globals.set('config_hash', data.configHash);
      const result = JSON.parse(await runtime.runPythonAsync('from web_api import export_file\nexport_file(export_name, config_hash)'));
      const binary = Uint8Array.from(atob(result.base64), character => character.charCodeAt(0));
      self.postMessage({type: 'download', requestId, name: result.name, mime: result.mime, configHash: result.config_hash, buffer: binary.buffer}, [binary.buffer]);
    } else throw new Error('Unknown design operation. Reload this page.');
  } catch (error) {
    const detail=String(error.message || error);
    const lines=detail.trim().split('\n');
    const message=lines[lines.length-1].replace(/^(ValueError|TypeError|RuntimeError|KeyError):\s*/, '');
    self.postMessage({type: 'error', requestId, message});
  } finally { working = false; }
};
