// The headless selector is code; its catalogue is independently published data.
// No catalogue rows are bundled with an RD release or written back by RD.
export const CATALOGUE_URL = 'https://raw.githubusercontent.com/RGoharimehr/DATA-CENTER-EQUIPMENT-FINDER/main/src/datacenter_equipment_finder/data/equipment_catalog.csv';
export const FINDER_REVISION = 'c2180b8a37b1ce711c963e5422b59ac8e4f7d219';
const MAX_BYTES = 2_000_000;
export async function currentCatalogue(signal) {
  const url = new URL(CATALOGUE_URL);
  url.searchParams.set('rd_request', String(Date.now()));
  const response = await fetch(url, {signal, cache:'no-store', credentials:'omit', redirect:'error'});
  if (!response.ok) throw new Error(`The finder catalogue could not be read (${response.status}). Retry the equipment search. Your design is still available.`);
  if (Number(response.headers.get('content-length') || 0) > MAX_BYTES) throw new Error('The finder catalogue exceeds the supported size. Your design is still available.');
  const reader = response.body?.getReader();
  if (!reader) throw new Error('The finder returned an empty catalogue.');
  const chunks=[]; let length=0;
  try {
    while (true) {
      const {done,value} = await reader.read(); if(done)break;
      length+=value.byteLength;
      if(length>MAX_BYTES)throw new Error('The finder catalogue exceeds the supported size.');
      chunks.push(value);
    }
  } finally { await reader.cancel().catch(()=>{}); }
  const bytes=new Uint8Array(length);let offset=0;
  for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  const digest=await crypto.subtle.digest('SHA-256',bytes);
  const sha256=Array.from(new Uint8Array(digest),x=>x.toString(16).padStart(2,'0')).join('');
  return {csv:new TextDecoder('utf-8',{fatal:true}).decode(bytes),metadata:{source_url:CATALOGUE_URL,sha256,fetched_at:new Date().toISOString(),finder_revision:FINDER_REVISION,bytes:length}};
}
