HELPER = "supabase/functions/_shared/commandcore_journey_readiness.ts"
ENDPOINT = "supabase/functions/commandcore-launch-readiness/index.ts"


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_launch_readiness_covers_core_business_journeys() -> None:
    source = read_text(HELPER)
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
    source = read_text(HELPER)

    assert "row.healthy === true" in source
    assert "failed.length === 0" in source
    assert "commandcore-crm-core" in source
    assert "commandcore-deal-completion" in source
    assert "commandcore-dispatch-worker" in source


def test_launch_endpoint_reports_journey_summary_without_changing_cutover_gate() -> None:
    source = read_text(ENDPOINT)

    assert 'core_journey_assessment_included: true' in source
    assert "const journeys = buildJourneyReadiness(checks);" in source
    assert "healthy_core_journey_count" in source
    assert "failed_core_journeys" in source
    assert "crm_cutover: crmCutover" in source
    assert "external_action_started: false" in source
    assert "owner_approval_bypassed: false" in source
