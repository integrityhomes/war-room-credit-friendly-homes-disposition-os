const SERVICE_VERSION = "2026-08-27.1";
const MAX_BODY_BYTES = 64 * 1024;

function jsonResponse(status:number,payload:Record<string,unknown>):Response{return new Response(JSON.stringify(payload),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}});}
function normalized(v:unknown):string{return String(v??"").trim();}
function bearerToken(req:Request):string{const a=req.headers.get("authorization")||"";return a.startsWith("Bearer ")?a.slice(7).trim():"";}
function constantTimeEqual(a:string,b:string):boolean{if(a.length!==b.length)return false;let d=0;for(let i=0;i<a.length;i++)d|=a.charCodeAt(i)^b.charCodeAt(i);return d===0;}
function isAuthenticated(req:Request):boolean{const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";const supplied=bearerToken(req);return Boolean(key&&supplied&&constantTimeEqual(key,supplied));}
function stringArray(v:unknown):string[]{return Array.isArray(v)?v.map(normalized).filter(Boolean):[];}
function hasPreferenceData(body:Record<string,unknown>):boolean{return ["market_preferences","property_types","max_purchase_price","max_monthly_payment","min_down_payment","max_down_payment","min_bedrooms","min_bathrooms","financing_preferences","condition_preferences","notes"].some((k)=>body[k]!==undefined);}
function envConfig(){const url=(Deno.env.get("SUPABASE_URL")||"").replace(/\/$/,"");const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";if(!url||!key)throw new Error("supabase_not_configured");return{url,key};}
async function callFunction(name:string,payload:Record<string,unknown>){const{url,key}=envConfig();const response=await fetch(`${url}/functions/v1/${name}`,{method:"POST",headers:{authorization:`Bearer ${key}`,apikey:key,"content-type":"application/json"},body:JSON.stringify(payload)});const text=await response.text();let data:Record<string,unknown>={};try{data=JSON.parse(text);}catch{data={raw:text};}if(!response.ok)throw new Error(`${name}_${response.status}_${normalized(data.error)}`);return data;}
function contactPayload(body:Record<string,unknown>):Record<string,unknown>{return{action:"upsert_contact",contact_id:body.contact_id,first_name:body.first_name,last_name:body.last_name,phone:body.phone,email:body.email,source:normalized(body.source)||"lead_intake",status:normalized(body.status)||"active",tags:stringArray(body.tags),market_preferences:stringArray(body.market_preferences)};}
function preferencePayload(contactId:string,body:Record<string,unknown>):Record<string,unknown>{return{action:"update_preferences",contact_id:contactId,market_preferences:body.market_preferences,property_types:body.property_types,max_purchase_price:body.max_purchase_price,max_monthly_payment:body.max_monthly_payment,min_down_payment:body.min_down_payment,max_down_payment:body.max_down_payment,min_bedrooms:body.min_bedrooms,min_bathrooms:body.min_bathrooms,financing_preferences:body.financing_preferences,condition_preferences:body.condition_preferences,notes:body.notes};}
async function maybeRecordConsent(contactId:string,channel:"sms"|"email",body:Record<string,unknown>){const state=normalized(body[`${channel}_consent_state`]).toLowerCase();if(!state)return null;const evidence=normalized(body[`${channel}_consent_evidence`]);const source=normalized(body[`${channel}_consent_source`])||normalized(body.source)||"lead_intake";if(state==="granted"&&!evidence)return{channel,state,recorded:false,reason:"evidence_required_for_granted_consent"};const result=await callFunction("commandcore-contact-ledger",{action:"record_consent",contact_id:contactId,channel,state,source,evidence_reference:evidence,recorded_by:"commandcore-lead-intake"});return{channel,state,recorded:true,event_id:result.event_id};}

Deno.serve(async(req)=>{
  if(req.method==="GET")return jsonResponse(200,{ok:true,service:"commandcore-lead-intake",version:SERVICE_VERSION,status:"healthy",external_action_started:false});
  if(req.method!=="POST")return jsonResponse(405,{ok:false,error:"method_not_allowed"});
  if(!isAuthenticated(req))return jsonResponse(401,{ok:false,error:"unauthorized"});
  const raw=await req.text();if(new TextEncoder().encode(raw).byteLength>MAX_BODY_BYTES)return jsonResponse(413,{ok:false,error:"payload_too_large"});
  let body:Record<string,unknown>;try{body=JSON.parse(raw);}catch{return jsonResponse(400,{ok:false,error:"invalid_json"});}
  if(!normalized(body.phone)&&!normalized(body.email)&&!normalized(body.contact_id))return jsonResponse(422,{ok:false,error:"lead_identity_required"});
  try{
    const contact=await callFunction("commandcore-contact-ledger",contactPayload(body));
    const contactId=normalized(contact.contact_id);if(!contactId)throw new Error("contact_id_missing_after_upsert");
    let preferences:null|Record<string,unknown>=null;
    if(hasPreferenceData(body))preferences=await callFunction("commandcore-buyer-profile",preferencePayload(contactId,body));
    const consentResults=[];
    const sms=await maybeRecordConsent(contactId,"sms",body);if(sms)consentResults.push(sms);
    const email=await maybeRecordConsent(contactId,"email",body);if(email)consentResults.push(email);
    return jsonResponse(200,{ok:true,action:"ingest_lead",contact_id:contactId,source:normalized(body.source)||"lead_intake",contact_saved:true,preferences_updated:Boolean(preferences),consent_results:consentResults,external_action_started:false});
  }catch(error){console.error("CommandCore lead intake failed",error);return jsonResponse(503,{ok:false,error:"lead_intake_unavailable"});}
});
