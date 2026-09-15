'use client';
import {useEffect,useMemo,useRef,useState} from 'react';
import type {Component,Graph} from './viewer';
import {color} from './viewer';
import {snappedMove} from '@/lib/zone-interaction';
import {draftZone,zoneMatrix,transformPoint,belongsToZone,footprint,polygonsOverlap,type Zone,type ZoneEdit} from '@/lib/zone-draft';
export type EditableZone=Zone;
export type {ZoneEdit};
export default function PlanEditor({graph,draftConfig,clearances,accessories,onSelect,editing,locked=false,revision=0,onMove,onEdit}:{graph:Graph;draftConfig?:Record<string,any>;clearances:boolean;accessories:boolean;onSelect:(c:Component)=>void;editing:boolean;locked?:boolean;revision?:number;onMove?:(zone:EditableZone,point:number[])=>void;onEdit?:(zone:EditableZone,edit:ZoneEdit)=>void}){
 const svg=useRef<SVGSVGElement>(null),drag=useRef<{zone:Zone;start:number[]}|null>(null);
 const [selectedZone,setSelectedZone]=useState(''),[offsets,setOffsets]=useState<Record<string,number[]>>({});
 useEffect(()=>{drag.current=null;setOffsets({});},[graph.nodes,graph.layout,revision]);
 const visible=useMemo(()=>graph.components.filter(c=>!c.attachment||accessories),[graph.components,accessories]);
 const config=graph.metadata.config||{},draft=draftConfig||config;
 const zones=useMemo(()=>(graph.layout.editable_zones||[]).map(z=>draftZone(z,config,draft)),[graph.layout,config,draft]);
 const baseZones=graph.layout.editable_zones||[];
 const changed=zones.some((z,i)=>{const old=baseZones[i];return z.anchor_m.some((v,k)=>Math.abs(v-old.anchor_m[k])>1e-7)||z.rotation_deg!==old.rotation_deg||!!z.flip_x!==!!old.flip_x||!!z.flip_y!==!!old.flip_y;});
 const matrix=(item:{id:string;host?:string})=>{const i=baseZones.findIndex(z=>belongsToZone(item,z));if(i<0)return undefined;const m=zoneMatrix(baseZones[i],zones[i],config),delta=offsets[zones[i].id]||[0,0];m[4]+=delta[0];m[5]+=delta[1];return `matrix(${m.join(' ')})`;};
 const movedPoints=(item:{id:string;host?:string;center_m?:number[];size_m?:number[];rotation_deg?:number})=>{const i=baseZones.findIndex(z=>belongsToZone(item,z));return footprint(item).map(p=>i<0?p:transformPoint([...p,0],baseZones[i],zones[i],config).slice(0,2));};
 const reservations=graph.layout.clearance_zones as (Graph['layout']['clearance_zones'][number]&{host?:string;floor_elevation_m?:number})[];
 const placement=useMemo(()=>{
  const bodies=visible.filter(c=>c.center_m&&c.size_m&&!c.attachment),points=new Map([...bodies,...reservations].map(c=>[c.id,movedPoints(c)]));
  const conflicts:string[]=[];const ids=new Set<string>();
  for(let i=0;i<bodies.length;i++)for(let j=i+1;j<bodies.length;j++){const a=bodies[i],b=bodies[j];if(Math.abs(a.center_m![2]-b.center_m![2])>=(a.size_m![2]+b.size_m![2])/2-1e-7)continue;if(polygonsOverlap(points.get(a.id)!,points.get(b.id)!)){conflicts.push(`${a.id} overlaps ${b.id}`);ids.add(a.id);ids.add(b.id);}}
  for(const z of reservations)for(const b of bodies){if(b.id===z.host||(z.host?.startsWith('IT-R')&&b.id.startsWith(z.host+'-')))continue;if(b.center_m![2]-b.size_m![2]/2>(z.floor_elevation_m||0)+2.5)continue;if(polygonsOverlap(points.get(z.id)!,points.get(b.id)!)){conflicts.push(`${b.id} obstructs service access for ${z.host||z.id}`);ids.add(b.id);}}
  return {conflicts,ids};
 // Transient drag outlines are free to move; inspect the complete staged placement at release.
 },[zones,visible,reservations]);
 const fw=Number(config.site_footprint_width_m||0),fd=Number(config.site_footprint_depth_m||0),fx=Number(config.site_footprint_origin_x_m||0),fy=Number(config.site_footprint_origin_y_m||0);
 // Keep the applied viewport fixed through a draft so dragging does not chase a rescaled plan.
 const [minx,miny,maxx,maxy]=useMemo(()=>{const points=visible.flatMap(c=>c.mesh?.vertices||[]);points.push([0,0,0]);if(fw&&fd)points.push([fx,fy,0],[fx+fw,fy+fd,0]);return [points.reduce((v,p)=>Math.min(v,p[0]),Infinity)-4,points.reduce((v,p)=>Math.min(v,p[1]),Infinity)-4,points.reduce((v,p)=>Math.max(v,p[0]),-Infinity)+4,points.reduce((v,p)=>Math.max(v,p[1]),-Infinity)+4];},[visible,fw,fd,fx,fy]);
 const labelSize=Math.max(.9,(maxy-miny)/45),nodes=useMemo(()=>Object.fromEntries(graph.nodes.map(n=>[n.id,n.xyz_m])),[graph.nodes]);
 // Declared handover points. A pod's point is the tee where its duty joins the
 // facility trunk, and the leader is the facility point it was assigned to, so
 // a pod routed past the nearer plant shows as a line that crosses the hall.
 const handovers=useMemo(()=>{
  const declared=graph.metadata.connection_points;if(!declared)return [];
  const facility:Record<string,any>=Object.fromEntries((declared.facility||[]).map((f:any)=>[f.id,f]));
  const assigned:Record<string,any>=Object.fromEntries((declared.assignments||[]).map((a:any)=>[a.zone,a]));
  const lpm=(q:number)=>(q*60000).toFixed(0)+' L/min';
  return [...(declared.facility||[]).map((f:any)=>({id:f.id,point:f.point_m,to:null,
           note:`${f.label} · declared facility connection point · capacity ${lpm(f.capacity_m3_s||0)}`})),
          ...(declared.zones||[]).map((z:any)=>{const row=assigned[z.id],host=facility[row?.connection_point];
           return {id:z.id,point:z.point_m,to:host&&host.id!==z.id?host.point_m:null,
                   note:`${z.label} → ${host?.label||'unassigned'} · ${lpm(z.flow_m3_s||0)} · ${row?.distance_m??'?'} m${row?.status?' · '+row.status:''}`};})];
 },[graph.metadata]);
 const at=(e:React.PointerEvent)=>{const m=svg.current?.getScreenCTM();if(!m)return null;const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(m.inverse());return [p.x,p.y];};
 const start=(e:React.PointerEvent,zone:Zone)=>{setSelectedZone(zone.id);if(!editing||locked||!onMove||e.button!==0)return;const p=at(e);if(!p)return;e.preventDefault();e.stopPropagation();svg.current!.setPointerCapture(e.pointerId);drag.current={zone,start:p};};
 const move=(e:React.PointerEvent)=>{const d=drag.current,p=at(e);if(!d||!p||locked)return;setOffsets({[d.zone.id]:[Math.round((p[0]-d.start[0])*4)/4,Math.round((p[1]-d.start[1])*4)/4]});};
 const finish=(e:React.PointerEvent)=>{const d=drag.current,p=at(e);if(!d)return;drag.current=null;if(svg.current?.hasPointerCapture(e.pointerId))svg.current.releasePointerCapture(e.pointerId);setOffsets({});const target=p&&snappedMove(d.zone.anchor_m,d.start,p);if(target&&!locked)onMove?.(d.zone,target);};
 const selected=zones.find(z=>z.id===selectedZone)||zones[0];
 return <div className="plan-editor-shell" aria-busy={locked}>
 {editing&&selected&&<div className="zone-edit-tools"><label>Zone <select aria-label="Equipment zone" value={selected.id} onChange={e=>setSelectedZone(e.target.value)}>{zones.map(z=><option key={z.id} value={z.id}>{z.label}</option>)}</select></label><button type="button" disabled={locked} onClick={()=>onEdit?.(selected,{rotation_deg:(selected.rotation_deg+90)%360})}>Rotate 90°</button><button type="button" disabled={locked} aria-pressed={!!selected.flip_x} onClick={()=>onEdit?.(selected,{flip_x:!selected.flip_x})}>Flip X</button><button type="button" disabled={locked} aria-pressed={!!selected.flip_y} onClick={()=>onEdit?.(selected,{flip_y:!selected.flip_y})}>Flip Y</button><span>{selected.anchor_m.slice(0,2).map(n=>n.toFixed(2)).join(', ')} m · {selected.rotation_deg}°{selected.flip_x?' · X flipped':''}{selected.flip_y?' · Y flipped':''}</span></div>}
 {changed&&<div className="draft-placement-note" role="status">Draft arrangement · move, rotate or flip again, then Apply design. Faint pipes show the last applied route.{placement.conflicts.length>0&&<details><summary>{placement.conflicts.length} placement conflicts · keep arranging to resolve</summary>{placement.conflicts.slice(0,8).map((s,i)=><p key={i}>{s}</p>)}</details>}</div>}
 <svg ref={svg} className={'actual-plan '+(editing?'editing':'')} viewBox={`${minx} ${miny} ${maxx-minx} ${maxy-miny}`} role={editing?'group':'img'} aria-label={editing?'Arrange cooling pods and equipment zones; drag a labelled handle or use arrow keys, then Apply design.':'Plan of the generated network, in metres'} onPointerMove={move} onPointerUp={finish} onPointerCancel={()=>{drag.current=null;setOffsets({});}} onLostPointerCapture={()=>{if(drag.current){drag.current=null;setOffsets({});}}}>
 <g stroke="#344759" strokeWidth=".08"><path d="M -1 0 H 1 M 0 -1 V 1"/><text x=".4" y="-.4" stroke="none" fill="#344759" fontSize={labelSize*.7}>World 0, 0</text></g>
 {fw>0&&fd>0&&<rect x={fx} y={fy} width={fw} height={fd} fill="none" stroke="#a05633" strokeWidth=".10" strokeDasharray=".6 .3"><title>Declared site footprint</title></rect>}
 {clearances&&reservations.map(z=><g key={z.id} transform={matrix(z)}><rect transform={`rotate(${z.rotation_deg||0} ${z.center_m[0]} ${z.center_m[1]})`} x={z.center_m[0]-z.size_m[0]/2} y={z.center_m[1]-z.size_m[1]/2} width={z.size_m[0]} height={z.size_m[1]} fill="#dec780" opacity=".3"/></g>)}
 {visible.filter(c=>c.center_m&&c.size_m).map(c=><g key={c.id} transform={matrix(c)}><rect transform={`rotate(${c.rotation_deg||0} ${c.center_m![0]} ${c.center_m![1]})`} x={c.center_m![0]-c.size_m![0]/2} y={c.center_m![1]-c.size_m![1]/2} width={c.size_m![0]} height={c.size_m![1]} fill={color(c)} stroke={changed&&placement.ids.has(c.id)?'#ba3e22':undefined} strokeWidth=".15" onClick={()=>onSelect(c)}><title>{c.id}</title></rect></g>)}
 <g opacity={changed?.2:1}>{visible.filter(c=>c.ports.length>=2&&!c.size_m).map(c=><polyline key={c.id} points={c.ports.map(p=>`${nodes[p][0]},${nodes[p][1]}`).join(' ')} stroke={color(c)} strokeWidth={c.kind==='pipe'?.045:.08} fill="none" onClick={()=>onSelect(c)}><title>{c.id} · {c.kind}{changed?' · last applied route':''}</title></polyline>)}</g>
 <g className="handover-points" opacity={changed?.25:1}>{handovers.map(h=><g key={h.id}><title>{h.note}</title>
  {h.to&&<line x1={h.point[0]} y1={h.point[1]} x2={h.to[0]} y2={h.to[1]} stroke="#a05633" strokeWidth=".07" strokeDasharray=".5 .35" opacity=".55"/>}
  <circle cx={h.point[0]} cy={h.point[1]} r={labelSize*.3} fill="#f5f8f5" stroke="#a05633" strokeWidth=".11"/></g>)}</g>
 {editing&&zones.map((zone,i)=>{if(!baseZones[i].bounds_m)return null;const b=baseZones[i].bounds_m!,points=[[b.min[0],b.min[1]],[b.max[0],b.min[1]],[b.max[0],b.max[1]],[b.min[0],b.max[1]]].map(p=>transformPoint([...p,0],baseZones[i],zone,config));const min=[Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1]))],max=[Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))],delta=offsets[zone.id]||[0,0];return <g key={zone.id} transform={`translate(${delta[0]} ${delta[1]})`} className={'zone-handle '+(selected?.id===zone.id?'selected':'')} role="button" tabIndex={0} aria-disabled={locked} aria-label={`Move ${zone.label}`} onPointerDown={e=>start(e,zone)} onClick={e=>{e.stopPropagation();setSelectedZone(zone.id);}} onKeyDown={e=>{if(locked)return;const step:Record<string,number[]>={ArrowLeft:[-.25,0],ArrowRight:[.25,0],ArrowUp:[0,-.25],ArrowDown:[0,.25]};const d=step[e.key];if(!d)return;e.preventDefault();setSelectedZone(zone.id);onMove?.(zone,[zone.anchor_m[0]+d[0],zone.anchor_m[1]+d[1],zone.anchor_m[2]||0]);}}>
 <rect x={min[0]-.25} y={min[1]-.25} width={max[0]-min[0]+.5} height={max[1]-min[1]+.5} fill="transparent" stroke="#254f73" strokeDasharray=".45 .25" strokeWidth=".06"/>
 <rect x={min[0]-.25} y={min[1]-labelSize*1.65} width={Math.max(6,zone.label.length*labelSize*.62)} height={labelSize*1.4} rx=".12" fill="#254f73"/><text x={min[0]} y={min[1]-labelSize*.55} fontSize={labelSize} fill="white">{zone.label}</text></g>;})}
 </svg></div>;
}
