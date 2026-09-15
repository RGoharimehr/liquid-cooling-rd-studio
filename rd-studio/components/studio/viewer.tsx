'use client';
import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import PlanEditor,{type EditableZone,type ZoneEdit} from './plan-editor';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
export type Component={id:string;kind:string;service:string;ports:string[];attachment?:boolean;center_m?:number[];size_m?:number[];rotation_deg?:number;port_details?:{circuit_id:string}[];nominal_size_in?:number;mesh:{vertices:number[][];faces:number[][]}};
export type Graph={components:Component[];nodes:{id:string;xyz_m:number[]}[];metadata:Record<string,any>;layout:{clearance_zones:{id:string;center_m:number[];size_m:number[];rotation_deg?:number}[];network_power_W:number;editable_zones?:EditableZone[]};edges:any[]};
// Semantic colours for the attention roll-up, deliberately outside the service
// palette so a flag never reads as a fluid. Applied as an emissive tint, so the
// component keeps its own colour and the flag sits on top of it.
export const ATTENTION_COLOR:Record<string,string>={undersized:'#b03a2e',oversized:'#2e6fb0',missing_information:'#a8791c',clash:'#8e2f5e',unserved:'#7a1f1f'};
const CATEGORY_RANK=['clash','unserved','undersized','missing_information','oversized'];
export type AttentionMode='off'|'specific'|'all';
/** component id -> worst category, from metadata.attention. */
export const attentionIndex=(graph:Graph,mode:AttentionMode)=>{
 const index=new Map<string,string>();
 if(mode==='off')return index;
 const data=graph.metadata?.attention;if(!data)return index;
 const put=(id:string,category:string)=>{
  const held=index.get(id);
  if(!held||CATEGORY_RANK.indexOf(category)<CATEGORY_RANK.indexOf(held))index.set(id,category);
 };
 for(const [id,entry] of Object.entries<any>(data.components||{}))for(const category of entry.categories)put(id,category);
 // Systemic findings land on every component of a kind. They are one project
 // gap, not N problems, so they are opt-in rather than shown by default.
 if(mode==='all')for(const item of data.systemic||[])for(const id of item.component_ids||[])put(id,item.category);
 return index;
};
export const color=(c:Component)=>c.kind==='compute_rack'?'#304956':c.kind==='network_rack'?'#9174b0':(c.kind==='cdu_enclosure'||c.kind==='cdu')?'#6498a6':c.kind==='chiller'?'#748498':c.kind==='cooling_tower'?'#879fa8':c.attachment?'#a1aba4':c.service==='CWS'?'#497dc0':c.service==='TCS'?'#0c9993':'#d2913e';
/** A tinted mesh is easy to miss among hundreds of boxes. Pins are billboards
 * drawn over everything, so a flagged object can be found from any angle even
 * when it sits inside a row. One canvas per colour, shared by every pin. */
const PIN_CACHE=new Map<string,THREE.Texture>();
const pinTexture=(hex:string)=>{
 const held=PIN_CACHE.get(hex);if(held)return held;
 const canvas=document.createElement('canvas');canvas.width=canvas.height=64;
 const ctx=canvas.getContext('2d')!;
 ctx.beginPath();ctx.arc(32,32,25,0,Math.PI*2);ctx.fillStyle=hex;ctx.fill();
 ctx.lineWidth=7;ctx.strokeStyle='#fbfdfa';ctx.stroke();
 const texture=new THREE.CanvasTexture(canvas);PIN_CACHE.set(hex,texture);return texture;
};
/** Bounds over every component, visible or not, so the framing and the grid do
 * not move when a layer is toggled. */
