const SERVICE_VERSION = "2026-09-04.1";
const MAX_BODY_BYTES = 128 * 1024;
const SUPPORTED_SOURCES = new Set(["website_form", "property_page", "facebook_lead", "inbound_sms", "inbound_call", "manual_import"]);
const CANONICAL_LEAD_TYPES = new Set(["seller", "buyer", "owner_finance_buyer", "investor_buyer_interest", "agent", "other"]);

function jsonResponse(status:number,payload:Record<string,unknown>):Response{return new Response(JSON.stringify(payload),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}})}
function normalized(value:unknown):string{return String(value??"").trim()}
function lower(value:unknown):string{return normalized(value).toLowerCase()}
function bearerToken(req:Request):string{const auth=req.headers.get("authorization")||"";return auth.startsWith("Bearer ")?auth.slice(7).trim():""}
function constantTimeEqual(a:string,b:string):boolean{if(a.length!==b.length)return false;let d=0;for(let i=0;i<a.length;i++)d|=a.charCodeAt(i)^b.charCodeAt(i);return d===0}
function isAuthenticated(req:Request):boolean{const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";const supplied=bearerToken(req);return Boolean(key&&supplied&&constantTimeEqual(key,supplied))}
function stringArray(value:unknown):string[]{if(Array.isArray(value))return value.map(normalized).filter(Boolean);if(typeof value==="string")return value.split(/[,;|]/).map(v=>v.trim()).filter(Boolean);return []}
function numberOrUndefined(value:unknown):number|undefined{if(value===null||value===undefined||value==="")return undefined;const n=Number(String(value).replace(/[$,]/g,""));return Number.isFinite(n)?n:undefined}
function first(raw:Record<string,unknown>,keys:string[]):unknown{for(const key of keys){if(raw[key]!==undefined&&raw[key]!==null&&normalized(raw[key]))return raw[key]}return undefined}
function objectValue(value:unknown):Record<string,unknown>{return value&&typeof value==="object"&&!Array.isArray(value)?value as Record<string,unknown>: {}}

function normalizeLead(sourceType:string,body:Record<string,unknown>):Record<string,unknown>{
  const raw=objectValue(body.payload||body.lead||body.data||body);
  const fullName=normalized(first(raw,["full_name","name","contact_name"]));
  const parts=fullName.split(/\s+/).filter(Boolean);
  const firstName=normalized(first(raw,["first_name","firstname","firstName"]))||(parts[0]||"");
  const lastName=normalized(first(raw,["last_name","lastname","lastName"]))||(parts.length>1?parts.slice(1).join(" "):"");
  const phone=normalized(first(raw,["phone","phone_number","mobile","from","caller_phone"]));
  const email=lower(first(raw,["email","email_address"]));
  const sourceEventId=normalized(body.source_event_id||first(raw,["lead_id","id","event_id","message_id","call_id"]));
  const marketPreferences=stringArray(first(raw,["market_preferences","markets","areas","locations","preferred_markets"]));
  const propertyTypes=stringArray(first(raw,["property_types","property_type","home_types"]));
  const financingPreferences=stringArray(first(raw,["financing_preferences","financing","purchase_method"]));
  const conditionPreferences=stringArray(first(raw,["condition_preferences","condition","property_condition"]));
  const tags=Array.from(new Set([sourceType,...stringArray(first(raw,["tags","tag"]))]));
  const requestedLeadType=lower(first(raw,["lead_type","lead_category","contact_type"]));
  const leadType=CANONICAL_LEAD_TYPES.has(requestedLeadType)?requestedLeadType:"buyer";
  const campaign=normalized(first(raw,["campaign","campaign_name","utm_campaign"]));
  const sourceDetail=normalized(first(raw,["source_detail","utm_source"]));
  const medium=normalized(first(raw,["medium","utm_medium"]));
  const out:Record<string,unknown>={
    first_name:firstName,last_name:lastName,phone,email,source:sourceType,channel:sourceType,lead_type:leadType,tags,market_preferences:marketPreferences,
    property_types:propertyTypes,financing_preferences:financingPreferences,condition_preferences:conditionPreferences,
    notes:normalized(first(raw,["notes","message","body","comments","comment","transcript_summary"])),
    source_event_id:sourceEventId,
    source_property_id:normalized(first(raw,["property_id","listing_id","deal_id"])),
    source_property_address:normalized(first(raw,["property_address","address","listing_address"])),
    city:normalized(first(raw,["city"])),state:normalized(first(raw,["state"])),zip:normalized(first(raw,["zip","postal_code"])),
    campaign,source_detail:sourceDetail,medium,test_mode:raw.test_mode===true,
    occurred_at:normalized(first(raw,["occurred_at","created_time","created_at"])),
    meta_page_id:normalized(first(raw,["meta_page_id","page_id"])),meta_form_id:normalized(first(raw,["meta_form_id","form_id"])),
    meta_leadgen_id:normalized(first(raw,["meta_leadgen_id","leadgen_id"])),meta_campaign_id:normalized(first(raw,["meta_campaign_id","campaign_id"])),
    meta_adset_id:normalized(first(raw,["meta_adset_id","adset_id"])),meta_ad_id:normalized(first(raw,["meta_ad_id","ad_id"])),
  };
  const numericMap:Record<string,string[]>={
    max_purchase_price:["max_purchase_price","max_price","budget"],
    max_monthly_payment:["max_monthly_payment","max_payment","monthly_budget","monthly_payment"],
    min_down_payment:["min_down_payment"],max_down_payment:["max_down_payment","down_payment_budget","down_payment"],
    min_bedrooms:["min_bedrooms","bedrooms","beds"],min_bathrooms:["min_bathrooms","bathrooms","baths"]
  };
  for(const [target,keys] of Object.entries(numericMap)){const value=numberOrUndefined(first(raw,keys));if(value!==undefined)out[target]=value}
  const smsState=lower(first(raw,["sms_consent_state","sms_consent"]));
  const emailState=lower(first(raw,["email_consent_state","email_consent"]));
  const evidence=normalized(first(raw,["consent_evidence_reference","consent_evidence","consent_reference"]));
  if(["granted","denied","opt_out"].includes(smsState))out.sms_consent_state=smsState;
  if(["granted","denied","opt_out"].includes(emailState))out.email_consent_state=emailState;
  if(evidence){out.consent_evidence_reference=evidence;out.sms_consent_evidence=evidence;out.email_consent_evidence=evidence;}
  return out;
}

async function forwardToFunction(name:string,payload:Record<string,unknown>):Promise<{status:number;body:unknown}>{
  const supabaseUrl=(Deno.env.get("SUPABASE_URL")||"").replace(/\/$/,"");
  const serviceRoleKey=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!supabaseUrl||!serviceRoleKey)throw new Error("intake_not_configured");
  const response=await fetch(`${supabaseUrl}/functions/v1/${name}`,{method:"POST",headers:{authorization:`Bearer ${serviceRoleKey}`,"content-type":"application/json"},body:JSON.stringify(payload)});
  let parsed:unknown={};try{parsed=await response.json()}catch{parsed={ok:false,error:"invalid_intake_response"}}
  return {status:response.status,body:parsed};
}

