import assert from 'node:assert/strict';
import {currentCatalogue,CATALOGUE_URL} from '../public/finder-catalog.js';
import {equipmentSnapshot} from '../lib/equipment-tools.ts';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const original=globalThis.fetch;let version=0,requests=[];
try{
 globalThis.fetch=async(url,options)=>{requests.push({url:String(url),options});return new Response('catalogue snapshot '+(++version));};
 const first=await currentCatalogue(new AbortController().signal),second=await currentCatalogue(new AbortController().signal);
 assert.notEqual(first.metadata.sha256,second.metadata.sha256);assert.equal(first.metadata.source_url,CATALOGUE_URL);
 assert.equal(requests.length,2);assert.ok(requests.every(r=>r.options.cache==='no-store'&&r.options.credentials==='omit'&&r.options.redirect==='error'));
 globalThis.fetch=async()=>new Response('unavailable',{status:503});await assert.rejects(currentCatalogue(new AbortController().signal),/503/);
 globalThis.fetch=async()=>new Response('x',{headers:{'content-length':'3000000'}});await assert.rejects(currentCatalogue(new AbortController().signal),/size/);
}finally{globalThis.fetch=original;}
const req={config_hash:'abc',ready_for_matching:true,requirements:[{id:'REQ:V1',component_id:'V1'}]},report={status:'complete',items:[{component_id:'V1',candidates:[]}],summary:{items:1}};
const result=equipmentSnapshot(req,report,true,{component_ids:['V1']});
assert.equal(result.pending_parameters,true);assert.equal(result.candidates.length,1);
for(const input of [null,[],{bad:true},{component_ids:'V1'},{component_ids:['missing']}])assert.throws(()=>equipmentSnapshot(req,report,false,input));
console.log('Finder transport freshness, failure/size limits and read-only tool contract passed.');
// Exercise the actual worker's cancellation branch with a slow catalogue,
// retaining its loaded RD runtime. Browser QA separately tests real startup.
const messages=[],globals={};
const runtime={globals:{set(k,v){globals[k]=v;}},runPython(){return JSON.stringify({status:'unavailable',applied_config_hash:globals.config_hash,message:globals.finder_error});}};
const context=vm.createContext({self:{postMessage(m){messages.push(m);}},runtime,AbortController,setTimeout,clearTimeout,Uint8Array,
 currentCatalogue(signal){return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('Cancelled','AbortError')),{once:true}));}});
const source=readFileSync(new URL('../public/engine-worker.js',import.meta.url),'utf8').replace("import {currentCatalogue} from './finder-catalog.js';",'');
vm.runInContext(source+'\nruntimePromise=Promise.resolve(runtime);',context);
const job=context.self.onmessage({data:{requestId:1,action:'find_equipment',configHash:'a'.repeat(64)}});
await new Promise(resolve=>setTimeout(resolve,0));
await context.self.onmessage({data:{requestId:1,action:'cancel_finder'}});
await job;
assert.equal(messages.at(-1).type,'equipment');assert.equal(messages.at(-1).report.status,'unavailable');
assert.equal(vm.runInContext('working',context),false);
assert.equal(await vm.runInContext('runtimePromise',context),runtime);
console.log('Slow catalogue cancellation preserves the loaded RD session.');
