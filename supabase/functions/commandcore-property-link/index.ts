const SERVICE_VERSION = "2026-08-27.1";

function jsonResponse(status:number,payload:Record<string,unknown>):Response{
  return new Response(JSON.stringify(payload),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}});
}
function normalized(v:unknown):string{return String(v??"").trim()}
function constantTimeEqual(left:string,right:string):boolean{if(left.length!==right.length)return false;let difference=0;for(let i=0;i<left.length;i+=1)difference|=left.charCodeAt(i)^right.charCodeAt(i);return difference===0}
function bearerToken(req:Request):string{const auth=req.headers.get("authorization")||"";return auth.startsWith("Bearer ")?auth.slice(7).trim():""}
function isAuthenticated(req:Request):boolean{const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";const supplied=bearerToken(req);return Boolean(key&&supplied&&constantTimeEqual(key,supplied))}
function safeUrlBase():string{const base=(Deno.env.get("SUPABASE_URL")||"").replace(/\/$/,"");if(!base)throw new Error("supabase_url_missing");return base}

Deno.serve(async(req)=>{
  if(req.method==="GET")return jsonResponse(200,{ok:true,service:"commandcore-property-link",version:SERVICE_VERSION,status:"healthy",external_action_started:false});
  if(req.method!=="POST")return jsonResponse(405,{ok:false,error:"method_not_allowed"});
  if(!isAuthenticated(req))return jsonResponse(401,{ok:false,error:"unauthorized"});
  let body:Record<string,unknown>={};try{body=await req.json()}catch{return jsonResponse(400,{ok:false,error:"invalid_json"})}
  const property=body.property&&typeof body.property==="object"&&!Array.isArray(body.property)?body.property as Record<string,unknown>:body;
  const propertyId=normalized(property.property_id||property.id||property.record_id);
  const address=normalized(property.address||property.property_address);
  const city=normalized(property.city);
  const state=normalized(property.state);
  if(!propertyId&&!address)return jsonResponse(422,{ok:false,error:"property_identity_required"});
  const url=new URL(`${safeUrlBase()}/functions/v1/commandcore-public-lead-gateway/form`);
  if(propertyId)url.searchParams.set("property_id",propertyId);
  if(address)url.searchParams.set("address",address);
  if(city)url.searchParams.set("city",city);
  if(state)url.searchParams.set("state",state);
  return jsonResponse(200,{ok:true,property_id:propertyId,property_address:address,lead_form_url:url.toString(),form_version:"cfh-property-interest-v1",external_action_started:false});
});
