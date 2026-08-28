const SERVICE_VERSION = "2026-08-27.1";
const ACTION_BUCKET = "commandcore-action-queue";

function jsonResponse(status:number,payload:Record<string,unknown>):Response{
  return new Response(JSON.stringify(payload),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}});
}
function normalized(v:unknown):string{return String(v??"").trim()}
function constantTimeEqual(a:string,b:string):boolean{if(a.length!==b.length)return false;let d=0;for(let i=0;i<a.length;i++)d|=a.charCodeAt(i)^b.charCodeAt(i);return d===0}
function bearer(req:Request):string{const a=req.headers.get("authorization")||"";return a.startsWith("Bearer ")?a.slice(7).trim():""}
function authed(req:Request):boolean{const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";const supplied=bearer(req);return Boolean(key&&supplied&&constantTimeEqual(key,supplied))}
function obj(v:unknown):Record<string,unknown>{return v&&typeof v==="object"&&!Array.isArray(v)?v as Record<string,unknown>: {}}
function safePart(v:unknown):string{return normalized(v).replace(/[^a-zA-Z0-9_-]+/g,"-").replace(/^-+|-+$/g,"").slice(0,120)}
function storageHeaders(key:string):HeadersInit{return {authorization:`Bearer ${key}`,apikey:key,"content-type":"application/json"}}

const REASON_LABELS:Record<string,string>={
  campaign_approval:"Approve campaign",
  creative_approval:"Approve creative",
  buyer_match:"Confirm buyer match",
  consent_ledger:"Verify buyer consent",
  suppression_check:"Clear suppression / opt-out check",
  sender_identity:"Verify production sender identity",
  delivery_adapter_connection:"Connect delivery provider",
  budget_authorization:"Approve ad budget",
  ad_account_connection:"Connect ad account",
  platform_connection:"Connect platform account",
  channel_identity_verification:"Verify page / channel identity",
  connection_connected:"Reconnect channel",
  connection_healthy:"Fix unhealthy connection",
  execution_permission:"Enable execution permission",
  connection_verified:"Verify connection",
  channel_identity:"Set verified sender / destination identity",
  outbound_handoff_missing:"Rebuild outbound handoff",
  readiness_check_failed:"Review readiness service failure",
  human_final_post_required:"Complete final human post",
  channel_blocked:"Review blocked channel"
};

function actionForReason(reason:string):string{return REASON_LABELS[reason]||reason.replace(/_/g," ").replace(/^./,c=>c.toUpperCase())}
function priorityFor(readiness:string,reasons:string[]):string{
  if(readiness==="BLOCKED")return "high";
  if(reasons.some(r=>["suppression_check","consent_ledger","sender_identity","budget_authorization"].includes(r)))return "high";
  if(readiness==="MANUAL")return "medium";
  return "medium";
}

async function persist(dispatchId:string,payload:Record<string,unknown>):Promise<void>{
  const url=(Deno.env.get("SUPABASE_URL")||"").replace(/\/$/,"");const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!url||!key)throw new Error("action_queue_not_configured");
  const bucket=await fetch(`${url}/storage/v1/bucket`,{method:"POST",headers:storageHeaders(key),body:JSON.stringify({id:ACTION_BUCKET,name:ACTION_BUCKET,public:false})});
  if(!bucket.ok&&bucket.status!==400&&bucket.status!==409)throw new Error(`action_bucket_failed_${bucket.status}`);
  const path=`dispatches/${safePart(dispatchId)}.json`;
  const res=await fetch(`${url}/storage/v1/object/${ACTION_BUCKET}/${path}`,{method:"POST",headers:{...storageHeaders(key),"x-upsert":"true"},body:JSON.stringify(payload)});
  if(!res.ok)throw new Error(`action_queue_write_failed_${res.status}`);
}

Deno.serve(async(req)=>{
  if(req.method==="GET")return jsonResponse(200,{ok:true,service:"commandcore-action-queue",version:SERVICE_VERSION,status:"healthy",external_execution_enabled:false});
  if(req.method!=="POST")return jsonResponse(405,{ok:false,error:"method_not_allowed"});
  if(!authed(req))return jsonResponse(401,{ok:false,error:"unauthorized"});
  let body:Record<string,unknown>={};try{body=await req.json()}catch{return jsonResponse(400,{ok:false,error:"invalid_json"})}
  const dispatch=obj(body.dispatch||body);
  const dispatchId=safePart(dispatch.dispatch_id||body.dispatch_id);
  if(!dispatchId)return jsonResponse(422,{ok:false,error:"dispatch_id_required"});
  const propertyId=safePart(dispatch.property_id||body.property_id);
  const workOrders=Array.isArray(dispatch.work_orders)?dispatch.work_orders:[];
  const items:Record<string,unknown>[]=[];
  let ready=0,hold=0,manual=0,blocked=0;

  for(const raw of workOrders){
    if(!raw||typeof raw!=="object"||Array.isArray(raw))continue;
    const order=raw as Record<string,unknown>;
    const readiness=normalized(order.readiness||order.execution_readiness).toUpperCase();
    if(readiness==="READY"){ready+=1;continue}
    if(readiness==="HOLD")hold+=1;else if(readiness==="MANUAL")manual+=1;else if(readiness==="BLOCKED")blocked+=1;else continue;
    const reasonsRaw=Array.isArray(order.readiness_reasons)?order.readiness_reasons:Array.isArray(order.reasons)?order.reasons:[];
    const reasons=reasonsRaw.map(normalized).filter(Boolean);
    const channel=normalized(order.channel_key);
    items.push({
      action_id:`${dispatchId}-${safePart(channel)}-${readiness.toLowerCase()}`,
      dispatch_id:dispatchId,
      property_id:propertyId||null,
      channel_key:channel||null,
      readiness,
      priority:priorityFor(readiness,reasons),
      reasons,
      required_actions:reasons.length?reasons.map(actionForReason):[readiness==="MANUAL"?"Complete final human action":"Review channel hold"],
      marketing_package:obj(order.marketing_package),
      lead_form_url:normalized(order.lead_form_url)||null,
      created_at:new Date().toISOString(),
      external_action_started:false
    });
  }

  const queue={
    dispatch_id:dispatchId,
    property_id:propertyId||null,
    summary:{ready,hold,manual,blocked,needs_attention:hold+manual+blocked,total:ready+hold+manual+blocked},
    items,
    generated_at:new Date().toISOString(),
    external_execution_enabled:false,
    external_action_started:false
  };
  try{await persist(dispatchId,queue)}catch(error){console.error("CommandCore action queue persistence failed",error);return jsonResponse(503,{ok:false,error:"action_queue_unavailable",external_action_started:false})}
  return jsonResponse(200,{ok:true,queue,external_execution_enabled:false,external_action_started:false});
});
