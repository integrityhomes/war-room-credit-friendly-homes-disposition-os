const SERVICE_VERSION = "2026-08-27.1";
const CONTACT_BUCKET = "commandcore-contact-registry";
const MAX_BODY_BYTES = 64 * 1024;

function jsonResponse(status: number, payload: Record<string, unknown>): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}
function normalized(value: unknown): string { return String(value ?? "").trim(); }
function safeId(value: unknown): string { return normalized(value).replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 120); }
function numberOrNull(value: unknown): number | null { if (value === null || value === undefined || value === "") return null; const n = Number(value); return Number.isFinite(n) ? n : null; }
function stringArray(value: unknown): string[] { return Array.isArray(value) ? value.map(normalized).filter(Boolean) : []; }
function bearerToken(req: Request): string { const auth = req.headers.get("authorization") || ""; return auth.startsWith("Bearer ") ? auth.slice(7).trim() : ""; }
function constantTimeEqual(a: string, b: string): boolean { if (a.length !== b.length) return false; let d = 0; for (let i=0;i<a.length;i++) d |= a.charCodeAt(i)^b.charCodeAt(i); return d===0; }
function isAuthenticated(req: Request): boolean { const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||""; const supplied=bearerToken(req); return Boolean(key&&supplied&&constantTimeEqual(key,supplied)); }
function storageConfig() { const supabaseUrl=(Deno.env.get("SUPABASE_URL")||"").replace(/\/$/,""); const serviceRoleKey=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||""; if(!supabaseUrl||!serviceRoleKey) throw new Error("storage_not_configured"); return {supabaseUrl,serviceRoleKey}; }
function headers(key:string):HeadersInit { return {authorization:`Bearer ${key}`,apikey:key,"content-type":"application/json"}; }
async function readContact(contactId:string):Promise<Record<string,unknown>|null>{ const {supabaseUrl,serviceRoleKey}=storageConfig(); const r=await fetch(`${supabaseUrl}/storage/v1/object/${CONTACT_BUCKET}/contacts/${contactId}.json`,{headers:headers(serviceRoleKey)}); if(r.status===404)return null; if(!r.ok)throw new Error(`contact_read_failed_${r.status}`); const j=await r.json(); return j&&typeof j==="object"&&!Array.isArray(j)?j as Record<string,unknown>:null; }
async function writeContact(contactId:string,payload:Record<string,unknown>):Promise<void>{ const {supabaseUrl,serviceRoleKey}=storageConfig(); const r=await fetch(`${supabaseUrl}/storage/v1/object/${CONTACT_BUCKET}/contacts/${contactId}.json`,{method:"POST",headers:{...headers(serviceRoleKey),"x-upsert":"true"},body:JSON.stringify(payload)}); if(!r.ok)throw new Error(`contact_write_failed_${r.status}`); }

Deno.serve(async(req)=>{
  if(req.method==="GET") return jsonResponse(200,{ok:true,service:"commandcore-buyer-profile",version:SERVICE_VERSION,status:"healthy",external_action_started:false});
  if(req.method!=="POST") return jsonResponse(405,{ok:false,error:"method_not_allowed"});
  if(!isAuthenticated(req)) return jsonResponse(401,{ok:false,error:"unauthorized"});
  const raw=await req.text(); if(new TextEncoder().encode(raw).byteLength>MAX_BODY_BYTES) return jsonResponse(413,{ok:false,error:"payload_too_large"});
  let body:Record<string,unknown>; try{body=JSON.parse(raw);}catch{return jsonResponse(400,{ok:false,error:"invalid_json"});}
  try{
    const contactId=safeId(body.contact_id); if(!contactId)return jsonResponse(422,{ok:false,error:"contact_id_required"});
    const contact=await readContact(contactId); if(!contact)return jsonResponse(404,{ok:false,error:"contact_not_found"});
    const action=normalized(body.action).toLowerCase()||"update_preferences";
    if(action==="get_preferences") return jsonResponse(200,{ok:true,contact_id:contactId,market_preferences:contact.market_preferences||[],buyer_preferences:contact.buyer_preferences||{}});
    if(action!=="update_preferences") return jsonResponse(422,{ok:false,error:"unsupported_action"});
    const current=contact.buyer_preferences&&typeof contact.buyer_preferences==="object"&&!Array.isArray(contact.buyer_preferences)?contact.buyer_preferences as Record<string,unknown>:{};
    const prefs:Record<string,unknown>={
      ...current,
      property_types: body.property_types!==undefined?stringArray(body.property_types):(current.property_types||[]),
      max_purchase_price: body.max_purchase_price!==undefined?numberOrNull(body.max_purchase_price):(current.max_purchase_price??null),
      max_monthly_payment: body.max_monthly_payment!==undefined?numberOrNull(body.max_monthly_payment):(current.max_monthly_payment??null),
      min_down_payment: body.min_down_payment!==undefined?numberOrNull(body.min_down_payment):(current.min_down_payment??null),
      max_down_payment: body.max_down_payment!==undefined?numberOrNull(body.max_down_payment):(current.max_down_payment??null),
      min_bedrooms: body.min_bedrooms!==undefined?numberOrNull(body.min_bedrooms):(current.min_bedrooms??null),
      min_bathrooms: body.min_bathrooms!==undefined?numberOrNull(body.min_bathrooms):(current.min_bathrooms??null),
      financing_preferences: body.financing_preferences!==undefined?stringArray(body.financing_preferences):(current.financing_preferences||[]),
      condition_preferences: body.condition_preferences!==undefined?stringArray(body.condition_preferences):(current.condition_preferences||[]),
      notes: body.notes!==undefined?normalized(body.notes):(current.notes||""),
      updated_at:new Date().toISOString()
    };
    const marketPreferences=body.market_preferences!==undefined?stringArray(body.market_preferences):(Array.isArray(contact.market_preferences)?contact.market_preferences:[]);
    await writeContact(contactId,{...contact,market_preferences:marketPreferences,buyer_preferences:prefs,updated_at:new Date().toISOString()});
    return jsonResponse(200,{ok:true,action:"update_preferences",contact_id:contactId,market_preferences:marketPreferences,buyer_preferences:prefs,external_action_started:false});
  }catch(error){ console.error("CommandCore buyer profile failed",error); return jsonResponse(503,{ok:false,error:"buyer_profile_unavailable"}); }
});
