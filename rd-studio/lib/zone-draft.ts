/** Lightweight arrangement preview. Only Apply invokes the routing engine. */
export type Zone={id:string;kind:string;pod?:number;label:string;anchor_m:number[];anchor_layout_m?:number[];original_anchor_m?:number[];bounds_m:{min:number[];max:number[]}|null;rotation_deg:number;flip_x?:boolean;flip_y?:boolean;equipment_ids?:string[];rotation_parameter?:string};
export type ZoneEdit={anchor_m?:number[];rotation_deg?:number;flip_x?:boolean;flip_y?:boolean};
type Config=Record<string,any>;
export const placementKeys=new Set(['pod_origins_m','pod_rotations_deg','pod_flip_x','pod_flip_y','plant_origin_x_m','plant_origin_y_m','plant_rotation_deg','plant_flip_x','plant_flip_y','network_offset_x_m','network_offset_y_m','network_rotation_deg','network_flip_x','network_flip_y','air_offset_x_m','air_offset_y_m']);
const same=(a:any,b:any)=>JSON.stringify(a)===JSON.stringify(b);
/** Zones placed by an offset from where the generator put them, not by an origin. */
const offsetPrefix=(z:Zone)=>z.kind==='network_zone'?'network':z.kind==='air_cooling'?'air':'';
export function arrangementBlockReason(applied:Config,draft:Config){
 return Object.keys(draft).some(k=>!placementKeys.has(k)&&!same(draft[k],applied[k]))?'Apply the other parameter changes first to update the equipment and coordinate frame. Zone placement changes can be arranged together.':'';
}
function local(p:number[],c:Config){const a=Number(c.layout_rotation_deg||0)*Math.PI/180,co=Math.cos(a),si=Math.sin(a),x=p[0]-Number(c.layout_origin_x_m||0),y=p[1]-Number(c.layout_origin_y_m||0);return [co*x+si*y,-si*x+co*y,p[2]||0];}
function world(p:number[],c:Config){const a=Number(c.layout_rotation_deg||0)*Math.PI/180,co=Math.cos(a),si=Math.sin(a);return [co*p[0]-si*p[1]+Number(c.layout_origin_x_m||0),si*p[0]+co*p[1]+Number(c.layout_origin_y_m||0),p[2]||0];}
function vector(p:number[],z:Zone,inverse=false){const a=z.rotation_deg*Math.PI/180,co=Math.round(Math.cos(a)),si=Math.round(Math.sin(a)),sx=z.flip_x?-1:1,sy=z.flip_y?-1:1;return inverse?[sx*(co*p[0]+si*p[1]),sy*(-si*p[0]+co*p[1]),p[2]||0]:[co*sx*p[0]-si*sy*p[1],si*sx*p[0]+co*sy*p[1],p[2]||0];}
export function draftZone(zone:Zone,applied:Config,draft:Config):Zone{
 const old=zone.anchor_layout_m||local(zone.anchor_m,applied);let anchor=old;let rotation=zone.rotation_deg,flipX=!!zone.flip_x,flipY=!!zone.flip_y;
 if(zone.pod){const i=zone.pod-1;anchor=draft.pod_origins_m?.[i]?[...draft.pod_origins_m[i],old[2]]:(zone.original_anchor_m||old);rotation=draft.pod_rotations_deg?.[i]??0;flipX=draft.pod_flip_x?.[i]??false;flipY=draft.pod_flip_y?.[i]??false;}
 else {const prefix=offsetPrefix(zone);anchor=prefix?[old[0]+Number(draft[prefix+'_offset_x_m']||0)-Number(applied[prefix+'_offset_x_m']||0),old[1]+Number(draft[prefix+'_offset_y_m']||0)-Number(applied[prefix+'_offset_y_m']||0),old[2]]:[draft.plant_origin_x_m,draft.plant_origin_y_m,old[2]];
  // A zone that declares no rotation parameter moves and does not turn.
  if(zone.rotation_parameter){const key=prefix||'plant';rotation=draft[key+'_rotation_deg']??rotation;flipX=draft[key+'_flip_x']??flipX;flipY=draft[key+'_flip_y']??flipY;}}
 return {...zone,anchor_layout_m:anchor,anchor_m:world(anchor,applied),rotation_deg:rotation,flip_x:flipX,flip_y:flipY};
}
export function stageZoneEdit(zones:Zone[],applied:Config,draft:Config,id:string,edit:ZoneEdit):Config{
 const base=zones.find(z=>z.id===id);if(!base)throw Error('Select an available equipment zone.');
 const current=draftZone(base,applied,draft);const next={...current,...edit};
 if(edit.anchor_m&&(![2,3].includes(edit.anchor_m.length)||!edit.anchor_m.every(Number.isFinite)))throw Error('Use finite zone coordinates in metres.');
 if(!Number.isFinite(next.rotation_deg)||next.rotation_deg%90)throw Error('Use a multiple of 90 degrees.');
 if(typeof next.flip_x!=='boolean'||typeof next.flip_y!=='boolean')throw Error('Zone flips must be true or false.');
 next.rotation_deg=((next.rotation_deg%360)+360)%360;
 if(same(next.anchor_m,current.anchor_m)&&next.rotation_deg===current.rotation_deg&&next.flip_x===current.flip_x&&next.flip_y===current.flip_y)return draft;
 const anchor=local(next.anchor_m,applied),out={...draft};
 if(base.pod){const pods=zones.filter(z=>z.pod).sort((a,b)=>a.pod!-b.pod!).map(z=>draftZone(z,applied,draft));const idx=base.pod-1;
  for(const [key,value,values] of [['pod_origins_m',anchor.slice(0,2),pods.map(z=>z.anchor_layout_m!.slice(0,2))],['pod_rotations_deg',next.rotation_deg,pods.map(z=>z.rotation_deg)],['pod_flip_x',next.flip_x,pods.map(z=>z.flip_x)],['pod_flip_y',next.flip_y,pods.map(z=>z.flip_y)]] as [string,any,any[]][]){out[key]=values;out[key][idx]=value;}
 }else{const prefix=offsetPrefix(base);
  if(!prefix){out.plant_origin_x_m=anchor[0];out.plant_origin_y_m=anchor[1];}
  else{const old=current.anchor_layout_m!;out[prefix+'_offset_x_m']=Number(draft[prefix+'_offset_x_m']||0)+anchor[0]-old[0];out[prefix+'_offset_y_m']=Number(draft[prefix+'_offset_y_m']||0)+anchor[1]-old[1];}
  if(base.rotation_parameter){const key=prefix||'plant';out[key+'_rotation_deg']=next.rotation_deg;out[key+'_flip_x']=next.flip_x;out[key+'_flip_y']=next.flip_y;}}
 return out;
}
export function transformPoint(point:number[],before:Zone,after:Zone,config:Config){const a=before.anchor_layout_m||local(before.anchor_m,config),b=after.anchor_layout_m||local(after.anchor_m,config);const p=local(point,config);const v=vector(vector(p.map((x,i)=>x-a[i]),before,true),after);return world(v.map((x,i)=>x+b[i]),config);}
export function zoneMatrix(before:Zone,after:Zone,config:Config){const o=transformPoint([0,0,0],before,after,config),x=transformPoint([1,0,0],before,after,config),y=transformPoint([0,1,0],before,after,config);return [x[0]-o[0],x[1]-o[1],y[0]-o[0],y[1]-o[1],o[0],o[1]];}
export function belongsToZone(item:{id:string;host?:string},zone:Zone){return (zone.equipment_ids||[]).some(id=>id===item.id||id===item.host||(item.host?.startsWith('IT-R')&&id.startsWith(item.host+'-')));}
export function footprint(item:{center_m?:number[];size_m?:number[];rotation_deg?:number}){if(!item.center_m||!item.size_m)return [];const [x,y]=item.center_m,[w,h]=item.size_m,a=(item.rotation_deg||0)*Math.PI/180,co=Math.cos(a),si=Math.sin(a);return [[-w/2,-h/2],[w/2,-h/2],[w/2,h/2],[-w/2,h/2]].map(([u,v])=>[x+co*u-si*v,y+si*u+co*v]);}
export function polygonsOverlap(a:number[][],b:number[][]){if(!a.length||!b.length)return false;for(const p of [a,b])for(let i=0;i<p.length;i++){const j=(i+1)%p.length,n=[p[i][1]-p[j][1],p[j][0]-p[i][0]],length=Math.hypot(...n);if(length<1e-12)continue;const aa=a.map(v=>(v[0]*n[0]+v[1]*n[1])/length),bb=b.map(v=>(v[0]*n[0]+v[1]*n[1])/length);if(Math.min(Math.max(...aa),Math.max(...bb))-Math.max(Math.min(...aa),Math.min(...bb))<=1e-7)return false;}return true;}
