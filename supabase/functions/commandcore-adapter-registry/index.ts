const SERVICE_VERSION = "2026-08-27.1";
const REGISTRY_BUCKET = "commandcore-adapter-registry";

function jsonResponse(status:number,payload:Record<string,unknown>):Response{
  return new Response(JSON.stringify(payload),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}});
}
function normalized(v:unknown):string{return String(v??"").trim()}
function constantTimeEqual(left:string,right:string):boolean{if(left.length!==right.length)return false;let d=0;for(let i=0;i<left.length;i+=1)d|=left.charCodeAt(i)^right.charCodeAt(i);return d===0}
function bearer(req:Request):string{const a=req.headers.get("authorization")||"";return a.startsWith("Bearer ")?a.slice(7).trim():""}
function authed(req:Request):boolean{const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";const supplied=bearer(req);return Boolean(key&&supplied&&constantTimeEqual(key,supplied))}
function safePart(v:unknown):string{return normalized(v).replace(/[^a-zA-Z0-9_-]+/g,"-").replace(/^-+|-+$/g,"").slice(0,120)}
function headers(key:string):HeadersInit{return {authorization:`Bearer ${key}`,apikey:key,"content-type":"application/json"}}
function objectPath(channel:string){return `connections/${safePart(channel)}.json`}

async function readConnection(channel:string):Promise<Record<string,unknown>|null>{
  const url=(Deno.env.get("SUPABASE_URL")||"").replace(/\/$/,"");const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!url||!key)throw new Error("registry_not_configured");
  const res=await fetch(`${url}/storage/v1/object/${REGISTRY_BUCKET}/${objectPath(channel)}`,{headers:headers(key)});
  if(res.status===404)return null;if(!res.ok)throw new Error(`registry_read_failed_${res.status}`);
  const parsed=await res.json();return parsed&&typeof parsed==="object"&&!Array.isArray(parsed)?parsed as Record<string,unknown>:null;
}
async function writeConnection(channel:string,payload:Record<string,unknown>):Promise<void>{
  const url=(Deno.env.get("SUPABASE_URL")||"").replace(/\/$/,"");const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!url||!key)throw new Error("registry_not_configured");
  const bucket=await fetch(`${url}/storage/v1/bucket`,{method:"POST",headers:headers(key),body:JSON.stringify({id:REGISTRY_BUCKET,name:REGISTRY_BUCKET,public:false})});
  if(!bucket.ok&&bucket.status!==400&&bucket.status!==409)throw new Error(`registry_bucket_failed_${bucket.status}`);
  const res=await fetch(`${url}/storage/v1/object/${REGISTRY_BUCKET}/${objectPath(channel)}`,{method:"POST",headers:{...headers(key),"x-upsert":"true"},body:JSON.stringify(payload)});
  if(!res.ok)throw new Error(`registry_write_failed_${res.status}`);
}

Deno.serve(async(req)=>{
  if(req.method==="GET")return jsonResponse(200,{ok:true,service:"commandcore-adapter-registry",version:SERVICE_VERSION,status:"healthy",stores_raw_credentials:false,external_execution_enabled:false});
  if(req.method!=="POST")return jsonResponse(405,{ok:false,error:"method_not_allowed"});
  if(!authed(req))return jsonResponse(401,{ok:false,error:"unauthorized"});
  let body:Record<string,unknown>={};try{body=await req.json()}catch{return jsonResponse(400,{ok:false,error:"invalid_json"})}
  const action=normalized(body.action||"get");const channel=safePart(body.channel_key);
  if(!channel)return jsonResponse(422,{ok:false,error:"channel_key_required"});
  try{
    if(action==="get"){
      const connection=await readConnection(channel);
      return jsonResponse(200,{ok:true,channel_key:channel,connection,connected:Boolean(connection&&connection.connection_state==="connected"),execution_permitted:Boolean(connection&&connection.execution_permitted===true),external_execution_enabled:false});
    }
    if(action!=="upsert")return jsonResponse(422,{ok:false,error:"unsupported_action"});
    const existing=await readConnection(channel)||{};
    const allowedStates=new Set(["disconnected","pending","connected","degraded","revoked"]);
    const connectionState=normalized(body.connection_state||existing.connection_state||"disconnected");
    if(!allowedStates.has(connectionState))return jsonResponse(422,{ok:false,error:"invalid_connection_state"});
    const record={
      channel_key:channel,
      adapter_family:normalized(body.adapter_family||existing.adapter_family)||null,
      provider:normalized(body.provider||existing.provider)||null,
      account_label:normalized(body.account_label||existing.account_label)||null,
      account_external_id:normalized(body.account_external_id||existing.account_external_id)||null,
      sender_identity:normalized(body.sender_identity||existing.sender_identity)||null,
      destination_identity:normalized(body.destination_identity||existing.destination_identity)||null,
      connection_state:connectionState,
      health_status:normalized(body.health_status||existing.health_status||"unknown"),
      execution_permitted:body.execution_permitted===true,
      permission_scope:Array.isArray(body.permission_scope)?body.permission_scope.map(normalized).filter(Boolean):Array.isArray(existing.permission_scope)?existing.permission_scope:[],
      credential_reference:normalized(body.credential_reference||existing.credential_reference)||null,
      raw_credentials_stored:false,
      last_verified_at:normalized(body.last_verified_at)||new Date().toISOString(),
      updated_at:new Date().toISOString()
    };
    await writeConnection(channel,record);
    return jsonResponse(200,{ok:true,saved:true,connection:record,external_execution_enabled:false});
  }catch(error){console.error("CommandCore adapter registry failed",error);return jsonResponse(503,{ok:false,error:"adapter_registry_unavailable",external_execution_enabled:false})}
});
