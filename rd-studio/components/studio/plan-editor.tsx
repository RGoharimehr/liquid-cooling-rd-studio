'use client';
import {useEffect,useRef,useState} from 'react';
import type {Component,Graph} from './viewer';
import {color} from './viewer';
export type EditableZone={id:string;kind:string;pod?:number;label:string;anchor_m:number[];anchor_layout_m?:number[];bounds_m:{min:number[];max:number[]}|null;rotation_deg:number;flip_x?:boolean;flip_y?:boolean};
export type ZoneEdit={anchor_m?:number[];rotation_deg?:number;flip_x?:boolean;flip_y?:boolean};
export default function PlanEditor({graph,clearances,accessories,onSelect,editing,onMove,onEdit}:{graph:Graph;clearances:boolean;accessories:boolean;onSelect:(c:Component)=>void;editing:boolean;onMove?:(zone:EditableZone,point:number[])=>void;onEdit?:(zone:EditableZone,edit:ZoneEdit)=>void}){
 const svg=useRef<SVGSVGElement>(null),drag=useRef<{zone:EditableZone;start:number[];offset:number[]}|null>(null);
 const [selectedZone,setSelectedZone]=useState('');
 const [offsets,setOffsets]=useState<Record<string,number[]>>({});
 useEffect(()=>setOffsets({}),[graph]);
 const visible=graph.components.filter(c=>!c.attachment||accessories);const points=visible.flatMap(c=>c.mesh?.vertices||[]);
 const config=graph.metadata.config||{};const fw=Number(config.site_footprint_width_m||0),fd=Number(config.site_footprint_depth_m||0),fx=Number(config.site_footprint_origin_x_m||0),fy=Number(config.site_footprint_origin_y_m||0);
 points.push([0,0,0]);
 if(fw&&fd)points.push([fx,fy,0],[fx+fw,fy+fd,0]);
 const minx=points.reduce((v,p)=>Math.min(v,p[0]),Infinity)-4,miny=points.reduce((v,p)=>Math.min(v,p[1]),Infinity)-4,maxx=points.reduce((v,p)=>Math.max(v,p[0]),-Infinity)+4,maxy=points.reduce((v,p)=>Math.max(v,p[1]),-Infinity)+4;
 const labelSize=Math.max(.9,(maxy-miny)/45);
 const nodes=Object.fromEntries(graph.nodes.map(n=>[n.id,n.xyz_m]));const zones=(graph.layout.editable_zones||[]) as EditableZone[];
 const at=(e:React.PointerEvent)=>{const point=new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.current!.getScreenCTM()!.inverse());return [point.x,point.y];};
 const start=(e:React.PointerEvent,zone:EditableZone)=>{if(!editing||!onMove)return;setSelectedZone(zone.id);e.preventDefault();e.stopPropagation();svg.current!.setPointerCapture(e.pointerId);drag.current={zone,start:at(e),offset:offsets[zone.id]||[0,0]};};
 const move=(e:React.PointerEvent)=>{const d=drag.current;if(!d)return;const p=at(e);setOffsets(old=>({...old,[d.zone.id]:[Math.round((d.offset[0]+p[0]-d.start[0])*4)/4,Math.round((d.offset[1]+p[1]-d.start[1])*4)/4]}));};
 const finish=(e:React.PointerEvent)=>{const d=drag.current;if(!d)return;const p=at(e);const delta=[Math.round((d.offset[0]+p[0]-d.start[0])*4)/4,Math.round((d.offset[1]+p[1]-d.start[1])*4)/4];drag.current=null;svg.current!.releasePointerCapture(e.pointerId);onMove?.(d.zone,[d.zone.anchor_m[0]+delta[0],d.zone.anchor_m[1]+delta[1],0]);};
 const selected=zones.find(z=>z.id===selectedZone)||zones[0];
 return <div className="plan-editor-shell">{editing&&selected&&<div className="zone-edit-tools"><label>Zone <select aria-label="Equipment zone" value={selected.id} onChange={e=>setSelectedZone(e.target.value)}>{zones.map(z=><option key={z.id} value={z.id}>{z.label}</option>)}</select></label><button onClick={()=>onEdit?.(selected,{rotation_deg:(selected.rotation_deg||0)+90})}>Rotate 90°</button><button onClick={()=>onEdit?.(selected,{flip_x:!selected.flip_x})}>Flip X</button><button onClick={()=>onEdit?.(selected,{flip_y:!selected.flip_y})}>Flip Y</button><span>{selected.anchor_m.slice(0,2).map(n=>n.toFixed(2)).join(', ')} m · {selected.rotation_deg||0}°</span></div>}<svg ref={svg} className={'actual-plan '+(editing?'editing':'')} viewBox={`${minx} ${miny} ${maxx-minx} ${maxy-miny}`} role={editing?'group':'img'} aria-label={editing?'Arrange cooling pods and equipment zones; drag a labelled handle or use arrow keys, then Apply design':'Plan of the generated network, in metres'} onPointerMove={move} onPointerUp={finish} onPointerCancel={()=>{drag.current=null;setOffsets({});}}>
 <g stroke="#344759" strokeWidth=".08"><path d="M -1 0 H 1 M 0 -1 V 1"/><text x=".4" y="-.4" stroke="none" fill="#344759" fontSize={labelSize*.7}>World 0, 0</text></g>
 {fw>0&&fd>0&&<rect x={fx} y={fy} width={fw} height={fd} fill="none" stroke="#a05633" strokeWidth=".10" strokeDasharray=".6 .3"><title>Declared site footprint</title></rect>}
 {clearances&&graph.layout.clearance_zones.map(z=><rect transform={`rotate(${z.rotation_deg||0} ${z.center_m[0]} ${z.center_m[1]})`} key={z.id} x={z.center_m[0]-z.size_m[0]/2} y={z.center_m[1]-z.size_m[1]/2} width={z.size_m[0]} height={z.size_m[1]} fill="#dec780" opacity=".3"/>)}
 {visible.filter(c=>c.center_m&&c.size_m).map(c=><rect transform={`rotate(${c.rotation_deg||0} ${c.center_m![0]} ${c.center_m![1]})`} key={c.id} x={c.center_m![0]-c.size_m![0]/2} y={c.center_m![1]-c.size_m![1]/2} width={c.size_m![0]} height={c.size_m![1]} fill={color(c)} onClick={()=>onSelect(c)}><title>{c.id}</title></rect>)}
 {visible.filter(c=>c.ports.length>=2&&!c.size_m).map(c=><polyline key={c.id} points={c.ports.map(p=>`${nodes[p][0]},${nodes[p][1]}`).join(' ')} stroke={color(c)} strokeWidth={c.kind==='pipe'?.045:.08} fill="none" onClick={()=>onSelect(c)}><title>{c.id} · {c.kind}</title></polyline>)}
 {editing&&zones.map(zone=>{if(!zone.bounds_m)return null;const {min,max}=zone.bounds_m,delta=offsets[zone.id]||[0,0];return <g key={zone.id} transform={`translate(${delta[0]} ${delta[1]})`} className="zone-handle" role="button" tabIndex={0} aria-label={`Move ${zone.label}`} onPointerDown={e=>start(e,zone)} onKeyDown={e=>{const arrows:Record<string,number[]>={ArrowLeft:[-.25,0],ArrowRight:[.25,0],ArrowUp:[0,-.25],ArrowDown:[0,.25]};const change=arrows[e.key];if(!change)return;e.preventDefault();const next=[delta[0]+change[0],delta[1]+change[1]];setOffsets(old=>({...old,[zone.id]:next}));onMove?.(zone,[zone.anchor_m[0]+next[0],zone.anchor_m[1]+next[1],0]);}}>
 <rect x={min[0]-.25} y={min[1]-.25} width={max[0]-min[0]+.5} height={max[1]-min[1]+.5} fill="transparent" stroke="#254f73" strokeDasharray=".45 .25" strokeWidth=".06"/>
 <rect x={min[0]-.25} y={min[1]-labelSize*1.65} width={Math.max(6,zone.label.length*labelSize*.62)} height={labelSize*1.4} rx=".12" fill="#254f73"/><text x={min[0]} y={min[1]-labelSize*.55} fontSize={labelSize} fill="white">{zone.label}{delta.some(Boolean)?' · pending':''}</text></g>;})}
 </svg></div>
}
