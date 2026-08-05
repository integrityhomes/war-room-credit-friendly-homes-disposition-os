import { createHmac } from "node:crypto";

type DwelyxEventType =
  | "buyer.registered"
  | "buyer.qualified"
  | "application.started"
  | "application.submitted"
  | "showing.requested"
  | "showing.scheduled"
  | "contract.pending"
  | "contract.signed"
  | "home.filled";

export type DwelyxAttributionEvent = {
  schema_version: "1.0";
  event_id: string;
  event_type: DwelyxEventType;
  occurred_at: string;
  dwelyx_buyer_id: string;
  dwelyx_property_id?: string;
  cfh_property_id?: string;
  source: string;
  medium: string;
  campaign: string;
  dwelyx_record_url?: string;
  test_mode: boolean;
};

export type DwelyxDeliveryResult = {
  accepted: boolean;
  duplicate: boolean;
  event_id: string;
};

function signedHeaders(body: string, eventId: string, secret: string): Record<string, string> {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const digest = createHmac("sha256", secret)
    .update(`${timestamp}.${body}`, "utf8")
    .digest("hex");
  return {
    "content-type": "application/json",
    "x-dwelyx-event-id": eventId,
    "x-dwelyx-timestamp": timestamp,
    "x-dwelyx-signature": `sha256=${digest}`,
  };
}

export async function sendDwelyxAttributionEvent(
  event: DwelyxAttributionEvent,
  options: {
    endpoint: string;
    secret: string;
    fetchImpl?: typeof fetch;
  },
): Promise<DwelyxDeliveryResult> {
  if (!options.endpoint.startsWith("https://")) {
    throw new Error("The Dwelyx results endpoint must use HTTPS");
  }
  if (!options.secret) {
    throw new Error("DWELYX_WEBHOOK_SECRET is required");
  }

  // JSON.stringify is called once. The same exact body is signed and sent.
  const body = JSON.stringify(event);
  const response = await (options.fetchImpl ?? fetch)(options.endpoint, {
    method: "POST",
    headers: signedHeaders(body, event.event_id, options.secret),
    body,
  });

  const result = (await response.json().catch(() => ({}))) as Partial<DwelyxDeliveryResult> & {
    error?: string;
  };
  if (!response.ok) {
    throw new Error(
      `Dwelyx attribution delivery failed with HTTP ${response.status}: ${result.error ?? "unknown error"}`,
    );
  }
  return {
    accepted: result.accepted === true,
    duplicate: result.duplicate === true,
    event_id: String(result.event_id ?? event.event_id),
  };
}

// Example server-side call. Never include buyer names, email addresses, phone
// numbers, application details, documents, income, credit data, or arbitrary metadata.
export async function reportApplicationSubmitted(input: {
  eventId: string;
  buyerId: string;
  dwelyxPropertyId: string;
  creditFriendlyHomesPropertyId: string;
  source: string;
  medium: string;
  campaign: string;
  buyerAdminUrl?: string;
}): Promise<DwelyxDeliveryResult> {
  const event: DwelyxAttributionEvent = {
    schema_version: "1.0",
    event_id: input.eventId,
    event_type: "application.submitted",
    occurred_at: new Date().toISOString(),
    dwelyx_buyer_id: input.buyerId,
    dwelyx_property_id: input.dwelyxPropertyId,
    cfh_property_id: input.creditFriendlyHomesPropertyId,
    source: input.source,
    medium: input.medium,
    campaign: input.campaign,
    dwelyx_record_url: input.buyerAdminUrl,
    test_mode: false,
  };

  return sendDwelyxAttributionEvent(event, {
    endpoint: process.env.DWELYX_RESULTS_ENDPOINT ?? "",
    secret: process.env.DWELYX_WEBHOOK_SECRET ?? "",
  });
}
