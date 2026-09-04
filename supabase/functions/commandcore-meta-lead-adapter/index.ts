const SERVICE_VERSION = "2026-09-04.1";
const MAX_BODY_BYTES = 128 * 1024;
const MAX_ENTRIES = 25;
const MAX_CHANGES = 50;
const MAX_FIELDS = 100;
const LEAD_TYPES = new Set(["seller", "buyer", "owner_finance_buyer", "investor_buyer_interest"]);

function jsonResponse(status:number,payload:Record<string,unknown>):Response{return new Response(JSON.stringify(payload),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff"}})}
function normalized(value:unknown):string{return String(value??"").trim()}
function lower(value:unknown):string{return normalized(value).toLowerCase()}
function objectValue(value:unknown):Record<string,unknown>{return value&&typeof value==="object"&&!Array.isArray(value)?value as Record<string,unknown>: {}}
function constantTimeEqual(a:string,b:string):boolean{if(a.length!==b.length)return false;let difference=0;for(let index=0;index<a.length;index++)difference|=a.charCodeAt(index)^b.charCodeAt(index);return difference===0}
function hex(bytes:ArrayBuffer):string{return Array.from(new Uint8Array(bytes)).map(value=>value.toString(16).padStart(2,"0")).join("")}
async function hmacSha256(secret:string,body:string):Promise<string>{const key=await crypto.subtle.importKey("raw",new TextEncoder().encode(secret),{name:"HMAC",hash:"SHA-256"},false,["sign"]);return hex(await crypto.subtle.sign("HMAC",key,new TextEncoder().encode(body)))}
async function validSignature(req:Request,raw:string):Promise<boolean>{const secret=Deno.env.get("COMMANDCORE_META_TEST_APP_SECRET")||"";const supplied=req.headers.get("x-hub-signature-256")||"";if(!secret||!supplied.startsWith("sha256="))return false;return constantTimeEqual(supplied.slice(7),await hmacSha256(secret,raw))}
function isTestMode():boolean{return lower(Deno.env.get("COMMANDCORE_META_LEAD_MODE")||"test")==="test"}
function verificationResponse(req:Request):Response{
  if(!isTestMode())return jsonResponse(403,{ok:false,error:"live_meta_ingress_disabled",external_action_started:false});
  const url=new URL(req.url);const mode=url.searchParams.get("hub.mode")||"";const supplied=url.searchParams.get("hub.verify_token")||"";const challenge=url.searchParams.get("hub.challenge")||"";
  const expected=Deno.env.get("COMMANDCORE_META_TEST_VERIFY_TOKEN")||"";
  if(mode!=="subscribe"||!expected||!supplied||!constantTimeEqual(supplied,expected)||!challenge)return jsonResponse(403,{ok:false,error:"invalid_verification_challenge",external_action_started:false});
  return new Response(challenge,{status:200,headers:{"content-type":"text/plain; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff"}});
}

function normalizeFields(value:unknown):Record<string,string>{
  if(!Array.isArray(value)||value.length>MAX_FIELDS)throw new Error("invalid_field_data");
  const fields:Record<string,string>={};
  for(const item of value){const field=objectValue(item);const name=lower(field.name).replace(/[^a-z0-9_]/g,"_");if(!name)continue;const values=Array.isArray(field.values)?field.values:[];fields[name]=values.map(normalized).filter(Boolean).join(", ").slice(0,4000);}
  return fields;
}
function first(fields:Record<string,string>,names:string[]):string{for(const name of names){if(fields[name])return fields[name]}return ""}
function leadType(fields:Record<string,string>,value:Record<string,unknown>):string{const requested=lower(value.lead_type||first(fields,["lead_type","lead_category","contact_type"]));if(!LEAD_TYPES.has(requested))throw new Error("unsupported_lead_type");return requested}
function safeId(value:unknown):string{const result=normalized(value);return /^[A-Za-z0-9._:-]{1,200}$/.test(result)?result:""}

function normalizeChange(entry:Record<string,unknown>,change:Record<string,unknown>):Record<string,unknown>{
  if(lower(change.field)!=="leadgen")throw new Error("unsupported_change");
  const value=objectValue(change.value);const fields=normalizeFields(value.field_data);
  const leadgenId=safeId(value.leadgen_id);const pageId=safeId(value.page_id||entry.id);const formId=safeId(value.form_id);
  if(!leadgenId||!pageId||!formId)throw new Error("meta_identity_required");
  const kind=leadType(fields,value);
  const campaignId=safeId(value.campaign_id);const adsetId=safeId(value.adset_id);const adId=safeId(value.ad_id);
  const eventId=`meta-leadgen:${pageId}:${formId}:${leadgenId}`;
  return {
    source_type:"facebook_lead",source_event_id:eventId,test_mode:true,
    payload:{
      first_name:first(fields,["first_name","first_name_1"]),last_name:first(fields,["last_name","last_name_1"]),
      full_name:first(fields,["full_name","name"]),phone:first(fields,["phone_number","phone","mobile_phone_number"]),
      email:lower(first(fields,["email","email_address"])),lead_type:kind,
      property_address:first(fields,["property_address","address","street_address"]),city:first(fields,["city"]),state:first(fields,["state"]),zip:first(fields,["zip_code","zip","postal_code"]),
      notes:first(fields,["notes","message","comments"]),campaign:campaignId,source_detail:"meta_lead_ads",medium:"paid_social",
      market_preferences:first(fields,["market_preferences","preferred_markets","locations"]),property_types:first(fields,["property_types","property_type","home_types"]),
      financing_preferences:first(fields,["financing_preferences","financing","purchase_method"]),condition_preferences:first(fields,["condition_preferences","property_condition"]),
      max_purchase_price:first(fields,["max_purchase_price","max_price","budget"]),max_monthly_payment:first(fields,["max_monthly_payment","max_payment","monthly_budget"]),
      max_down_payment:first(fields,["max_down_payment","down_payment_budget"]),min_bedrooms:first(fields,["min_bedrooms","bedrooms","beds"]),min_bathrooms:first(fields,["min_bathrooms","bathrooms","baths"]),
      sms_consent_state:lower(first(fields,["sms_consent_state"])),email_consent_state:lower(first(fields,["email_consent_state"])),
      consent_evidence_reference:first(fields,["consent_evidence_reference","consent_reference"]),occurred_at:normalized(value.created_time||entry.time),
      meta_page_id:pageId,meta_form_id:formId,meta_leadgen_id:leadgenId,meta_campaign_id:campaignId,meta_adset_id:adsetId,meta_ad_id:adId,
      test_mode:true,external_action_started:false,
    },
  };
}

async function forward(payload:Record<string,unknown>):Promise<{status:number;body:unknown}>{const base=(Deno.env.get("SUPABASE_URL")||"").replace(/\/$/,"");const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";if(!base||!key)throw new Error("adapter_not_configured");const response=await fetch(`${base}/functions/v1/commandcore-lead-source-adapter`,{method:"POST",headers:{authorization:`Bearer ${key}`,"content-type":"application/json"},body:JSON.stringify(payload)});let body:unknown={};try{body=await response.json()}catch{body={ok:false,error:"invalid_adapter_response"}}return{status:response.status,body}}

Deno.serve(async(req)=>{
  if(req.method==="GET")return new URL(req.url).searchParams.has("hub.challenge")?verificationResponse(req):jsonResponse(200,{ok:true,service:"commandcore-meta-lead-adapter",version:SERVICE_VERSION,status:"test_mode_only",live_ingress_enabled:false,external_action_started:false});
  if(req.method!=="POST")return jsonResponse(405,{ok:false,error:"method_not_allowed"});
  if(!isTestMode())return jsonResponse(403,{ok:false,error:"live_meta_ingress_disabled",external_action_started:false});
  const raw=await req.text();if(new TextEncoder().encode(raw).byteLength>MAX_BODY_BYTES)return jsonResponse(413,{ok:false,error:"payload_too_large"});
  if(!(await validSignature(req,raw)))return jsonResponse(401,{ok:false,error:"invalid_signature",external_action_started:false});
  let body:Record<string,unknown>;try{body=JSON.parse(raw)}catch{return jsonResponse(400,{ok:false,error:"invalid_json"})}
  if(lower(body.object)!=="page"||!Array.isArray(body.entry)||body.entry.length===0||body.entry.length>MAX_ENTRIES)return jsonResponse(422,{ok:false,error:"malformed_meta_event"});
  try{
    const normalizedEvents:Record<string,unknown>[]=[];
    for(const rawEntry of body.entry){const entry=objectValue(rawEntry);if(!Array.isArray(entry.changes)||entry.changes.length===0||entry.changes.length>MAX_CHANGES)throw new Error("malformed_meta_event");for(const rawChange of entry.changes)normalizedEvents.push(normalizeChange(entry,objectValue(rawChange)));}
    const unique=new Map<string,Record<string,unknown>>();for(const event of normalizedEvents)unique.set(normalized(event.source_event_id),event);
    const results=[];for(const event of unique.values())results.push(await forward(event));
    const failed=results.find(result=>result.status<200||result.status>=300);
    if(failed)return jsonResponse(502,{ok:false,error:"canonical_intake_failed",external_action_started:false});
    return jsonResponse(202,{ok:true,accepted:unique.size,duplicates_ignored:normalizedEvents.length-unique.size,replay_safe:true,canonical_destination:"commandcore-lead-source-adapter",event_ids:Array.from(unique.keys()),external_action_started:false});
  }catch(error){const code=error instanceof Error?error.message:"malformed_meta_event";const safe=new Set(["invalid_field_data","unsupported_lead_type","unsupported_change","meta_identity_required","malformed_meta_event"]);return jsonResponse(422,{ok:false,error:safe.has(code)?code:"malformed_meta_event",external_action_started:false});}
});
