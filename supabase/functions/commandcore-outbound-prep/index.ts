const SERVICE_VERSION = "2026-08-27.1";

function jsonResponse(status:number,payload:Record<string,unknown>):Response{
  return new Response(JSON.stringify(payload),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}});
}
function normalized(v:unknown):string{return String(v??"").trim()}
function constantTimeEqual(left:string,right:string):boolean{if(left.length!==right.length)return false;let d=0;for(let i=0;i<left.length;i+=1)d|=left.charCodeAt(i)^right.charCodeAt(i);return d===0}
function bearer(req:Request):string{const a=req.headers.get("authorization")||"";return a.startsWith("Bearer ")?a.slice(7).trim():""}
function authed(req:Request):boolean{const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";const supplied=bearer(req);return Boolean(key&&supplied&&constantTimeEqual(key,supplied))}

const CHANNEL_FAMILIES:Record<string,string>={
  facebook_marketplace:"social_manual",facebook_groups:"social_manual",facebook_page:"social_connected",instagram:"social_connected",tiktok:"social_connected",youtube:"video_connected",blog:"owned_content",market_seo:"owned_content",email:"permissioned_message",sms:"permissioned_message",reactivation:"permissioned_message",meta_ads:"paid_media",google_ads:"paid_media"
};

Deno.serve(async(req)=>{
  if(req.method==="GET")return jsonResponse(200,{ok:true,service:"commandcore-outbound-prep",version:SERVICE_VERSION,status:"healthy",external_execution_enabled:false,external_action_started:false});
  if(req.method!=="POST")return jsonResponse(405,{ok:false,error:"method_not_allowed"});
  if(!authed(req))return jsonResponse(401,{ok:false,error:"unauthorized"});
  let body:Record<string,unknown>={};try{body=await req.json()}catch{return jsonResponse(400,{ok:false,error:"invalid_json"})}
  const order=body.work_order&&typeof body.work_order==="object"&&!Array.isArray(body.work_order)?body.work_order as Record<string,unknown>:body;
  const channelKey=normalized(order.channel_key);
  const family=CHANNEL_FAMILIES[channelKey]||"unsupported";
  if(family==="unsupported")return jsonResponse(422,{ok:false,error:"unsupported_channel",external_action_started:false});
  if(normalized(order.result_status)==="blocked"||normalized(order.state)==="blocked")return jsonResponse(409,{ok:false,error:"channel_blocked",external_action_started:false});
  const pkg=order.marketing_package&&typeof order.marketing_package==="object"&&!Array.isArray(order.marketing_package)?order.marketing_package as Record<string,unknown>:{};
  const copy=normalized(pkg.copy||order.copy);
  const subject=normalized(pkg.subject||order.subject);
  const headline=normalized(pkg.headline||order.headline);
  const leadFormUrl=normalized(pkg.lead_form_url||order.lead_form_url);
  if(!copy&&family!=="owned_content")return jsonResponse(422,{ok:false,error:"copy_required",external_action_started:false});

  let requiredGates:string[]=[];
  if(family==="permissioned_message")requiredGates=["campaign_approval","buyer_match","consent_ledger","suppression_check","sender_identity","delivery_adapter_connection"];
  else if(family==="paid_media")requiredGates=["campaign_approval","creative_approval","budget_authorization","ad_account_connection"];
  else if(family==="social_connected"||family==="video_connected")requiredGates=["campaign_approval","platform_connection","channel_identity_verification"];
  else if(family==="social_manual")requiredGates=["campaign_approval","human_final_post"];
  else requiredGates=["campaign_approval"];

  const handoff={
    channel_key:channelKey,
    adapter_family:family,
    destination_connection_required:!["owned_content","social_manual"].includes(family),
    subject:subject||null,
    headline:headline||null,
    copy:copy||null,
    lead_form_url:leadFormUrl||null,
    required_gates:requiredGates,
    execution_state:"prepared_not_executable",
    external_execution_enabled:false,
    external_action_started:false
  };
  return jsonResponse(200,{ok:true,prepared:true,handoff,external_execution_enabled:false,external_action_started:false});
});
