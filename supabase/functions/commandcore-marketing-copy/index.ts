const SERVICE_VERSION = "2026-08-27.1";

function jsonResponse(status:number,payload:Record<string,unknown>):Response{
  return new Response(JSON.stringify(payload),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}});
}
function normalized(v:unknown):string{return String(v??"").trim()}
function constantTimeEqual(left:string,right:string):boolean{if(left.length!==right.length)return false;let d=0;for(let i=0;i<left.length;i+=1)d|=left.charCodeAt(i)^right.charCodeAt(i);return d===0}
function bearer(req:Request):string{const a=req.headers.get("authorization")||"";return a.startsWith("Bearer ")?a.slice(7).trim():""}
function authed(req:Request):boolean{const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";const supplied=bearer(req);return Boolean(key&&supplied&&constantTimeEqual(key,supplied))}
function money(v:unknown):string{const n=Number(String(v??"").replace(/[^0-9.-]/g,""));return Number.isFinite(n)&&n>0?`$${Math.round(n).toLocaleString("en-US")}`:""}
function propertyFacts(body:Record<string,unknown>):Record<string,unknown>{const p=body.property&&typeof body.property==="object"&&!Array.isArray(body.property)?body.property as Record<string,unknown>:{};return p}
function channelSource(body:Record<string,unknown>,key:string):Record<string,unknown>{const channels=Array.isArray(body.channels)?body.channels:[];for(const item of channels){if(item&&typeof item==="object"&&!Array.isArray(item)){const row=item as Record<string,unknown>;if(normalized(row.channel_key||row.key)===key)return row}}return {}}
function appendCta(copy:string,url:string,cta:string):string{const clean=copy.trim();if(!url)return clean; if(clean.includes(url))return clean;return `${clean}${clean?"\n\n":""}${cta}: ${url}`.trim()}

Deno.serve(async(req)=>{
  if(req.method==="GET")return jsonResponse(200,{ok:true,service:"commandcore-marketing-copy",version:SERVICE_VERSION,status:"healthy",external_action_started:false});
  if(req.method!=="POST")return jsonResponse(405,{ok:false,error:"method_not_allowed"});
  if(!authed(req))return jsonResponse(401,{ok:false,error:"unauthorized"});
  let body:Record<string,unknown>={};try{body=await req.json()}catch{return jsonResponse(400,{ok:false,error:"invalid_json"})}
  const p=propertyFacts(body);const link=normalized(body.lead_form_url||p.lead_form_url);
  const address=normalized(p.address||p.property_address||"this home");const city=normalized(p.city);const state=normalized(p.state);const location=[city,state].filter(Boolean).join(", ");
  const down=money(p.down_payment||p.down_payment_amount||p.minimum_down_payment);const payment=money(p.monthly_payment||p.payment||p.monthly_payment_amount);const price=money(p.price||p.sale_price||p.purchase_price);
  const baseDetails=[address,location,price?`Price ${price}`:"",down?`Down payment ${down}`:"",payment?`Monthly payment ${payment}`:""].filter(Boolean).join(" • ");
  const channels=["facebook_marketplace","facebook_groups","facebook_page","instagram","tiktok","youtube","blog","email","sms","reactivation","market_seo"];
  const packages:Record<string,unknown>[]=[];
  for(const key of channels){const src=channelSource(body,key);const supplied=normalized(src.copy||src.body||src.caption||src.text);let copy=supplied||baseDetails;
    let subject="",headline="",cta="See details and tell us you're interested";
    if(key==="email"){subject=normalized(src.subject)||`Owner-financed home available${location?` in ${location}`:""}`;copy=appendCta(copy,link,"View the home");}
    else if(key==="sms"||key==="reactivation"){copy=appendCta(copy,link,"Details");}
    else if(key==="blog"||key==="market_seo"){headline=normalized(src.headline)||`${address}${location?` — ${location}`:""}`;copy=appendCta(copy,link,"Interested in this home?");}
    else {copy=appendCta(copy,link,cta);}
    packages.push({channel_key:key,subject,headline,copy,lead_form_url:link,cta_included:Boolean(link),external_action_started:false});
  }
  return jsonResponse(200,{ok:true,package_count:packages.length,lead_form_url:link,packages,external_action_started:false});
});
