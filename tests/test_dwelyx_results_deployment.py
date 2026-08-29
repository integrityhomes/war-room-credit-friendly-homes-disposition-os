from pathlib import Path

WORKFLOW = Path(".github/workflows/deploy-dwelyx-results.yml")
RECEIVER = Path("supabase/functions/dwelyx-results/index.ts")


def test_dwelyx_results_has_main_deployment_and_deno_validation() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "deno check supabase/functions/dwelyx-results/index.ts" in workflow
    assert "supabase functions deploy dwelyx-results" in workflow
    assert "branches:\n      - main" in workflow


def test_dwelyx_results_production_canary_is_no_write_and_fail_closed() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    receiver = RECEIVER.read_text(encoding="utf-8")

    assert "Signed Dwelyx headers are required" in receiver
    assert 'if (request.method !== "POST")' in receiver
    assert 'if [ "$STATUS" = "401" ]' in workflow
    assert "Signed Dwelyx headers are required" in workflow
    assert "No event was written" in workflow
    assert 'if [ "$STATUS" = "503" ]' in workflow
    assert "DWELYX_WEBHOOK_SECRET is not configured" in workflow
