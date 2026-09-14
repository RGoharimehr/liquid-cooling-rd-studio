/** Match Config.from_dict migration without overwriting an explicit plant. */
export function importParameters(data:unknown,defaults:Record<string,any>){
 if(typeof data!=='object'||Array.isArray(data)||data===null)throw Error('Expected a JSON parameter object');
 const value=data as Record<string,any>;const keys=new Set(Object.keys(defaults));const unknown=Object.keys(value).filter(k=>!keys.has(k));if(unknown.length)throw Error('Unknown parameters: '+unknown.join(', '));
 const version=value.schema_version??1;if(version!==1&&version!==2)throw Error('Unsupported parameter schema version');
 return {...defaults,...value,schema_version:2,...(version===1&&!Object.hasOwn(value,'plant_type')?{plant_type:'boundary'}:{})};
}
