const SERVICE_VERSION = "2026-08-29.1";
const MAX_BODY_BYTES = 32 * 1024;

type Row = Record<string, unknown>;

function text(value: unknown): string {
  return String(value ?? "").trim();
}

function obj(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

function links(record: Row): Row {
  return obj(record.links);
}

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

function authed(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const authorization = req.headers.get("authorization") || "";
  const supplied = authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}

async function crmCall(url: string, key: string, payload: Row): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/commandcore-crm-core`, {
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) throw new Error(text(parsed.error) || `crm_call_failed_${response.status}`);
  return parsed;
}

async function listEntity(url: string, key: string, entity: string): Promise<Row[]> {
  const result = await crmCall(url, key, { action: "list", entity, limit: 500 });
  return Array.isArray(result.records)
    ? result.records.filter((item) => item && typeof item === "object" && !Array.isArray(item)) as Row[]
    : [];
}

async function upsertEntity(url: string, key: string, entity: string, record: Row): Promise<Row> {
  const result = await crmCall(url, key, { action: "upsert", entity, record });
  return obj(result.record);
}

function approvedTemplate(record: Row): boolean {
  const documentType = text(record.document_type).toLowerCase();
  const status = text(record.status).toLowerCase();
  const legalStatus = text(record.legal_review_status).toLowerCase();
  const typeAllowed = documentType === "approved_legal_template" || documentType === "contract_template";
  const statusAllowed = status === "approved" || status === "active" || status === "owner_approved";
  const explicitlyApproved = record.approved_for_use === true && (record.legal_approved === true || legalStatus === "approved");
  return typeAllowed && statusAllowed && explicitlyApproved;
}

function templateScore(template: Row, factsDocument: Row): number {
  const facts = obj(factsDocument.facts);
  const templateState = text(template.state).toUpperCase();
  const factsState = text(facts.state).toUpperCase();
  const templateContractType = text(template.contract_type).toLowerCase();
  const requestedContractType = text(factsDocument.contract_type || facts.contract_type).toLowerCase();
  let score = 0;
  if (templateState && factsState && templateState === factsState) score += 4;
  if (!templateState) score += 1;
  if (templateContractType && requestedContractType && templateContractType === requestedContractType) score += 3;
  if (!templateContractType) score += 1;
  return score;
}

function selectTemplate(templates: Row[], factsDocument: Row): Row | undefined {
  return templates
    .map((template) => ({ template, score: templateScore(template, factsDocument) }))
    .sort((left, right) => right.score - left.score)[0]?.template;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-contract-document-coordinator",
      version: SERVICE_VERSION,
      status: "healthy",
      external_execution_enabled: false,
      legal_terms_generated: false,
      signing_enabled: false,
      approved_template_required: true,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large" });
  let body: Row = {};
  try {
    body = JSON.parse(raw || "{}") as Row;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const apply = body.apply !== false;
  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  try {
    const [documents, tasks] = await Promise.all([
      listEntity(url, key, "documents"),
      listEntity(url, key, "tasks"),
    ]);
    const templates = documents.filter(approvedTemplate);
    const existingTaskKeys = new Set(tasks.map((task) => text(task.external_id)).filter(Boolean));
    const candidates = documents.filter((document) =>
      text(document.document_type) === "contract_prep_facts" &&
      text(document.status) === "needs_approved_legal_template" &&
      text(document.contract_coordination_status) !== "package_ready"
    );
    const results: Row[] = [];

    for (const factsDocument of candidates) {
      const factsDocumentId = text(factsDocument.id);
      const dealId = text(links(factsDocument).deal_id || factsDocument.deal_id);
      const template = selectTemplate(templates, factsDocument);

      if (!template) {
        const blockerExternalId = `contract-template-blocker-${factsDocumentId}`;
        if (apply && !existingTaskKeys.has(blockerExternalId)) {
          await upsertEntity(url, key, "tasks", {
            source: "commandcore-contract-document-coordinator",
            external_id: blockerExternalId,
            task_type: "contract_legal_template_blocker",
            work_type: "prepare_contract",
            title: "Approved legal contract template required",
            status: "open",
            priority: "high",
            blocking_reason: "No explicitly approved legal contract template matches this contract preparation record.",
            legal_decision_required: true,
            owner_approval_required: false,
            external_action_started: false,
            links: { deal_id: dealId || null, document_id: factsDocumentId || null },
          });
          existingTaskKeys.add(blockerExternalId);
        }
        if (apply) {
          await upsertEntity(url, key, "documents", {
            ...factsDocument,
            contract_coordination_status: "blocked_missing_approved_legal_template",
            external_action_started: false,
          });
        }
        results.push({ document_id: factsDocumentId, deal_id: dealId, status: "blocked_missing_approved_legal_template" });
        continue;
      }

      const templateId = text(template.id);
      const packageExternalId = `contract-review-package-${factsDocumentId}-${templateId}`;
      const packageRecord: Row = {
        source: "commandcore-contract-document-coordinator",
        external_id: packageExternalId,
        name: "Contract assembly review package",
        document_type: "contract_assembly_review_package",
        status: "needs_owner_approval",
        facts: factsDocument.facts ?? {},
        contract_type: factsDocument.contract_type ?? null,
        approved_template_reference: {
          document_id: templateId || null,
          name: text(template.name) || null,
          version: text(template.version) || null,
          state: text(template.state) || null,
          contract_type: text(template.contract_type) || null,
          legal_review_status: text(template.legal_review_status) || null,
          approved_for_use: template.approved_for_use === true,
        },
        source_facts_document_id: factsDocumentId || null,
        legal_terms_generated: false,
        legal_terms_changed: false,
        document_assembled: false,
        signing_started: false,
        approval_required: true,
        external_action_started: false,
        links: { deal_id: dealId || null, source_document_id: factsDocumentId || null, legal_template_id: templateId || null },
      };

      if (!apply) {
        results.push({ document_id: factsDocumentId, deal_id: dealId, template_id: templateId, status: "would_create_owner_review_package" });
        continue;
      }

      const packageDocument = await upsertEntity(url, key, "documents", packageRecord);
      await upsertEntity(url, key, "documents", {
        ...factsDocument,
        contract_coordination_status: "package_ready",
        contract_review_package_id: text(packageDocument.id) || null,
        approved_legal_template_id: templateId || null,
        external_action_started: false,
      });
      results.push({
        document_id: factsDocumentId,
        deal_id: dealId,
        template_id: templateId,
        package_document_id: text(packageDocument.id),
        status: "owner_review_package_ready",
      });
    }

    return jsonResponse(200, {
      ok: true,
      apply,
      candidate_count: candidates.length,
      approved_template_count: templates.length,
      package_ready_count: results.filter((result) => result.status === "owner_review_package_ready").length,
      blocker_count: results.filter((result) => result.status === "blocked_missing_approved_legal_template").length,
      results,
      legal_terms_generated: false,
      legal_terms_changed: false,
      signing_started: false,
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore contract document coordinator failed", error);
    return jsonResponse(503, {
      ok: false,
      error: error instanceof Error ? error.message : "contract_document_coordinator_unavailable",
      legal_terms_generated: false,
      signing_started: false,
      external_action_started: false,
    });
  }
});
