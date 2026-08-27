const SEO_VERSION = "2026-08-27.1";
const MAX_BODY_BYTES = 24 * 1024;

function jsonResponse(status: number, payload: Record<string, unknown>): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let i = 0; i < left.length; i += 1) difference |= left.charCodeAt(i) ^ right.charCodeAt(i);
  return difference === 0;
}

function bearerToken(req: Request): string {
  const auth = req.headers.get("authorization") || "";
  return auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
}

function isAuthenticated(req: Request): boolean {
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const supplied = bearerToken(req);
  return Boolean(serviceRoleKey && supplied && constantTimeEqual(serviceRoleKey, supplied));
}

function slug(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
}

function money(value: unknown): string {
  const number = Number(String(value ?? "").replace(/[^0-9.\-]/g, ""));
  return Number.isFinite(number) ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(number) : "Contact us";
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-market-seo",
      version: SEO_VERSION,
      status: "healthy",
      external_action_started: false,
    });
  }

  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "payload_too_large" });
  }

  let body: Record<string, unknown>;
  try {
    body = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const property = body.property && typeof body.property === "object" && !Array.isArray(body.property)
    ? body.property as Record<string, unknown>
    : {};

  const city = String(property.city || "").trim();
  const state = String(property.state || "").trim().toUpperCase();
  const address = String(property.address || "").trim();
  const propertyId = String(property.property_id || "").trim();
  if (!city || !state || !propertyId) {
    return jsonResponse(422, { ok: false, error: "missing_market_seo_facts" });
  }

  const marketSlug = `${slug(city)}-${slug(state)}`;
  const propertySlug = slug(address || propertyId);
  const title = `Owner Financing Homes in ${city}, ${state} | Credit Friendly Homes`;
  const description = `Explore owner-financing opportunities in ${city}, ${state}. Current featured home: ${address || "available property"}. Price ${money(property.total_price)}, down payment ${money(property.down_payment)}, monthly payment ${money(property.monthly_payment)}. Terms and availability subject to verification.`;

  const seoRecord = {
    market_key: `${city.toLowerCase()}|${state}`,
    market_slug: marketSlug,
    property_id: propertyId,
    property_slug: propertySlug,
    page_path: `/owner-finance-homes/${marketSlug}`,
    title,
    meta_description: description,
    h1: `Owner Financing Homes in ${city}, ${state}`,
    canonical_key: `market:${marketSlug}`,
    updated_at: new Date().toISOString(),
    source: "commandcore_market_seo_adapter",
  };

  return jsonResponse(200, {
    ok: true,
    accepted: true,
    channel_key: "market_seo",
    status: "live",
    adapter: "cfh_market_seo",
    seo_record: seoRecord,
    external_action_started: false,
  });
});
