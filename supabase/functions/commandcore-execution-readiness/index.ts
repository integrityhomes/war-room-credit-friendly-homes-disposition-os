const SERVICE_VERSION="2026-08-27.1";
function jsonResponse(status:number,payload:Record<string,unknown>):Response{return new Response(JSON.stringify(payload),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}})}
function normalized(v:unknown):string{return String(v??"").trim()}
function constantTimeEqual(a:string,b:string):boolean{if(a.length!==b.length)return false;let d=0;for(let i=0;i<a.length;i++)d|=a.charCodeAt(i)^b.charCodeAt(i);return d===0}
function bearer(req:Request):string{const a=req.headers.get("authorization")||"";return a.startsWith("Bearer ")?a.slice(7).trim():""}
function authed(req:Request):boolean{const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";const supplied=bearer(req);return Boolean(key&&supplied&&constantTimeEqual(key,supplied))}
function bool(v:unknown):boolean{return v===true}
function obj(v:unknown):Record<string,unknown>{return v&&typeof v==="object"&&!Array.isArray(v)?v as Record<string,unknown>: {}}

Deno.serve(async(req)=>{
  if(req.method==="GET")return jsonResponse(200,{ok:true,service:"commandcore-execution-readiness",version:SERVICE_VERSION,status:"healthy",external_execution_enabled:false});
  if(req.method!=="POST")return jsonResponse(405,{ok:false,error:"method_not_allowed"});
  if(!authed(req))return jsonResponse(401,{ok:false,error:"unauthorized"});
  let body:Record<string,unknown>={};try{body=await req.json()}catch{return jsonResponse(400,{ok:false,error:"invalid_json"})}
  const order=obj(body.work_order||body);
  const handoff=obj(order.outbound_handoff||body.outbound_handoff);
  const channel=normalized(order.channel_key||handoff.channel_key);
  if(!channel)return jsonResponse(422,{ok:false,error:"channel_key_required"});
  const family=normalized(handoff.adapter_family||order.adapter_family);
  const reasons:string[]=[];

  if(normalized(order.result_status)==="blocked"||normalized(order.state)==="blocked")return jsonResponse(200,{ok:true,channel_key:channel,readiness:"BLOCKED",reasons:["channel_blocked"],external_action_started:false});
  if(family==="social_manual"||bool(order.human_final_post_required))return jsonResponse(200,{ok:true,channel_key:channel,readiness:"MANUAL",reasons:["human_final_post_required"],external_action_started:false});

  const required=Array.isArray(handoff.required_gates)?handoff.required_gates.map(normalized).filter(Boolean):[];
  const gates=obj(body.gates||order.gates);
  for(const gate of required){
    if(gate==="platform_connection"||gate==="channel_identity_verification"||gate==="delivery_adapter_connection"||gate==="ad_account_connection")continue;
    if(!bool(gates[gate]))reasons.push(gate);
  }

  if(bool(handoff.destination_connection_required)){
    const c=obj(handoff.connection);
    if(!c||normalized(c.connection_state)!=="connected")reasons.push("connection_connected");
    const health=normalized(c.health_status).toLowerCase();
    if(!["healthy","ok","ready"].includes(health))reasons.push("connection_healthy");
    if(!bool(c.execution_permitted))reasons.push("execution_permission");
    if(!normalized(c.last_verified_at))reasons.push("connection_verified");
    if((family==="permissioned_message"&&!normalized(c.sender_identity))||(["social_connected","video_connected","paid_media"].includes(family)&&!normalized(c.destination_identity||c.sender_identity)))reasons.push("channel_identity");
  }

  const unique=[...new Set(reasons)];
  const readiness=unique.length?"HOLD":"READY";
  return jsonResponse(200,{ok:true,channel_key:channel,readiness,reasons:unique,required_gates:required,external_execution_enabled:false,external_action_started:false});
});
