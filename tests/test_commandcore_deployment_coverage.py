from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

REQUIRED_SERVICES = (
    "commandcore-crm-core",
    "commandcore-inbound-lead-capture",
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
)


def test_required_commandcore_services_have_main_deployment_paths() -> None:
    workflow_sources = {
        path: path.read_text(encoding="utf-8")
        for path in sorted(WORKFLOWS.glob("*.yml"))
    }

    missing = []
    for service in REQUIRED_SERVICES:
        deploy_command = f"supabase functions deploy {service}"
        function_path = f"supabase/functions/{service}/**"
        covered = any(
            deploy_command in source
            and function_path in source
            and "main" in source
            for source in workflow_sources.values()
        )
        if not covered:
            missing.append(service)

    assert not missing, "Missing main deployment coverage: " + ", ".join(missing)
