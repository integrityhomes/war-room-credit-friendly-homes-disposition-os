const SERVICE_VERSION = "2026-08-27.1";
const CONTACT_BUCKET = "commandcore-contact-registry";
const MAX_BODY_BYTES = 64 * 1024;
const MAX_CONTACTS = 1000;

function jsonResponse(status: number, payload: Record<string, unknown>): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function bearerToken(req: Request): string {
  const auth = req.headers.get("authorization") || "";
  return auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let i = 0; i < left.length; i += 1) difference |= left.charCodeAt(i) ^ right.charCodeAt(i);
  return difference === 0;
}

function isAuthenticated(req: Request): boolean {
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const supplied = bearerToken(req);
  return Boolean(key && supplied && constantTimeEqual(key, supplied));
}

function normalized(value: unknown): string {
  return String(value ?? "").trim();
}

function lower(value: unknown): string {
  return normalized(value).toLowerCase();
}

function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function arrayOfStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => lower(item)).filter(Boolean) : [];
}

function storageConfig() {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) throw new Error("storage_not_configured");
  return { supabaseUrl, serviceRoleKey };
}

function storageHeaders(serviceRoleKey: string): HeadersInit {
  return {
    authorization: `Bearer ${serviceRoleKey}`,
    apikey: serviceRoleKey,
    "content-type": "application/json",
  };
}

async function listContactFiles(): Promise<string[]> {
  const { supabaseUrl, serviceRoleKey } = storageConfig();
  const response = await fetch(`${supabaseUrl}/storage/v1/object/list/${CONTACT_BUCKET}`, {
    method: "POST",
    headers: storageHeaders(serviceRoleKey),
    body: JSON.stringify({ prefix: "contacts", limit: MAX_CONTACTS, offset: 0, sortBy: { column: "name", order: "asc" } }),
  });
  if (response.status === 404) return [];
  if (!response.ok) throw new Error(`contact_list_failed_${response.status}`);
  const rows = await response.json();
  if (!Array.isArray(rows)) return [];
  return rows
    .map((row) => row && typeof row === "object" ? normalized((row as Record<string, unknown>).name) : "")
    .filter((name) => name.endsWith(".json"))
    .map((name) => `contacts/${name}`);
}

