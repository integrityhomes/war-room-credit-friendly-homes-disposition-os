from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "supabase" / "functions"

# The external inbound-capture boundary is intentionally excluded here because
# it has its own channel/integration authentication contract. These services
# are internal CommandCore functions and must require the Supabase service-role
# credential before accepting POST/internal work.
INTERNAL_SERVICES = (
    "commandcore-crm-core",
    "commandcore-owner-routing",
    "commandcore-action-queue",
    "commandcore-crm-followup-sync",
    "commandcore-followup-intelligence",
    "commandcore-stage-intelligence",
    "commandcore-owner-approval-release",
    "commandcore-approval-engine",
    "commandcore-deal-lifecycle-coordinator",
    "commandcore-deal-lifecycle-readiness",
    "commandcore-deal-specialist-prep",
    "commandcore-contract-document-coordinator",
    "commandcore-executed-contract-handoff",
    "commandcore-closing-dispo-handoff",
    "commandcore-deal-completion",
    "commandcore-adapter-registry",
    "commandcore-contact-ledger",
    "commandcore-outbound-prep",
    "commandcore-communication-gate",
    "commandcore-execution-readiness",
    "commandcore-dispatch-worker",
    "commandcore-deal-flow-orchestrator",
    "commandcore-workload-balance-advisor",
    "commandcore-safe-rebalance-apply",
    "commandcore-auto-rebalance",
)


def test_internal_commandcore_services_require_service_role_authentication() -> None:
    missing: list[str] = []
    for service in INTERNAL_SERVICES:
        path = FUNCTIONS / service / "index.ts"
        assert path.exists(), f"Missing internal service source: {service}"
        source = path.read_text(encoding="utf-8")
        normalized = source.lower()
        has_service_role = "supabase_service_role_key" in normalized
        has_authorization = "authorization" in normalized
        has_unauthorized_failure = "unauthorized" in normalized and "401" in normalized
        if not (has_service_role and has_authorization and has_unauthorized_failure):
            missing.append(service)

    assert not missing, (
        "Internal CommandCore services missing the required service-role auth contract: "
        + ", ".join(missing)
    )
