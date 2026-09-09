import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {buildContext,configStamp,localEndpoint,parseReply,proposedConfig,reviewDesign,localModels,askLocal} from '../lib/design-agent.ts';
const {parameters:fields,presets}=JSON.parse(readFileSync(new URL('../public/catalog.json',import.meta.url)));
const graph=JSON.parse(readFileSync(new URL('../public/initial-graph.json',import.meta.url)));
const base=graph.metadata.config;
const change=(parameter,value)=>({parameter,value_json:JSON.stringify(value),reason:'Test request'});
let tests=0;const test=(name,fn)=>{fn();tests++;console.log('PASS',name);};
test('Loopback only; reject remote URLs, credentials and redirects in the address',()=>{
 assert.equal(localEndpoint('http://localhost:11434'),'http://localhost:11434');
 for(const url of ['https://example.com','http://localhost.example.com','http://127.0.0.1@evil.test','http://localhost:11434/api/chat','file:///tmp/a','http://localhost/?forward=1'])assert.throws(()=>localEndpoint(url));
});
test('Snapshot includes draft changes, source notes and no meshes or full edge list',()=>{
 const c=buildContext({...base,rows:3},graph,fields,'Explain pipe sizing',true);
 assert.equal(c.pending_parameters,true);assert.equal(c.draft_config.rows,3);assert.equal(c.applied_summary.equipment_counts.compute_rack,32);
 assert.ok(c.relevant_parameters.length<=24);assert.ok(c.source_ids_available.length);assert.equal(JSON.stringify(c).includes('"vertices"'),false);assert.equal(JSON.stringify(c).includes('"faces"'),false);
});
test('Snapshot identity detects draft changes and ignores object-key order',()=>{
 assert.equal(configStamp({a:1,b:[2]}),configStamp({b:[2],a:1}));assert.notEqual(configStamp(base),configStamp({...base,rows:3}));
});
test('Patch leaves source configuration unchanged and retains exact values',()=>{
 const before=configStamp(base),p=proposedConfig(base,[change('flow_lpm_per_kw',1.2),change('sizing_mode','preliminary')],fields);
 assert.equal(configStamp(base),before);assert.equal(p.config.sizing_mode,'preliminary');
});
test('Reject unknown, duplicate, malformed, nonfinite and unavailable values',()=>{
 for(const changes of [[change('__proto__',{})],[change('rows',3),change('rows',2)],[change('rows','3')],[change('rows',0)],[change('plant_type','magic')],[change('pod_origins_m',{})],[{parameter:'rows',value_json:'NaN',reason:'x'}]])assert.throws(()=>proposedConfig(base,changes,fields));
});
test('Reset old assignment arrays when pod membership count changes',()=>{
 const old={...base,row_pod_assignments:[1,1,1,1],cdu_pod_assignments:[1,1,1],pod_origins_m:[[0,0]],pod_rotations_deg:[0]};
 const p=proposedConfig(old,[change('pod_count',2),change('cdu_count',4)],fields);
 assert.deepEqual(p.config.row_pod_assignments,[]);assert.deepEqual(p.config.cdu_pod_assignments,[]);assert.deepEqual(p.config.pod_origins_m,[]);assert.equal(p.changes.length,6);
});
test('Reject browser workload overflow and inactive controls',()=>{
 assert.throws(()=>proposedConfig(base,[change('rows',32)],fields));
 assert.throws(()=>proposedConfig(base,[change('flow_lpm_per_kw',2)],fields));
});
test('Reject nested assignments and incomplete pod placement instead of staging them',()=>{
 assert.throws(()=>proposedConfig(base,[change('pod_count',2),change('row_pod_assignments',[[1,1],[1,2]])],fields));
 assert.throws(()=>proposedConfig(base,[change('pod_count',2),change('pod_origins_m',[[0,0]])],fields));
 assert.throws(()=>proposedConfig(base,[change('pod_rotations_deg',[45])],fields));
});
test('Only supplied source IDs are accepted',()=>{
 const value={summary:'Review',changes:[],source_ids:['rows'],qualifications:[]};assert.equal(parseReply(JSON.stringify(value),['rows']).summary,'Review');
 assert.throws(()=>parseReply(JSON.stringify({...value,source_ids:['invented-standard']}),['rows']));assert.throws(()=>parseReply('not JSON',[]));
});
test('Review distinguishes pending parameters, manual dimensions and unverified imports',()=>{
 const report=reviewDesign(graph,true).join(' ');assert.match(report,/Pending/);assert.match(report,/manual/);assert.match(report,/unverified/);
});
const original=globalThis.fetch;
try{
 globalThis.fetch=async()=>Response.json({models:[{name:'local',size:1e9,digest:'a'},{name:'remote-cloud',size:1e9,digest:'b'},{name:'tiny-metadata',size:1000,digest:'c'}]});
 assert.deepEqual((await localModels('http://localhost:11434',new AbortController().signal)).map(m=>m.name),['local']);tests++;
 const context=buildContext(base,graph,fields,'Review',false);
 let captured;
 globalThis.fetch=async(url,options)=>{captured={url,options,body:JSON.parse(options.body)};return Response.json({message:{content:JSON.stringify({summary:'Grounded answer',changes:[],source_ids:[],qualifications:[]})}});};
 const answer=await askLocal('http://localhost:11434','local','Review',context,new AbortController().signal);
 assert.equal(answer.summary,'Grounded answer');assert.equal(captured.body.stream,false);assert.equal(captured.options.redirect,'error');assert.equal(captured.options.credentials,'omit');assert.equal(captured.body.messages[0].role,'system');tests++;
}finally{globalThis.fetch=original;}
console.log(tests+' assistant tests passed.');
const {editInputs,inactiveReason}=await import('../lib/design-agent.ts');
const changed=editInputs({...base,pod_count:2,cdu_count:4,cdu_pod_assignments:[1,1,2,2],row_pod_assignments:[1,1,2,2]},{cdu_count:3,rows:3});
assert.deepEqual(changed.config.cdu_pod_assignments,[]);assert.deepEqual(changed.config.row_pod_assignments,[]);assert.ok(changed.notes.length);
const shrink=editInputs({...base,pod_count:2,cdu_count:4,redundancy:2},{cdu_count:1});assert.equal(shrink.config.pod_count,1);assert.equal(shrink.config.redundancy,0);
assert.ok(inactiveReason(fields.find(f=>f.key==='cws_density_kg_m3'),{...base,sizing_mode:'preliminary',plant_type:'air_cooled'}));
assert.equal(inactiveReason(fields.find(f=>f.key==='cws_density_kg_m3'),{...base,sizing_mode:'preliminary',plant_type:'water_cooled'}),'');
assert.ok(fields.every(f=>f.effect));console.log('Count repair, combined dependencies and parameter effects passed.');
