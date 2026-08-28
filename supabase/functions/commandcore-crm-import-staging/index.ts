const SERVICE_VERSION = "2026-08-28.1";
const MAX_BODY_BYTES = 512 * 1024;
const MAX_ROWS = 2000;

type Row = Record<string, unknown>;

type EntityRule = {
  entity: string;
  fields: Record<string, string[]>;
  requiredAny: string[];
};

const RULES: EntityRule[] = [
  {
    entity: "contacts",
    fields: {
      external_id: ["id", "contact id", "contact_id", "lead id", "lead_id", "record id"],
      first_name: ["first name", "firstname", "first_name"],
      last_name: ["last name", "lastname", "last_name"],
      name: ["name", "full name", "contact name", "seller name", "buyer name"],
      phone: ["phone", "phone number", "mobile", "mobile phone", "cell", "primary phone"],
      email: ["email", "email address", "primary email"],
      company: ["company", "company name", "business"],
      tags: ["tags", "tag", "labels"],
      notes: ["notes", "note", "comments", "comment"],
    },
    requiredAny: ["phone", "email", "name", "first_name", "last_name"],
  },
  {
    entity: "properties",
    fields: {
      external_id: ["id", "property id", "property_id", "record id"],
      address: ["address", "property address", "street address", "address 1"],
      city: ["city", "property city"],
      state: ["state", "property state"],
      zip: ["zip", "zipcode", "zip code", "postal code"],
      county: ["county"],
      parcel_id: ["parcel", "parcel id", "apn", "pin"],
      bedrooms: ["beds", "bedrooms", "bed"],
      bathrooms: ["baths", "bathrooms", "bath"],
      square_feet: ["sqft", "square feet", "square_feet", "living area"],
      property_type: ["property type", "type"],
      notes: ["notes", "property notes"],
    },
    requiredAny: ["address", "parcel_id"],
  },
  {
    entity: "deals",
    fields: {
      external_id: ["id", "deal id", "deal_id", "lead id", "lead_id", "record id"],
      title: ["deal name", "title", "lead name"],
      status: ["status", "deal status", "lead status"],
      stage: ["stage", "pipeline stage", "deal stage"],
      source: ["source", "lead source", "marketing source"],
      asking_price: ["asking price", "ask", "seller asking"],
      offer_price: ["offer", "offer price", "our offer"],
      arv: ["arv", "after repair value"],
      estimated_repairs: ["repairs", "repair estimate", "estimated repairs"],
      assigned_to: ["assigned to", "owner", "acquisitions rep", "user"],
      notes: ["notes", "deal notes", "lead notes"],
    },
    requiredAny: ["title", "status", "stage", "asking_price", "offer_price"],
  },
];

function jsonResponse(status: number, payload: Row): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return difference === 0;
}

function isAuthenticated(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const auth = req.headers.get("authorization") || "";
  const supplied = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}

function text(value: unknown): string {
  return String(value ?? "").trim();
}

function canonicalHeader(value: unknown): string {
  return text(value).toLowerCase().replace(/[_-]+/g, " ").replace(/\s+/g, " ");
}

function nonEmpty(value: unknown): boolean {
  return value !== null && value !== undefined && text(value) !== "";
}

function normalizedPhone(value: unknown): string {
  const raw = text(value);
  const digits = raw.replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("1")) return digits.slice(1);
  return digits;
}

function normalizedEmail(value: unknown): string {
  return text(value).toLowerCase();
}

function normalizedAddress(row: Row): string {
  return [row.address, row.city, row.state, row.zip].map(text).filter(Boolean).join("|").toLowerCase().replace(/[^a-z0-9|]/g, "");
}

function aliasMap(rule: EntityRule): Map<string, string> {
  const map = new Map<string, string>();
  for (const [target, aliases] of Object.entries(rule.fields)) {
    map.set(canonicalHeader(target), target);
    for (const alias of aliases) map.set(canonicalHeader(alias), target);
  }
  return map;
}

function mapRow(sourceRow: Row, rule: EntityRule): { mapped: Row; unmapped: Row; mapping: Row } {
  const aliases = aliasMap(rule);
  const mapped: Row = {};
  const unmapped: Row = {};
  const mapping: Row = {};
  for (const [sourceKey, value] of Object.entries(sourceRow)) {
    const target = aliases.get(canonicalHeader(sourceKey));
    if (target && nonEmpty(value)) {
      if (!nonEmpty(mapped[target])) mapped[target] = value;
      mapping[sourceKey] = target;
    } else if (nonEmpty(value)) {
      unmapped[sourceKey] = value;
    }
  }
  return { mapped, unmapped, mapping };
}

function scoreRule(row: Row, rule: EntityRule): number {
  const result = mapRow(row, rule).mapped;
  const recognized = Object.keys(result).length;
  const required = rule.requiredAny.some((field) => nonEmpty(result[field]));
  return recognized + (required ? 4 : 0);
}

