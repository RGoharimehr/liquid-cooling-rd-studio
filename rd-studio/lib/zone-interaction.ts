/** A click and sub-grid motion select a zone without submitting a design edit. */
export function snappedMove(anchor:number[],start:number[],end:number[],offset=[0,0]):number[]|null {
 const delta=[0,1].map(i=>Math.round((offset[i]+end[i]-start[i])*4)/4);
 if(delta.every(value=>value===0))return null;
 return [anchor[0]+delta[0],anchor[1]+delta[1],anchor[2]||0];
}
