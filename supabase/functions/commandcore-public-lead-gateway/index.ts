const SERVICE_VERSION = "2026-08-27.1";
const MAX_BODY_BYTES = 32 * 1024;
const RATE_BUCKET = "commandcore-public-ingress";
const RATE_LIMIT = 12;
const RATE_WINDOW_MS = 10 * 60 * 1000;
const ALLOWED_SOURCES = new Set(["property_page", "website_form"]);

function jsonResponse(status:number,payload:Record<string,unknown>,origin=""):Response{
  const headers:Record<string,string>={"content-type":"application/json; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff"};
  if(origin){headers["access-control-allow-origin"]=origin;headers["vary"]="Origin";headers["access-control-allow-methods"]="POST, OPTIONS";headers["access-control-allow-headers"]="content-type";}
  return new Response(JSON.stringify(payload),{status,headers});
}
function normalized(v:unknown):string{return String(v??"").trim()}
function lower(v:unknown):string{return normalized(v).toLowerCase()}
function configuredOrigins():Set<string>{return new Set((Deno.env.get("CFH_PUBLIC_LEAD_ORIGINS")||"").split(",").map(v=>v.trim()).filter(Boolean))}
function allowedOrigin(req:Request):string{
  const origin=req.headers.get("origin")||"";
  const allowed=configuredOrigins();
  if(!origin||allowed.size===0||!allowed.has(origin))return "";
  return origin;
}
function clientIp(req:Request):string{return normalized(req.headers.get("cf-connecting-ip")||req.headers.get("x-forwarded-for")?.split(",")[0]||"unknown")}
async function sha256(value:string):Promise<string>{const d=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value));return Array.from(new Uint8Array(d)).map(b=>b.toString(16).padStart(2,"0")).join("")}
function storageConfig(){const supabaseUrl=(Deno.env.get("SUPABASE_URL")||"").replace(/\/$/,"");const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";if(!supabaseUrl||!key)throw new Error("storage_not_configured");return{supabaseUrl,key}}
function storageHeaders(key:string):HeadersInit{return{authorization:`Bearer ${key}`,apikey:key,"content-type":"application/json"}}
async function ensureBucket(){const{supabaseUrl,key}=storageConfig();const r=await fetch(`${supabaseUrl}/storage/v1/bucket/${RATE_BUCKET}`,{headers:storageHeaders(key)});if(r.ok)return;if(r.status!==404)throw new Error(`bucket_read_${r.status}`);const c=await fetch(`${supabaseUrl}/storage/v1/bucket`,{method:"POST",headers:storageHeaders(key),body:JSON.stringify({id:RATE_BUCKET,name:RATE_BUCKET,public:false})});if(!c.ok&&c.status!==409)throw new Error(`bucket_create_${c.status}`)}
async function readObject(path:string):Promise<Record<string,unknown>|null>{const{supabaseUrl,key}=storageConfig();const r=await fetch(`${supabaseUrl}/storage/v1/object/${RATE_BUCKET}/${path}`,{headers:storageHeaders(key)});if(r.status===404)return null;if(!r.ok)return null;try{const j=await r.json();return j&&typeof j==="object"&&!Array.isArray(j)?j as Record<string,unknown>:null}catch{return null}}
async function writeObject(path:string,payload:Record<string,unknown>){const{supabaseUrl,key}=storageConfig();const r=await fetch(`${supabaseUrl}/storage/v1/object/${RATE_BUCKET}/${path}`,{method:"POST",headers:{...storageHeaders(key),"x-upsert":"true"},body:JSON.stringify(payload)});if(!r.ok)throw new Error(`rate_write_${r.status}`)}
async function rateAllowed(ip:string):Promise<boolean>{await ensureBucket();const hash=(await sha256(ip)).slice(0,32);const path=`rates/${hash}.json`;const now=Date.now();const current=await readObject(path)||{};const start=Number(current.window_start||0);let count=Number(current.count||0);if(!start||now-start>RATE_WINDOW_MS){count=0;}count+=1;await writeObject(path,{window_start:(!start||now-start>RATE_WINDOW_MS)?now:start,count,updated_at:new Date().toISOString()});return count<=RATE_LIMIT}
async function forward(body:Record<string,unknown>):Promise<{status:number;body:unknown}>{const{supabaseUrl,key}=storageConfig();const r=await fetch(`${supabaseUrl}/functions/v1/commandcore-lead-source-adapter`,{method:"POST",headers:{authorization:`Bearer ${key}`,"content-type":"application/json"},body:JSON.stringify(body)});let parsed:unknown={};try{parsed=await r.json()}catch{parsed={ok:false,error:"invalid_adapter_response"}}return{status:r.status,body:parsed}}

Deno.serve(async(req=>{
  if(req.method==="GET")return jsonResponse(200,{ok:true,service:"commandcore-public-lead-gateway",version:SERVICE_VERSION,status:"healthy",public_ingress_enabled:true,allowed_sources:Array.from(ALLOWED_SOURCES),external_action_started:false});
  const origin=allowedOrigin(req);
  if(req.method==="OPTIONS")return origin?new Response(null,{status:204,headers:{"access-control-allow-origin":origin,"access-control-allow-methods":"POST, OPTIONS","access-control-allow-headers":"content-type","access-control-max-age":"600","vary":"Origin"}}):jsonResponse(403,{ok:false,error:"origin_not_allowed"});
  if(req.method!=="POST")return jsonResponse(405,{ok:false,error:"method_not_allowed"},origin);
  if(!origin)return jsonResponse(403,{ok:false,error:"origin_not_allowed"});
  const contentType=lower(req.headers.get("content-type"));if(!contentType.includes("application/json"))return jsonResponse(415,{ok:false,error:"json_required"},origin);
  const raw=await req.text();if(new TextEncoder().encode(raw).byteLength>MAX_BODY_BYTES)return jsonResponse(413,{ok:false,error:"payload_too_large"},origin);
  let body:Record<string,unknown>;try{body=JSON.parse(raw)}catch{return jsonResponse(400,{ok:false,error:"invalid_json"},origin)}
  if(normalized(body.website||body.company||body.middle_name||body.honeypot))return jsonResponse(202,{ok:true,accepted:true},origin);
  const source=lower(body.source_type||body.source||"property_page");if(!ALLOWED_SOURCES.has(source))return jsonResponse(422,{ok:false,error:"unsupported_public_source"},origin);
  const phone=normalized(body.phone);const email=lower(body.email);if(!phone&&!email)return jsonResponse(422,{ok:false,error:"lead_identity_required"},origin);
  if(phone.length>40||email.length>254||normalized(body.notes||body.message).length>4000)return jsonResponse(422,{ok:false,error:"field_too_long"},origin);
  try{
    if(!(await rateAllowed(clientIp(req))))return jsonResponse(429,{ok:false,error:"rate_limited"},origin);
    const payload:Record<string,unknown>={source_type:source,payload:{...body,source_type:undefined,source:undefined,website:undefined,company:undefined,middle_name:undefined,honeypot:undefined},source_event_id:normalized(body.source_event_id)||crypto.randomUUID()};
    // Public form submissions never manufacture consent. Explicit granted consent must carry evidence created by the form UI/version.
    const sms=lower(body.sms_consent_state);const emailState=lower(body.email_consent_state);const evidence=normalized(body.consent_evidence_reference);
    if((sms==="granted"||emailState==="granted")&&!evidence)return jsonResponse(422,{ok:false,error:"granted_consent_requires_evidence"},origin);
    const result=await forward(payload);
    if(result.status<200||result.status>=300)return jsonResponse(502,{ok:false,error:"lead_intake_failed"},origin);
    return jsonResponse(202,{ok:true,accepted:true,source_type:source,external_action_started:false},origin);
  }catch(error){console.error("CommandCore public lead gateway failed",error);return jsonResponse(503,{ok:false,error:"lead_gateway_unavailable"},origin)}
}));
