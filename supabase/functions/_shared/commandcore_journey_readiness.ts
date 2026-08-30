type HealthRow = Record<string, unknown>;

export type JourneyReadiness = {
  journey: string;
  healthy: boolean;
  required_services: string[];
  failed_services: string[];
};

const CORE_JOURNEYS: Array<{ journey: string; services: string[] }> = [
  {
    journey: "Lead Intake & CRM",
    services: [
      "commandcore-crm-core",
      "commandcore-inbound-lead-capture",
      "commandcore-owner-routing",
    ],
  },
  {
    journey: "Follow-Up & Pipeline",
    services: [
      "commandcore-action-queue",
      "commandcore-crm-followup-sync",
      "commandcore-followup-intelligence",
      "commandcore-stage-intelligence",
    ],
  },
  {
    journey: "Owner Approval",
    services: [
      "commandcore-owner-approval-release",
      "commandcore-approval-engine",
    ],
  },
  {
    journey: "Deal Lifecycle & Contract",
    services: [
      "commandcore-deal-lifecycle-coordinator",
      "commandcore-deal-lifecycle-readiness",
      "commandcore-deal-specialist-prep",
      "commandcore-contract-document-coordinator",
      "commandcore-executed-contract-handoff",
    ],
  },
  {
    journey: "Closing & Disposition",
    services: [
      "commandcore-closing-dispo-handoff",
      "commandcore-deal-completion",
    ],
  },
  {
    journey: "Communication & Execution",
    services: [
      "commandcore-adapter-registry",
      "commandcore-contact-ledger",
      "commandcore-outbound-prep",
      "commandcore-communication-gate",
      "commandcore-execution-readiness",
      "commandcore-dispatch-worker",
      "commandcore-deal-flow-orchestrator",
    ],
  },
  {
    journey: "Management & Safe Rebalancing",
    services: [
      "commandcore-workload-balance-advisor",
      "commandcore-safe-rebalance-apply",
      "commandcore-auto-rebalance",
    ],
  },
];

export function buildJourneyReadiness(checks: HealthRow[]): JourneyReadiness[] {
  const byService = new Map(
    checks.map((row) => [String(row.service || ""), row.healthy === true]),
  );
  return CORE_JOURNEYS.map((definition) => {
    const failed = definition.services.filter((service) => byService.get(service) !== true);
    return {
      journey: definition.journey,
      healthy: failed.length === 0,
      required_services: [...definition.services],
      failed_services: failed,
    };
  });
}
