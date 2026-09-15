'use client';
import {useState} from 'react';
import {ChevronDown,Crosshair,X} from 'lucide-react';
import {ATTENTION_COLOR,type Graph} from './viewer';
const friendly=(s:string)=>s.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
type Finding={key:string;category:string;severity:string;scope:string;detail:string;fix?:string;count:number;ids:string[]};
/** The roll-up the model colours, read as a list a reviewer can work through.
 *
 * Colouring an object says something is wrong with it; it cannot say what, and
 * it cannot say where the input that clears it lives. Systemic findings are the
 * larger half of the answer and are not drawn by default, so a panel that only
 * mirrored the 3D flags would leave most of them invisible. This lists both. */
export default function AttentionPanel({graph,highlight,onHighlight}:{graph:Graph;highlight?:string[];onHighlight:(ids:string[]|undefined)=>void}){
 const [open,setOpen]=useState(false);
 const data=graph.metadata?.attention;
 if(!data)return null;
 const specific:Finding[]=[];
 for(const [id,entry] of Object.entries<any>(data.components||{}))for(const flag of entry.flags||[])
  specific.push({key:id+'/'+flag.code,category:flag.category,severity:flag.severity,scope:id,
                 detail:flag.detail,fix:flag.resolved_by,count:1,ids:[id]});
 const systemic:Finding[]=(data.systemic||[]).map((item:any)=>({
  key:'systemic/'+item.code+'/'+item.scope,category:item.category,severity:item.severity,scope:item.scope,
  detail:item.detail,fix:item.clears_when,count:item.components,ids:item.component_ids||[]}));
 const total=specific.length+systemic.length;
 if(!total)return <p className="attention-clear">No component in this design is flagged for attention.</p>;
 const active=(f:Finding)=>highlight?.length===f.ids.length&&highlight[0]===f.ids[0];
 const row=(f:Finding)=><div className="attention-row" key={f.key}>
  <span className="attention-chip" style={{background:ATTENTION_COLOR[f.category]||'#8a8a8a'}}/>
  <div>
   <strong>{friendly(f.category)} · {f.scope}{f.count>1?` · ${f.count} objects`:''}</strong>
   <p>{f.detail}</p>
   {f.fix&&<p className="attention-fix">Where to fix: {f.fix}</p>}
  </div>
  <button onClick={()=>onHighlight(active(f)?undefined:f.ids)} aria-pressed={active(f)}>
   {active(f)?<><X size={11}/> Clear</>:<><Crosshair size={11}/> Show in model</>}
  </button>
 </div>;
 const counts=data.summary?.by_severity||{};
 return <div className="attention-panel">
  <button className="attention-toggle" onClick={()=>setOpen(v=>!v)} aria-expanded={open}>
   <span className="attention-chip" style={{background:counts.blocking?ATTENTION_COLOR.clash:counts.review?ATTENTION_COLOR.undersized:ATTENTION_COLOR.missing_information}}/>
   <span>Needs attention · {specific.length} on specific components, {systemic.length} project-wide</span>
   <ChevronDown size={13} style={{marginLeft:'auto',transform:open?'rotate(180deg)':undefined}}/>
  </button>
  {open&&<div className="attention-list">
   {specific.length>0&&<>
    <p className="attention-heading">On specific components</p>
    {specific.map(row)}
   </>}
   {systemic.length>0&&<>
    <p className="attention-heading">Project-wide · one gap affecting many objects, not many problems</p>
    {systemic.map(row)}
   </>}
  </div>}
 </div>;
}