function canonicalEvent(sourceType:string,lead:Record<string,unknown>):Record<string,unknown>{
  return {
    schema_version:"1.0",event_type:sourceType==="facebook_lead"?"meta.lead_submitted":"website.lead_submitted",event_id:normalized(lead.source_event_id),
    source:sourceType,channel:normalized(lead.channel)||sourceType,campaign:normalized(lead.campaign)||null,
    source_detail:normalized(lead.source_detail)||null,medium:normalized(lead.medium)||null,
    occurred_at:normalized(lead.occurred_at)||new Date().toISOString(),test_mode:lead.test_mode===true,
    lead,
  };
}

Deno.serve(async (req) => {
  if(req.method==="GET")return jsonResponse(200,{ok:true,service:"commandcore-lead-source-adapter",version:SERVICE_VERSION,status:"healthy",public_ingress_enabled:false,external_action_started:false,supported_sources:Array.from(SUPPORTED_SOURCES)});
  if(req.method!=="POST")return jsonResponse(405,{ok:false,error:"method_not_allowed"});
  if(!isAuthenticated(req))return jsonResponse(401,{ok:false,error:"unauthorized"});
  const rawText=await req.text();if(new TextEncoder().encode(rawText).byteLength>MAX_BODY_BYTES)return jsonResponse(413,{ok:false,error:"payload_too_large"});
  let body:Record<string,unknown>;try{body=JSON.parse(rawText)}catch{return jsonResponse(400,{ok:false,error:"invalid_json"})}
  const sourceType=lower(body.source_type||body.source);if(!SUPPORTED_SOURCES.has(sourceType))return jsonResponse(422,{ok:false,error:"unsupported_source",supported_sources:Array.from(SUPPORTED_SOURCES)});
  try{
    const normalizedLead=normalizeLead(sourceType,body);
    if(!normalized(normalizedLead.phone)&&!normalized(normalizedLead.email))return jsonResponse(422,{ok:false,error:"lead_identity_required"});
    if((normalizedLead.sms_consent_state==="granted"||normalizedLead.email_consent_state==="granted")&&!normalized(normalizedLead.consent_evidence_reference)){
      return jsonResponse(422,{ok:false,error:"granted_consent_requires_evidence"});
    }
    const canonicalSource=sourceType==="website_form"||sourceType==="property_page"||sourceType==="facebook_lead";
    const useLegacyIntake=body.compatibility_mode==="legacy_lead_intake"||!canonicalSource;
    const destination=useLegacyIntake?"commandcore-lead-intake":"commandcore-inbound-lead-capture";
    const payload=useLegacyIntake?normalizedLead:{integration_event:canonicalEvent(sourceType,normalizedLead)};
    const intake=await forwardToFunction(destination,payload);
    return jsonResponse(intake.status,{ok:intake.status>=200&&intake.status<300,action:"normalize_and_forward_lead",canonical_destination:destination,legacy_intake_available:true,source_type:sourceType,source_event_id:normalizedLead.source_event_id||"",intake:intake.body,external_action_started:false});
  }catch(error){console.error("CommandCore lead source adapter failed",error);return jsonResponse(503,{ok:false,error:"lead_source_adapter_unavailable"})}
});