async function readContact(path: string): Promise<Record<string, unknown> | null> {
  const { supabaseUrl, serviceRoleKey } = storageConfig();
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${CONTACT_BUCKET}/${path}`, {
    headers: storageHeaders(serviceRoleKey),
  });
  if (!response.ok) return null;
  const parsed = await response.json();
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
}

function consentState(contact: Record<string, unknown>, channel: "sms" | "email"): string {
  const consent = contact.consent && typeof contact.consent === "object" && !Array.isArray(contact.consent)
    ? contact.consent as Record<string, unknown>
    : {};
  const snapshot = consent[channel] && typeof consent[channel] === "object" && !Array.isArray(consent[channel])
    ? consent[channel] as Record<string, unknown>
    : {};
  return lower(snapshot.state) || "unknown";
}

function preferenceObject(contact: Record<string, unknown>): Record<string, unknown> {
  const value = contact.buyer_preferences;
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function marketMatches(contact: Record<string, unknown>, city: string, state: string, zip: string): boolean {
  const prefs = arrayOfStrings(contact.market_preferences);
  if (prefs.length === 0) return true;
  const candidates = [city, state, zip, `${city}, ${state}`, `${city} ${state}`].filter(Boolean).map((v) => v.toLowerCase());
  return prefs.some((pref) => candidates.some((candidate) => candidate.includes(pref) || pref.includes(candidate)));
}

function rangePass(maximum: number | null, value: number | null): boolean {
  if (maximum === null || value === null) return true;
  return value <= maximum;
}

function minimumPass(minimum: number | null, value: number | null): boolean {
  if (minimum === null || value === null) return true;
  return value >= minimum;
}

function scoreContact(contact: Record<string, unknown>, property: Record<string, unknown>) {
  const status = lower(contact.status) || "active";
  if (status === "inactive" || status === "suppressed") return null;

  const prefs = preferenceObject(contact);
  const city = lower(property.city);
  const state = lower(property.state);
  const zip = lower(property.zip);
  const propertyType = lower(property.property_type);
  const price = numberOrNull(property.purchase_price ?? property.price ?? property.sale_price);
  const monthly = numberOrNull(property.monthly_payment ?? property.payment);
  const down = numberOrNull(property.down_payment ?? property.down);

  const marketOk = marketMatches(contact, city, state, zip);
  const types = arrayOfStrings(prefs.property_types);
  const propertyTypeOk = types.length === 0 || !propertyType || types.includes(propertyType);
  const priceOk = rangePass(numberOrNull(prefs.max_purchase_price), price);
  const monthlyOk = rangePass(numberOrNull(prefs.max_monthly_payment), monthly);
  const downMaxOk = rangePass(numberOrNull(prefs.max_down_payment), down);
  const downMinOk = minimumPass(numberOrNull(prefs.min_down_payment), down);

  if (!marketOk || !propertyTypeOk || !priceOk || !monthlyOk || !downMaxOk || !downMinOk) return null;

  let score = 20;
  const reasons: string[] = [];
  if (marketOk) { score += 35; reasons.push("market_match"); }
  if (propertyTypeOk && types.length > 0) { score += 10; reasons.push("property_type_match"); }
  if (priceOk && numberOrNull(prefs.max_purchase_price) !== null && price !== null) { score += 10; reasons.push("price_fit"); }
  if (monthlyOk && numberOrNull(prefs.max_monthly_payment) !== null && monthly !== null) { score += 10; reasons.push("payment_fit"); }
  if (downMaxOk && numberOrNull(prefs.max_down_payment) !== null && down !== null) { score += 5; reasons.push("down_payment_fit"); }

  const smsState = consentState(contact, "sms");
  const emailState = consentState(contact, "email");
  const smsEligible = Boolean(normalized(contact.phone)) && smsState === "granted";
  const emailEligible = Boolean(normalized(contact.email)) && emailState === "granted";
  if (smsEligible) score += 5;
  if (emailEligible) score += 5;

  return {
    contact_id: normalized(contact.contact_id),
    first_name: normalized(contact.first_name),
    last_name: normalized(contact.last_name),
    score: Math.min(score, 100),
    reasons,
    sms_eligible: smsEligible,
    email_eligible: emailEligible,
    sms_consent_state: smsState,
    email_consent_state: emailState,
    market_preferences: contact.market_preferences || [],
    buyer_preferences: prefs,
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-buyer-matcher",
      version: SERVICE_VERSION,
      status: "healthy",
      external_delivery_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large" });

  let body: Record<string, unknown>;
  try { body = JSON.parse(raw) as Record<string, unknown>; }
  catch { return jsonResponse(400, { ok: false, error: "invalid_json" }); }

  try {
    const action = lower(body.action) || "match_buyers";
    if (action !== "match_buyers") return jsonResponse(422, { ok: false, error: "unsupported_action" });
    const property = body.property && typeof body.property === "object" && !Array.isArray(body.property)
      ? body.property as Record<string, unknown>
      : body;
    const files = await listContactFiles();
    const contacts = (await Promise.all(files.map(readContact))).filter(Boolean) as Record<string, unknown>[];
    const matches = contacts
      .map((contact) => scoreContact(contact, property))
      .filter(Boolean)
      .sort((a, b) => (b!.score as number) - (a!.score as number));

    return jsonResponse(200, {
      ok: true,
      action: "match_buyers",
      matched_count: matches.length,
      sms_ready_count: matches.filter((item) => item!.sms_eligible).length,
      email_ready_count: matches.filter((item) => item!.email_eligible).length,
      matches,
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore buyer matcher failed", error);
    return jsonResponse(503, { ok: false, error: "buyer_matcher_unavailable" });
  }
});
