import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {draftZone,stageZoneEdit,arrangementBlockReason,transformPoint,polygonsOverlap} from '../lib/zone-draft.ts';
import {importParameters} from '../lib/config-import.ts';
const graph=JSON.parse(readFileSync('public/initial-graph.json','utf8'));
const applied=graph.metadata.config,zones=graph.layout.editable_zones,plant=zones.find(z=>z.kind==='plant'),pod=zones.find(z=>z.pod===1),network=zones.find(z=>z.kind==='network_zone');
let draft=applied;
assert.equal(stageZoneEdit(zones,applied,draft,plant.id,{anchor_m:plant.anchor_m}),draft);
for(let n=1;n<=3;n++){const p=draftZone(plant,applied,draft);draft=stageZoneEdit(zones,applied,draft,plant.id,{anchor_m:[p.anchor_m[0]+.5,p.anchor_m[1],p.anchor_m[2]]});assert.equal(draft.plant_origin_x_m,applied.plant_origin_x_m+n*.5);assert.equal(arrangementBlockReason(applied,draft),'');}
const before=JSON.stringify(draft);
for(let n=1;n<=4;n++){const p=draftZone(plant,applied,draft);draft=stageZoneEdit(zones,applied,draft,plant.id,{rotation_deg:(p.rotation_deg+90)%360});assert.equal(draft.plant_rotation_deg,(applied.plant_rotation_deg+n*90)%360);}
assert.equal(JSON.stringify(draft),before,'four rotations restore arrangement without touching other inputs');
for(let n=1;n<=2;n++){draft=stageZoneEdit(zones,applied,draft,plant.id,{flip_x:!draftZone(plant,applied,draft).flip_x});assert.equal(draft.plant_flip_x,!!(n%2));}
const p=draftZone(pod,applied,draft);draft=stageZoneEdit(zones,applied,draft,pod.id,{anchor_m:[p.anchor_m[0]+.25,p.anchor_m[1],p.anchor_m[2]]});
const n=draftZone(network,applied,draft);draft=stageZoneEdit(zones,applied,draft,network.id,{anchor_m:[n.anchor_m[0],n.anchor_m[1]+.5,n.anchor_m[2]],flip_y:true});
assert.equal(draft.plant_origin_x_m,applied.plant_origin_x_m+1.5);assert.equal(draft.pod_origins_m[0][0],p.anchor_m[0]+.25);assert.equal(draft.network_offset_y_m,applied.network_offset_y_m+.5);assert.equal(draft.network_flip_y,true);
assert.equal(graph.metadata.config.plant_origin_x_m,applied.plant_origin_x_m);assert.notEqual(draft,applied);assert.ok(arrangementBlockReason(applied,{...draft,rows:applied.rows+1}));
const config={layout_rotation_deg:90,layout_origin_x_m:100,layout_origin_y_m:200};
const old={id:'plant',kind:'plant',label:'Plant',anchor_m:[80,210,0],anchor_layout_m:[10,20,0],rotation_deg:0,flip_x:false,flip_y:false};
const turn={...old,rotation_deg:90,flip_x:true};
const out=transformPoint([80,212,0],old,turn,config);assert.ok(Math.abs(out[0]-82)<1e-7&&Math.abs(out[1]-210)<1e-7,'flip local X then rotate within world frame');
assert.equal(polygonsOverlap([[0,0],[1,0],[1,1],[0,1]],[[1,0],[2,0],[2,1],[1,1]]),false);
assert.equal(polygonsOverlap([[0,0],[1,0],[1,1],[0,1]],[[.5,0],[1.5,0],[1.5,1],[.5,1]]),true);
for(const type of ['air_cooled','water_cooled'])for(const version of [undefined,1,2]){const input={plant_type:type,...(version?{schema_version:version}:{})};const result=importParameters(input,applied);assert.equal(result.plant_type,type);assert.equal(result.schema_version,2);}
assert.equal(importParameters({},applied).plant_type,'boundary');assert.equal(importParameters({schema_version:2},applied).plant_type,applied.plant_type);
for(const bad of [null,[],{schema_version:3},{unknown:1}])assert.throws(()=>importParameters(bad,applied));
console.log('Draft accumulation, independent zones, rotate/flip controls, world coordinates, overlaps and legacy plant imports passed.');
