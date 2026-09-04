const SERVICE_VERSION = "2026-09-04.1";
const FORM_VERSION = "cfh-property-interest-v1";
const MAX_BODY_BYTES = 32 * 1024;
const RATE_BUCKET = "commandcore-public-ingress";
const RATE_LIMIT = 12;
const RATE_WINDOW_MS = 10 * 60 * 1000;
const ALLOWED_SOURCES = new Set(["property_page", "website_form"]);
const ALLOWED_LEAD_TYPES = new Set(["seller", "buyer", "owner_finance_buyer", "investor_buyer_interest"]);

function jsonResponse(status:number,payload:Record<string,unknown>,origin=""):Response{
  const headers:Record<string,string>={"content-type":"application/json; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff"};
  if(origin){headers["access-control-allow-origin"]=origin;headers["vary"]="Origin";headers["access-control-allow-methods"]="POST, OPTIONS";headers["access-control-allow-headers"]="content-type";}
  return new Response(JSON.stringify(payload),{status,headers});
}
function htmlResponse(html:string):Response{return new Response(html,{status:200,headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff","content-security-policy":"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors *"}})}
function normalized(v:unknown):string{return String(v??"").trim()}
function lower(v:unknown):string{return normalized(v).toLowerCase()}
function escapeHtml(v:unknown):string{return normalized(v).replace(/[&<>'"]/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[ch]||ch))}
function configuredOrigins():Set<string>{return new Set((Deno.env.get("CFH_PUBLIC_LEAD_ORIGINS")||"").split(",").map(v=>v.trim()).filter(Boolean))}
function publicTestMode():boolean{return lower(Deno.env.get("COMMANDCORE_PUBLIC_LEAD_MODE")||"test")!=="production"}
function allowedOrigin(req:Request):string{
  const origin=req.headers.get("origin")||"";
  if(!origin)return "";
  const selfOrigin=new URL(req.url).origin;
  if(origin===selfOrigin)return origin;
  const allowed=configuredOrigins();
  return allowed.has(origin)?origin:"";
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

function renderPropertyForm(url:URL):string{
  const propertyId=escapeHtml(url.searchParams.get("property_id")||"");
  const address=escapeHtml(url.searchParams.get("address")||"This Home");
  const city=escapeHtml(url.searchParams.get("city")||"");
  const state=escapeHtml(url.searchParams.get("state")||"");
  const requestedLeadType=lower(url.searchParams.get("lead_type")||"buyer");
  const leadType=ALLOWED_LEAD_TYPES.has(requestedLeadType)?requestedLeadType:"buyer";
  const campaign=escapeHtml(url.searchParams.get("campaign")||url.searchParams.get("utm_campaign")||"");
  const sourceDetail=escapeHtml(url.searchParams.get("utm_source")||"");
  const medium=escapeHtml(url.searchParams.get("utm_medium")||"");
  const displayLocation=[city,state].filter(Boolean).join(", ");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>I'm Interested - Credit Friendly Homes</title><style>body{font-family:Arial,sans-serif;background:#f6f7f8;margin:0;color:#1f2937}.wrap{max-width:620px;margin:0 auto;padding:24px}.card{background:#fff;border-radius:16px;padding:24px;box-shadow:0 8px 30px rgba(0,0,0,.08)}h1{margin:0 0 8px;font-size:28px}.sub{color:#6b7280;margin-bottom:22px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.full{grid-column:1/-1}label{display:block;font-size:14px;font-weight:700;margin-bottom:5px}input,textarea{box-sizing:border-box;width:100%;padding:12px;border:1px solid #d1d5db;border-radius:9px;font-size:16px}textarea{min-height:95px}.consent{display:flex;gap:9px;align-items:flex-start;margin-top:14px;font-size:13px;color:#4b5563}.consent input{width:auto;margin-top:3px}button{width:100%;padding:14px;border:0;border-radius:10px;background:#111827;color:white;font-size:16px;font-weight:700;margin-top:18px;cursor:pointer}.msg{margin-top:14px;font-weight:700}.hidden{position:absolute;left:-9999px}@media(max-width:560px){.grid{grid-template-columns:1fr}}</style></head><body><div class="wrap"><div class="card"><h1>Interested in ${address}?</h1><div class="sub">${displayLocation||"Tell us how to reach you and what payment range works for you."}</div><form id="leadForm"><div class="grid"><div><label>First name</label><input name="first_name" autocomplete="given-name"></div><div><label>Last name</label><input name="last_name" autocomplete="family-name"></div><div><label>Phone</label><input name="phone" type="tel" autocomplete="tel"></div><div><label>Email</label><input name="email" type="email" autocomplete="email"></div><div><label>Down payment available</label><input name="down_payment" inputmode="numeric" placeholder="$"></div><div><label>Target monthly payment</label><input name="monthly_payment" inputmode="numeric" placeholder="$"></div><div class="full"><label>Questions or notes</label><textarea name="message" placeholder="Tell us anything that would help us match you with the right home."></textarea></div></div><input class="hidden" tabindex="-1" autocomplete="off" name="website"><input type="hidden" name="property_id" value="${propertyId}"><input type="hidden" name="property_address" value="${address}"><input type="hidden" name="lead_type" value="${leadType}"><input type="hidden" name="campaign" value="${campaign}"><input type="hidden" name="source_detail" value="${sourceDetail}"><input type="hidden" name="medium" value="${medium}"><label class="consent"><input id="smsConsent" type="checkbox"><span>I agree to receive text messages about this property and similar Credit Friendly Homes opportunities. Message/data rates may apply. Reply STOP to opt out.</span></label><label class="consent"><input id="emailConsent" type="checkbox"><span>I agree to receive email updates about this property and similar home opportunities.</span></label><button type="submit">Send My Information</button><div id="msg" class="msg" aria-live="polite"></div></form></div></div><script>const form=document.getElementById('leadForm'),msg=document.getElementById('msg');form.addEventListener('submit',async(e)=>{e.preventDefault();msg.textContent='Sending...';const data=Object.fromEntries(new FormData(form).entries());if(!data.phone&&!data.email){msg.textContent='Please enter a phone number or email.';return;}data.source_type='property_page';data.source_event_id=crypto.randomUUID();const sms=document.getElementById('smsConsent').checked,email=document.getElementById('emailConsent').checked;data.sms_consent_state=sms?'granted':'unknown';data.email_consent_state=email?'granted':'unknown';if(sms||email)data.consent_evidence_reference='${FORM_VERSION}:'+data.source_event_id;try{const r=await fetch(location.pathname,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(data)});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||'submit_failed');msg.textContent='Got it. Your information was saved.';form.reset();}catch(err){msg.textContent='We could not save this right now. Please try again.';}});</script></body></html>`;
}

Deno.serve(async (req) => {
  const url=new URL(req.url);
  if(req.method==="GET"&&url.pathname.endsWith("/form"))return htmlResponse(renderPropertyForm(url));
  if(req.method==="GET")return jsonResponse(200,{ok:true,service:"commandcore-public-lead-gateway",version:SERVICE_VERSION,status:"healthy",public_ingress_enabled:true,hosted_property_form:true,form_path:"/form",allowed_sources:Array.from(ALLOWED_SOURCES),external_action_started:false});
  const origin=allowedOrigin(req);
  if(req.method==="OPTIONS")return origin?new Response(null,{status:204,headers:{"access-control-allow-origin":origin,"access-control-allow-methods":"POST, OPTIONS","access-control-allow-headers":"content-type","access-control-max-age":"600","vary":"Origin"}}):jsonResponse(403,{ok:false,error:"origin_not_allowed"});
  if(req.method!=="POST")return jsonResponse(405,{ok:false,error:"method_not_allowed"},origin);
  if(!origin)return jsonResponse(403,{ok:false,error:"origin_not_allowed"});
  const contentType=lower(req.headers.get("content-type"));if(!contentType.includes("application/json"))return jsonResponse(415,{ok:false,error:"json_required"},origin);
  const raw=await req.text();if(new TextEncoder().encode(raw).byteLength>MAX_BODY_BYTES)return jsonResponse(413,{ok:false,error:"payload_too_large"},origin);
  let body:Record<string,unknown>;try{body=JSON.parse(raw)}catch{return jsonResponse(400,{ok:false,error:"invalid_json"},origin)}
  if(normalized(body.website||body.company||body.middle_name||body.honeypot))return jsonResponse(202,{ok:true,accepted:true},origin);
  const source=lower(body.source_type||body.source||"property_page");if(!ALLOWED_SOURCES.has(source))return jsonResponse(422,{ok:false,error:"unsupported_public_source"},origin);
  const leadType=lower(body.lead_type||body.lead_category||"buyer");if(!ALLOWED_LEAD_TYPES.has(leadType))return jsonResponse(422,{ok:false,error:"unsupported_lead_type"},origin);
  const phone=normalized(body.phone);const email=lower(body.email);if(!phone&&!email)return jsonResponse(422,{ok:false,error:"lead_identity_required"},origin);
  if(phone.length>40||email.length>254||normalized(body.notes||body.message).length>4000)return jsonResponse(422,{ok:false,error:"field_too_long"},origin);
  try{
    if(!(await rateAllowed(clientIp(req))))return jsonResponse(429,{ok:false,error:"rate_limited"},origin);
    const payload:Record<string,unknown>={source_type:source,payload:{...body,test_mode:publicTestMode(),source_type:undefined,source:undefined,website:undefined,company:undefined,middle_name:undefined,honeypot:undefined},source_event_id:normalized(body.source_event_id)||crypto.randomUUID()};
    const sms=lower(body.sms_consent_state);const emailState=lower(body.email_consent_state);const evidence=normalized(body.consent_evidence_reference);
    if((sms==="granted"||emailState==="granted")&&!evidence)return jsonResponse(422,{ok:false,error:"granted_consent_requires_evidence"},origin);
    const result=await forward(payload);
    if(result.status<200||result.status>=300)return jsonResponse(502,{ok:false,error:"lead_intake_failed"},origin);
    return jsonResponse(202,{ok:true,accepted:true,source_type:source,external_action_started:false},origin);
  }catch(error){console.error("CommandCore public lead gateway failed",error);return jsonResponse(503,{ok:false,error:"lead_gateway_unavailable"},origin)}
});
