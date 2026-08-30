from pathlib import Path


HELPER = Path("supabase/functions/_shared/commandcore_journey_readiness.ts")
ENDPOINT = Path("supabase/functions/commandcore-launch-readiness/index.ts")


def test_launch_readiness_covers_core_business_journeys() -> None:
    source = HELPER.read_text(encoding="utf-8")
    for journey in (
        "Lead Intake & CRM",
        "Follow-Up & Pipeline",
        "Owner Approval",
        "Deal Lifecycle & Contract",
        "Closing & Disposition",
        "Communication & Execution",
        "Management & Safe Rebalancing",
    ):
        assert f'journey: "{journey}"' in source


def test_journey_readiness_is_derived_from_existing_service_health() -> None:
    source = HELPER.read_text(encoding="utf-8")

    assert "row.healthy === true" in source
    assert "failed.length === 0" in source
    assert "commandcore-crm-core" in source
    assert "commandcore-deal-completion" in source
    assert "commandcore-dispatch-worker" in source


def test_launch_endpoint_reports_journey_summary_without_changing_cutover_gate() -> None:
    source = ENDPOINT.read_text(encoding="utf-8")

    assert 'core_journey_assessment_included: true' in source
    assert "const journeys = buildJourneyReadiness(checks);" in source
    assert "healthy_core_journey_count" in source
    assert "failed_core_journeys" in source
    assert "crm_cutover: crmCutover" in source
    assert "external_action_started: false" in source
    assert "owner_approval_bypassed: false" in source
