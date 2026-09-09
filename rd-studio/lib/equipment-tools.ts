'use client';
import {useEffect,useRef} from 'react';
export function equipmentSnapshot(requirements:any,report:any,pending:boolean,input:unknown){
 if(input===null||typeof input!=='object'||Array.isArray(input)||Object.keys(input).some(k=>k!=='component_ids'))throw Error('Expected an object with optional component_ids.');
 const ids=(input as any).component_ids;
 if(ids!==undefined&&(!Array.isArray(ids)||ids.length>50||ids.some(x=>typeof x!=='string')))throw Error('component_ids must be an array of at most 50 strings.');
 const rows=requirements?.requirements||[];
 if(ids?.some((id:string)=>!rows.some((r:any)=>r.component_id===id)))throw Error('Unknown component ID for the applied design.');
 const selected=ids?.length?rows.filter((r:any)=>ids.includes(r.component_id)):rows.slice(0,20);
 const allowed=new Set(selected.map((r:any)=>r.component_id));
 return {pending_parameters:pending,config_hash:requirements?.config_hash||null,ready_for_matching:requirements?.ready_for_matching||false,
  status:report?.status||'not_searched',catalogue:report?.catalogue||null,summary:report?.summary||requirements?.summary,
  requirements:selected,candidates:(report?.items||[]).filter((r:any)=>allowed.has(r.component_id)),
  omitted_components:rows.length-selected.length,scope:'Read-only applied RD duties and headless finder candidates; pending parameters are not calculated.'};
}
export function useEquipmentTools(requirements:any,report:any,pending:boolean){
 const latest=useRef({requirements,report,pending});latest.current={requirements,report,pending};
 useEffect(()=>{
  const context=(document as any).modelContext;if(!context?.registerTool)return;
  const lifecycle=new AbortController();
  const tool={name:'rd_get_equipment_matches',title:'Read RD equipment requirements and matches',description:'Read calculated duties, standard nominal sizes, circuit identities and current headless finder candidates for the applied reference design. Optional component_ids select up to 50 equipment items; omitted IDs return the first 20.',inputSchema:{type:'object',properties:{component_ids:{type:'array',maxItems:50,items:{type:'string'}}},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},execute(input:unknown){const s=latest.current;return equipmentSnapshot(s.requirements,s.report,s.pending,input);}};
  try{Promise.resolve(context.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch{}
  return ()=>lifecycle.abort();
 },[]);
}