function inferEntity(row: Row, requested: string): EntityRule {
  const requestedRule = RULES.find((rule) => rule.entity === requested);
  if (requestedRule) return requestedRule;
  return [...RULES].sort((left, right) => scoreRule(row, right) - scoreRule(row, left))[0];
}

function makeExternalId(entity: string, source: string, mapped: Row, rowIndex: number): string {
  if (nonEmpty(mapped.external_id)) return text(mapped.external_id);
  if (entity === "contacts") {
    const email = normalizedEmail(mapped.email);
    const phone = normalizedPhone(mapped.phone);
    if (email) return `email:${email}`;
    if (phone) return `phone:${phone}`;
    const name = [mapped.first_name, mapped.last_name, mapped.name].map(text).filter(Boolean).join(" ").toLowerCase();
    if (name) return `name:${name}`;
  }
  if (entity === "properties") {
    if (nonEmpty(mapped.parcel_id)) return `parcel:${text(mapped.parcel_id).toLowerCase()}`;
    const address = normalizedAddress(mapped);
    if (address) return `address:${address}`;
  }
  if (entity === "deals") {
    const title = text(mapped.title).toLowerCase();
    if (title) return `title:${title}`;
  }
  return `${source}:row:${rowIndex + 1}`;
}

function duplicateKey(entity: string, mapped: Row): string {
  if (entity === "contacts") {
    const email = normalizedEmail(mapped.email);
    const phone = normalizedPhone(mapped.phone);
    if (email) return `contact:email:${email}`;
    if (phone) return `contact:phone:${phone}`;
  }
  if (entity === "properties") {
    const parcel = text(mapped.parcel_id).toLowerCase();
    if (parcel) return `property:parcel:${parcel}`;
    const address = normalizedAddress(mapped);
    if (address) return `property:address:${address}`;
  }
  if (entity === "deals") {
    const externalId = text(mapped.external_id).toLowerCase();
    if (externalId) return `deal:id:${externalId}`;
  }
  return "";
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-crm-import-staging",
      version: SERVICE_VERSION,
      status: "healthy",
      supported_entities: RULES.map((rule) => rule.entity),
      commit_enabled: false,
      destructive_delete_enabled: false,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large" });

  let body: Row;
  try {
    body = JSON.parse(raw || "{}") as Row;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const source = text(body.source || "import").toLowerCase().replace(/[^a-z0-9._-]+/g, "-") || "import";
  const requestedEntity = text(body.entity).toLowerCase();
  const rows = Array.isArray(body.rows)
    ? body.rows.filter((row) => row && typeof row === "object" && !Array.isArray(row)).slice(0, MAX_ROWS) as Row[]
    : [];
  if (!rows.length) return jsonResponse(422, { ok: false, error: "rows_required" });

  const staged: Row[] = [];
  const duplicates = new Map<string, number[]>();
  const mappingSummary: Record<string, number> = {};

  rows.forEach((sourceRow, index) => {
    const rule = inferEntity(sourceRow, requestedEntity);
    const { mapped, unmapped, mapping } = mapRow(sourceRow, rule);
    for (const target of Object.values(mapping).map(text)) mappingSummary[target] = (mappingSummary[target] || 0) + 1;
    const externalId = makeExternalId(rule.entity, source, mapped, index);
    const record: Row = {
      ...mapped,
      source,
      external_id: externalId,
      import_metadata: {
        row_number: index + 1,
        original_columns: Object.keys(sourceRow),
        unmapped_columns: Object.keys(unmapped),
      },
    };
    const key = duplicateKey(rule.entity, record);
    if (key) duplicates.set(key, [...(duplicates.get(key) || []), index]);
    staged.push({
      row_number: index + 1,
      entity: rule.entity,
      confidence: scoreRule(sourceRow, rule) >= 6 ? "high" : scoreRule(sourceRow, rule) >= 3 ? "medium" : "low",
      record,
      unmapped,
      mapping,
      duplicate_key: key || null,
      duplicate_in_file: false,
      ready_for_import: rule.requiredAny.some((field) => nonEmpty(mapped[field])),
    });
  });

  const duplicateIndexes = new Set<number>();
  for (const indexes of duplicates.values()) if (indexes.length > 1) indexes.forEach((index) => duplicateIndexes.add(index));
  staged.forEach((row, index) => {
    if (duplicateIndexes.has(index)) row.duplicate_in_file = true;
  });

  const ready = staged.filter((row) => row.ready_for_import === true && row.duplicate_in_file !== true).length;
  const duplicateGroups = [...duplicates.entries()].filter(([, indexes]) => indexes.length > 1).map(([key, indexes]) => ({
    key,
    row_numbers: indexes.map((index) => index + 1),
  }));

  return jsonResponse(200, {
    ok: true,
    source,
    requested_entity: requestedEntity || "auto",
    input_rows: rows.length,
    staged_rows: staged.length,
    ready_for_import: ready,
    needs_review: staged.length - ready,
    duplicate_groups: duplicateGroups,
    mapping_summary: mappingSummary,
    staged,
    commit_performed: false,
    destructive_delete_used: false,
    external_action_started: false,
  });
});