const layoutBounds=(graph:Graph)=>{
 const box=new THREE.Box3();const point=new THREE.Vector3();
 for(const comp of graph.components)for(const v of comp.mesh?.vertices||[])box.expandByPoint(point.set(v[0],v[1],v[2]));
 if(box.isEmpty())box.setFromCenterAndSize(new THREE.Vector3(),new THREE.Vector3(10,10,10));
 return box;
};
export default function Viewer({graph,draftConfig,mode,clearances,accessories,attention='specific',highlight,onSelect,editing=false,editLocked=false,editRevision=0,onZoneMove,onZoneEdit}:{draftConfig?:Record<string,any>;attention?:AttentionMode;highlight?:string[];editing?:boolean;editLocked?:boolean;editRevision?:number;onZoneMove?:(zone:EditableZone,point:number[])=>void;onZoneEdit?:(zone:EditableZone,edit:ZoneEdit)=>void;graph:Graph;mode:'3d'|'plan';clearances:boolean;accessories:boolean;onSelect:(c:Component)=>void}){
 const mount=useRef<HTMLDivElement>(null);const [error,setError]=useState('');
 // The renderer, camera and controls outlive a content rebuild. Recreating them
 // whenever a layer was toggled threw away the orbit and zoom the reviewer had
 // set, which made every switch feel like it reset the model.
 const stage=useRef<{scene:THREE.Scene;camera:THREE.PerspectiveCamera;controls:OrbitControls;content:THREE.Group;solids:THREE.Object3D[]}|null>(null);
 const framed=useRef('');
 const selectRef=useRef(onSelect);selectRef.current=onSelect;

 useEffect(()=>{
  if(mode!=='3d'||!mount.current)return;
  const el=mount.current;let renderer:THREE.WebGLRenderer;
  try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});}catch{setError('3D is unavailable on this device. Switch to Plan to review the layout.');return;}
  setError('');renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));el.appendChild(renderer.domElement);
  const scene=new THREE.Scene();scene.background=new THREE.Color('#f1f5f0');scene.add(new THREE.HemisphereLight(0xffffff,0x769088,2.8));const light=new THREE.DirectionalLight(0xffffff,2);light.position.set(8,-10,20);scene.add(light);
  const content=new THREE.Group();scene.add(content);
  const camera=new THREE.PerspectiveCamera(40,1,.05,1000);camera.up.set(0,0,1);
  const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;
  stage.current={scene,camera,controls,content,solids:[]};framed.current='';
  const resize=()=>{const w=el.clientWidth,h=el.clientHeight;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();};const observer=new ResizeObserver(resize);observer.observe(el);resize();
  let frame:number;const render=()=>{controls.update();renderer.render(scene,camera);frame=requestAnimationFrame(render);};render();
  let down=[0,0];const pointerdown=(e:PointerEvent)=>{down=[e.clientX,e.clientY]};
  const pick=(e:PointerEvent)=>{
   if(Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;
   const r=renderer.domElement.getBoundingClientRect();const ray=new THREE.Raycaster();
   ray.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);
   const hit=ray.intersectObjects(stage.current?.solids||[])[0];
   if(hit)selectRef.current(hit.object.userData.component);
  };
  renderer.domElement.addEventListener('pointerdown',pointerdown);renderer.domElement.addEventListener('pointerup',pick);
  return()=>{
   cancelAnimationFrame(frame);observer.disconnect();controls.dispose();stage.current=null;
   scene.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>m.dispose());}});
   renderer.dispose();renderer.domElement.remove();
  };
 },[mode]);

 useEffect(()=>{
  const current=stage.current;if(mode!=='3d'||!current)return;
  const {camera,controls,content}=current;
  for(const child of [...content.children]){
   content.remove(child);
   child.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>m.dispose());}});
  }
  const solids:THREE.Object3D[]=[];current.solids=solids;
  const flags=attentionIndex(graph,attention);
  const pinned=new Set(highlight||[]);
  // A pin per flagged object would put hundreds of dots over a systemic gap,
  // which hides the handful that are specific. Tint carries the extent; pins
  // carry the ones a reviewer has to go and find.
  const data=graph.metadata?.attention;
  const specific=new Set(Object.keys(data?.components||{}));
  const bounds=layoutBounds(graph),center=bounds.getCenter(new THREE.Vector3()),size=bounds.getSize(new THREE.Vector3());
  const span=Math.max(size.x,size.y,10);
  const focus=new THREE.Box3();
  for(const comp of graph.components){
   const m=comp.mesh;if(!m?.vertices.length)continue;
   const hidden=comp.attachment&&!accessories;
   const flagged=flags.get(comp.id);
   const showPin=pinned.size?pinned.has(comp.id):(attention!=='off'&&specific.has(comp.id));
   if(hidden&&!showPin)continue;
   const box=new THREE.Box3();const point=new THREE.Vector3();
   for(const v of m.vertices)box.expandByPoint(point.set(v[0],v[1],v[2]));
   if(showPin){
    focus.union(box);
    const category=flagged||data?.components?.[comp.id]?.categories?.[0]||'missing_information';
    // Constant on screen rather than in metres. A pin scaled in world units is
    // a few pixels when the whole hall is in frame - which is exactly when a
    // reviewer is looking for it - and covers the fitting once they arrive.
    const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:pinTexture(ATTENTION_COLOR[category]||'#a8791c'),depthTest:false,transparent:true,sizeAttenuation:false}));
    sprite.scale.set(.03,.03,1);
    sprite.position.set((box.min.x+box.max.x)/2,(box.min.y+box.max.y)/2,box.max.z+Math.max(span*.01,.3));
    sprite.renderOrder=20;sprite.userData.component=comp;content.add(sprite);solids.push(sprite);
   }
   if(hidden)continue;
   const positions:number[]=[];for(const face of m.faces)for(let j=1;j<face.length-1;j++)for(const index of [face[0],face[j],face[j+1]])positions.push(...m.vertices[index]);
   const geom=new THREE.BufferGeometry();geom.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geom.computeVertexNormals();
   const transparent=comp.kind==='compute_rack'&&!flagged;
   const mat=new THREE.MeshStandardMaterial({color:color(comp),roughness:.65,metalness:.12,transparent,opacity:transparent?.80:1,side:THREE.DoubleSide,
    ...(flagged?{emissive:new THREE.Color(ATTENTION_COLOR[flagged]),emissiveIntensity:specific.has(comp.id)?1:.7}:{})});
   const mesh=new THREE.Mesh(geom,mat);mesh.userData.component=comp;content.add(mesh);solids.push(mesh);
  }
  if(clearances)for(const zone of graph.layout.clearance_zones){const geom=new THREE.BoxGeometry(...zone.size_m as [number,number,number]);const mesh=new THREE.Mesh(geom,new THREE.MeshBasicMaterial({color:'#d6aa50',transparent:true,opacity:.23}));mesh.position.set(...zone.center_m as [number,number,number]);mesh.rotation.z=(zone.rotation_deg||0)*Math.PI/180;content.add(mesh);}
  const grid=new THREE.GridHelper(Math.ceil(span+20),Math.ceil(span+20),0xbacbc1,0xdce5dc);grid.rotation.x=Math.PI/2;grid.position.set(center.x,center.y,-.04);content.add(grid);
  // Frame on a design whose extent actually changed, and on a request to show
  // where a finding is. Never on a layer toggle: the bounds above come from
  // every component, visible or not, so toggling one cannot move the camera.
  const key=[center.x,center.y,center.z,size.x,size.y,size.z].map(v=>v.toFixed(2)).join(',');
  if(framed.current!==key){
   framed.current=key;
   camera.position.set(center.x+span*.85,center.y-span*.9,span*.95);controls.target.copy(center);controls.update();
  }
  if(pinned.size&&!focus.isEmpty()){
   const at=focus.getCenter(new THREE.Vector3()),reach=Math.max(focus.getSize(new THREE.Vector3()).length(),4);
   camera.position.set(at.x+reach*.9,at.y-reach*.95,at.z+reach*.8);controls.target.copy(at);controls.update();
  }
 },[graph.components,graph.nodes,graph.layout,graph.metadata,mode,clearances,accessories,attention,highlight]);

 if(mode==='plan')return <PlanEditor graph={graph} draftConfig={draftConfig} clearances={clearances} accessories={accessories} onSelect={onSelect} editing={editing} locked={editLocked} revision={editRevision} onMove={onZoneMove} onEdit={onZoneEdit}/>;
 return <div className="three-view" ref={mount} role="img" aria-label="Interactive three-dimensional network. Drag to orbit, scroll to zoom, click a component to inspect.">{error&&<p className="render-error">{error}</p>}</div>
}
