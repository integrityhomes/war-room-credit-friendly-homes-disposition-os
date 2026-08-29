from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/commandcore-auto-rebalance.yml"
DEPLOY_WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-auto-rebalance.yml"
FUNCTION = ROOT / "supabase/functions/commandcore-auto-rebalance/index.ts"


def test_auto_rebalance_workflow_keeps_inline_python_yaml_safe() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "python - <<'PY'" in source
    assert "\nimport json\n" not in source
    assert "\nimport os\n" not in source
    assert 'cron: "17 * * * *"' in source
    assert "commandcore-auto-rebalance" in source


def test_auto_rebalance_keeps_hourly_schedule_and_safe_push_verification() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "push:" in source
    assert "branches: [main]" in source
    assert 'if [ "$GITHUB_EVENT_NAME" = "push" ]; then' in source
    assert 'APPLY="false"' in source
    assert '--data "{\\"apply\\":${APPLY}}"' in source


def test_auto_rebalance_dry_run_cannot_apply_assignments() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert 'assert result.get("apply_requested") is expected' in source
    assert 'assert result.get("assignment_only") is True' in source
    assert 'assert result.get("readiness_changed") is False' in source
    assert 'assert result.get("approval_changed") is False' in source
    assert 'assert result.get("consent_changed") is False' in source
    assert 'assert result.get("external_action_started") is False' in source
    assert "if not expected:" in source
    assert 'assert result.get("applied_count") == 0' in source


def test_auto_rebalance_empty_queue_is_successful_noop() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert "function noWorkResponse(apply: boolean)" in source
    assert 'if (!openItems.length) return jsonResponse(200, noWorkResponse(apply));' in source
    assert 'no_work: true' in source
    assert 'applied_count: 0' in source
    assert 'external_action_started: false' in source


def test_auto_rebalance_deploys_required_dependencies() -> None:
    source = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    for service in (
        "commandcore-workload-balance-advisor",
        "commandcore-safe-rebalance-apply",
        "commandcore-auto-rebalance",
    ):
        assert f"supabase functions deploy {service}" in source
        assert f"check_health {service}" in source
    assert "SUPABASE_URL" not in source
    assert '--data \'{"apply":false}\'' in source
    assert 'assert result.get("applied_count") == 0' in source
