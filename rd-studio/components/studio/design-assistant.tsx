'use client';
import {useEffect,useRef,useState} from 'react';
import {Bot,LoaderCircle,Send,Square,ShieldCheck} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Textarea} from '@/components/ui/textarea';
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from '@/components/ui/select';
import {Sheet,SheetContent,SheetHeader,SheetTitle,SheetDescription} from '@/components/ui/sheet';
import {DEFAULT_ENDPOINT,DEFAULT_MODEL,askLocal,buildContext,collectFindings,configStamp,localModels,proposedConfig,reviewDesign,type AgentReply,type DesignConfig,type DesignState,type Parameter} from '@/lib/design-agent';
type Proposal=ReturnType<typeof proposedConfig>;
type Trial={status:'PASS'|'FAIL';findings:string[];count:number;compute:number;cdus:number;hash:string};
type Turn={question:string;answer:AgentReply;stamp:string;graphHash:string;proposal:Proposal|null;trial?:Trial;staged?:boolean;error?:string};
export default function DesignAssistant({open,onOpenChange,config,graph,fields,dirty,designBusy,selectedId,onStage}:{open:boolean;onOpenChange:(v:boolean)=>void;config:DesignConfig;graph:DesignState|null;fields:Parameter[];dirty:boolean;designBusy:boolean;selectedId?:string|null;onStage:(next:DesignConfig,stamp:string,hash:string)=>void}){
 const [endpoint,setEndpoint]=useState(DEFAULT_ENDPOINT),[model,setModel]=useState(DEFAULT_MODEL),[models,setModels]=useState<{name:string;digest:string}[]>([]),[connected,setConnected]=useState(false),[question,setQuestion]=useState(''),[turns,setTurns]=useState<Turn[]>([]),[checks,setChecks]=useState<string[]>([]),[busy,setBusy]=useState(false),[phase,setPhase]=useState(''),[error,setError]=useState('');
 const abort=useRef<AbortController|null>(null),request=useRef(0),trialWorker=useRef<Worker|null>(null),trialReject=useRef<((e:Error)=>void)|null>(null),timer=useRef<ReturnType<typeof setTimeout>|null>(null);
 const stamp=configStamp(config),graphHash=String(graph?.metadata.config_hash||'');
 const latest=useRef({stamp,graphHash});latest.current={stamp,graphHash};
 const cancel=()=>{request.current++;abort.current?.abort();trialWorker.current?.terminate();trialWorker.current=null;trialReject.current?.(new Error('Cancelled'));trialReject.current=null;if(timer.current)clearTimeout(timer.current);setBusy(false);setPhase('Cancelled. Your design is unchanged.');};
 useEffect(()=>()=>{abort.current?.abort();trialWorker.current?.terminate();trialReject.current?.(new Error('Assistant closed'));if(timer.current)clearTimeout(timer.current);},[]);
 const connect=async()=>{
  const id=++request.current;setBusy(true);setError('');setPhase('Checking local models…');const controller=new AbortController();abort.current=controller;timer.current=setTimeout(()=>controller.abort(),12000);
  try{const available=await localModels(endpoint,controller.signal);if(id!==request.current)return;setModels(available);if(!available.length)throw Error('No downloaded local model was found. Run the local setup, then connect again.');setModel(available.some(x=>x.name===model)?model:available[0].name);setConnected(true);setPhase('Connected to Ollama on this computer.');}
  catch(err){if(id!==request.current)return;setConnected(false);setError(err instanceof Error&&err.name!=='AbortError'?err.message:'Local connection timed out. Start Ollama, check allowed origins, and allow local-network access in your browser.');setPhase('Local AI is not connected. Design checks remain available.');}
  finally{if(id===request.current){if(timer.current)clearTimeout(timer.current);setBusy(false);}}
 };
 const trial=async(next:DesignConfig,id:number):Promise<Trial>=>new Promise((resolve,reject)=>{
  const worker=new Worker('/engine-worker.js?release=20260910-zone-session-v2',{type:'module'});trialWorker.current=worker;trialReject.current=reject;
  const finish=()=>{worker.terminate();trialWorker.current=null;trialReject.current=null;};
  worker.onmessage=({data})=>{if(id!==request.current||data.requestId!==id)return;if(data.type==='status'){setPhase('Checking proposal · '+data.message);return;}if(data.type==='error'){finish();reject(new Error(data.message));return;}if(data.type==='result'){const g=data.result.graph as DesignState;const findings=collectFindings(g).filter(x=>x.status==='FAIL');finish();resolve({status:data.result.exportable?'PASS':'FAIL',findings:findings.slice(0,6).map(x=>x.check+': '+JSON.stringify(x.actual)),count:findings.length,compute:g.components.filter(x=>x.kind==='compute_rack').length,cdus:g.components.filter(x=>x.kind==='cdu').length,hash:data.result.config_hash});}};
  worker.onerror=e=>{finish();reject(new Error(e.message||'The proposal checker could not start.'));};worker.postMessage({requestId:id,action:'preview',config:next});
 });
 const optimize=async()=>{
  if(busy||designBusy||!graph||config.plant_type==='boundary')return;
  const id=++request.current,base=structuredClone(config),baseStamp=stamp,baseHash=graphHash;
  setBusy(true);setError('');setPhase('Testing plant routes with the generator…');
  const worker=new Worker('/engine-worker.js?release=20260910-zone-session-v2',{type:'module'});trialWorker.current=worker;
  const finish=()=>{worker.terminate();trialWorker.current=null;if(timer.current)clearTimeout(timer.current);setBusy(false);};
  timer.current=setTimeout(()=>{finish();setError('Route search timed out. Reduce the design size or cancel and adjust placement.');},180000);
  worker.onerror=e=>{finish();setError(e.message||'Route search could not start.');};
  worker.onmessage=({data})=>{
   if(id!==request.current||data.requestId!==id)return;
   if(data.type==='status'){setPhase(data.message);return;}
   if(data.type==='error'){finish();setError(data.message);return;}
   if(data.type!=='optimization')return;
   finish();const r=data.proposal;
   if(latest.current.stamp!==baseStamp||latest.current.graphHash!==baseHash){setError('The design changed during the search. Run it again for the current inputs.');return;}
   const changes=r.status==='IMPROVED'?Object.entries(r.config).filter(([k,v])=>configStamp(v)!==configStamp(base[k])).map(([parameter,value])=>({parameter,value_json:JSON.stringify(value),reason:'Measured shorter plant pipes after generator validation.'})):[];
   const answer:AgentReply={summary:r.summary+' Routed pipe: '+r.before.routed_pipe_length_m+' → '+r.after.routed_pipe_length_m+' m (plant '+r.before.plant_pipe_length_m+' → '+r.after.plant_pipe_length_m+'); elbows: '+r.before.elbows+' → '+r.after.elbows+'.',changes,source_ids:[],qualifications:[r.scope,...r.trials.filter((t:any)=>!t.accepted).map((t:any)=>t.reason||'A candidate was rejected by the geometry checks.')]};
   const proposal=changes.length?proposedConfig(base,changes,fields):null;
   setTurns(old=>[...old.slice(-7),{question:'Find shorter plant piping',answer,stamp:baseStamp,graphHash:baseHash,proposal,...(proposal?{trial:{status:'PASS' as const,findings:[],count:0,compute:graph.components.filter(c=>c.kind==='compute_rack').length,cdus:graph.components.filter(c=>c.kind==='cdu').length,hash:r.config_hash}}:{})}]);setPhase(r.summary);
  };
  worker.postMessage({requestId:id,action:'optimize_routes',config:base});
 };
 const ask=async(text=question)=>{
  if(/optim|shorter|reduce.*pipe|pipe.*rout/i.test(text)){void optimize();return;}
  if(!text.trim()||!connected||busy||designBusy||!fields.length)return;
  const id=++request.current,base=structuredClone(config),baseStamp=stamp,baseHash=graphHash,context={...buildContext(base,graph,fields,text,dirty,selectedId),recent_conversation:turns.slice(-3).map(t=>({request:t.question,answer:t.answer.summary.slice(0,1600),proposed_changes:t.answer.changes,staged:!!t.staged,based_on_current_design:t.stamp===stamp&&t.graphHash===graphHash}))},controller=new AbortController();abort.current=controller;
  setBusy(true);setError('');setPhase('Local model is reviewing the design…');setQuestion('');
  let timeout=false;timer.current=setTimeout(()=>{timeout=true;controller.abort();trialWorker.current?.terminate();trialReject.current?.(new Error('The proposal check timed out. Try fewer changes.'));},240000);
  let turn:Turn|null=null;
  try{
   let answer:AgentReply|null=null,proposal:Proposal|null=null,repair='';
   for(let attempt=0;attempt<2;attempt++){
    setPhase(attempt?'Local model is correcting an invalid proposal…':'Local model is reviewing the design…');
    try{answer=await askLocal(endpoint,model,text+repair,context,controller.signal);if(id!==request.current)return;proposal=answer.changes.length?proposedConfig(base,answer.changes,fields):null;break;}
    catch(err){if(controller.signal.aborted||attempt===1)throw err;repair='\nYour previous response was rejected by the validator: '+String(err instanceof Error?err.message:err)+'. Return a corrected complete response to the original request. Use [] for automatic grouping and include every requested equipment count.';}
   }
   if(!answer)throw Error('The local model returned no usable answer.');
   turn={question:text,answer,stamp:baseStamp,graphHash:baseHash,proposal};
   if(latest.current.stamp!==baseStamp||latest.current.graphHash!==baseHash){turn.error='The design changed during this request. Ask again using the current parameters.';setTurns(old=>[...old.slice(-7),turn!]);setPhase('Response belongs to an earlier design.');return;}
   if(proposal?.changes.length){setPhase('Checking the proposed design with the generator…');try{turn.trial=await trial(proposal.config,id);}catch(err){turn.error=String(err instanceof Error?err.message:err);}}
   if(id!==request.current)return;setTurns(old=>[...old.slice(-7),turn!]);setPhase(turn.error?'Proposal could not be validated.':turn.proposal?.changes.length?'Proposal checked. Review the changes below.':'Local answer ready.');
  }catch(err){if(id!==request.current)return;setError(timeout?'Local AI timed out. Try a shorter request or smaller model.':err instanceof Error&&err.name==='AbortError'?'Request cancelled.':String(err instanceof Error?err.message:err));setQuestion(text);setPhase('No parameters were changed.');}
  finally{if(id===request.current){if(timer.current)clearTimeout(timer.current);setBusy(false);abort.current=null;}}
 };
 return <Sheet open={open} onOpenChange={v=>{if(!v&&busy)cancel();onOpenChange(v);}}><SheetContent className="design-assistant"><SheetHeader><SheetTitle><Bot size={20}/> Design actions</SheetTitle><SheetDescription>Run a checked route search without a language model. Optional local AI can propose parameter changes; the generator validates them before staging.</SheetDescription></SheetHeader>
 <div className="agent-body"><div className="agent-actions"><Button disabled={busy||designBusy||!graph||config.plant_type==='boundary'} onClick={()=>void optimize()}>Try shorter plant routes</Button><p>Compares three corridor alternatives. Shows measured pipe length and elbows; only a candidate passing the generator checks can be staged.</p>{config.plant_type==='boundary'&&<p>Select an air-cooled or water-cooled plant first.</p>}</div><div className="agent-privacy"><ShieldCheck size={16}/><span>Ollama on your computer. Questions and design context go to the loopback address below. No cloud AI key.</span></div>
 <details className="agent-connection"><summary>{connected?'Connected · '+model:'Optional local AI · connect a model'}</summary><label htmlFor="agent-endpoint">Ollama address</label><Input id="agent-endpoint" value={endpoint} disabled={busy} onChange={e=>{setEndpoint(e.target.value);setConnected(false);}}/><label htmlFor="agent-model">Local model</label>{models.length?<Select value={model} disabled={busy} onValueChange={v=>v&&setModel(v)}><SelectTrigger id="agent-model" className="w-full"><SelectValue>{model}</SelectValue></SelectTrigger><SelectContent>{models.map(m=><SelectItem key={m.digest+m.name} value={m.name}>{m.name}</SelectItem>)}</SelectContent></Select>:<p>{DEFAULT_MODEL}</p>}<Button variant="outline" disabled={busy} onClick={connect}>{connected?'Refresh models':'Connect Ollama'}</Button><p>For this Mac, <a href="/start-local-agent.command" download>download the launcher</a> and run it in Terminal. It starts local-only Ollama and installs the model if needed. Keep it running while you use the assistant.</p><p>Allow local-network access if your browser asks. If the in-app browser blocks it, open this studio in Chrome. <a href="https://docs.ollama.com/faq" target="_blank" rel="noreferrer">Ollama setup reference</a></p></details>
 <div className="agent-snapshot">{dirty?'Pending parameters · calculations describe the last canvas':'Applied design · '+graphHash.slice(0,12)}{selectedId&&<span>Selected: {selectedId}</span>}</div>
 <Button variant="outline" disabled={!graph||designBusy||busy} onClick={()=>setChecks(reviewDesign(graph,dirty))}>Review design checks · no model needed</Button>{checks.length>0&&<div className="agent-checks"><strong>Generator review</strong><ul>{checks.map((line,i)=><li key={i}>{line}</li>)}</ul></div>}
 <div className="agent-prompts">{['Optimize the plant pipe routing.','Propose two cooling pods with four CDUs.','Change to a water-cooled plant and size its pipes.'].map(text=><button key={text} disabled={busy} onClick={()=>setQuestion(text)}>{text}</button>)}</div>
 <form onSubmit={e=>{e.preventDefault();void ask();}}><label htmlFor="agent-question">Ask or describe a change</label><Textarea id="agent-question" placeholder="For example: make two independent cooling pods and keep the same rack count…" value={question} maxLength={4000} disabled={busy} onChange={e=>setQuestion(e.target.value)}/><div className="agent-send"><Button type="submit" disabled={(!connected&&!/optim|shorter|reduce.*pipe|pipe.*rout/i.test(question))||busy||designBusy||!question.trim()||!fields.length}><Send size={15}/> Run request</Button>{busy&&<Button type="button" variant="outline" onClick={cancel}><Square size={13}/> Cancel</Button>}</div></form>
 <p className="agent-phase" role="status">{busy&&<LoaderCircle size={14} className="animate-spin"/>}{phase}</p>{error&&<div role="alert" className="agent-error">{error}{/fetch|network/i.test(error)&&<p>Start the launcher, verify Ollama’s allowed origins and the browser’s local-network permission, then reconnect.</p>}</div>}
 <div className="agent-turns">{turns.map((turn,i)=>{const stale=turn.stamp!==stamp||turn.graphHash!==graphHash;return <article key={i}><p className="agent-question">{turn.question}</p><p className="agent-answer">{turn.answer.summary}</p>{turn.answer.qualifications.length>0&&<ul>{turn.answer.qualifications.map((q,j)=><li key={j}>{q}</li>)}</ul>}{turn.answer.source_ids.length>0&&<details><summary>Parameter sources used</summary>{turn.answer.source_ids.map(key=>{const f=fields.find(f=>f.key===key);return f&&<p key={key}><strong>{f.label}: {f.source.title}</strong><br/>{f.source.status} · {f.source.edition} · {f.source.clause}<br/>{f.source.note}{f.source.url&&<><br/><a href={f.source.url} target="_blank" rel="noreferrer">Open reference</a></>}</p>;})}</details>}
 {turn.proposal&&turn.proposal.changes.length>0&&<div className="agent-proposal"><strong>Proposed parameter changes</strong><div className="agent-diff">{turn.proposal.changes.map(c=><div key={c.parameter}><b>{fields.find(f=>f.key===c.parameter)?.label||c.parameter}</b><span>{JSON.stringify(c.before)} → {JSON.stringify(c.after)}</span><p>{c.reason}</p></div>)}</div>{turn.trial&&<p className={turn.trial.status==='FAIL'?'agent-error':'agent-success'}>{turn.trial.status==='PASS'?'Generator check passed':'Generator found conflicts'} · {turn.trial.compute} compute racks · {turn.trial.cdus} CDUs{turn.trial.count>0?' · '+turn.trial.count+' findings':''}</p>}{turn.trial?.findings.map((s,j)=><p key={j}>{s}</p>)}{turn.error&&<p className="agent-error">{turn.error}</p>}{stale&&!turn.staged&&<p className="agent-error">This proposal is out of date. Ask again for the current design.</p>}<Button disabled={busy||designBusy||stale||!!turn.error||!turn.trial||turn.trial.status!=='PASS'||turn.staged} onClick={()=>{if(stale||!turn.proposal||turn.trial?.status!=='PASS')return;try{onStage(turn.proposal.config,turn.stamp,turn.graphHash);setTurns(old=>old.map((t,j)=>j===i?{...t,staged:true}:t));onOpenChange(false);}catch(err){setError(String(err instanceof Error?err.message:err));}}}>{turn.staged?'Staged for Apply design':'Stage these parameters'}</Button><p>Staging updates the tuning controls. Apply design regenerates the canvas and export package.</p></div>}
 {!turn.proposal&&stale&&<small>Answer based on an earlier design.</small>}</article>;})}</div>
 </div></SheetContent></Sheet>;
}
