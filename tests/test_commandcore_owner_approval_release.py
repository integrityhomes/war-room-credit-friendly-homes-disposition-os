from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "supabase/functions/commandcore-owner-approval-release/index.ts"
WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-owner-approval-release.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_owner_approval_release_skips_already_released_items():
    source = _read(SERVICE)
    assert 'text(offer.approval_release_status) === "released_to_internal_contract_prep"' in source
    assert 'text(document.approval_release_status) === "released_to_internal_next_step"' in source
    assert "alreadyReleasedSkippedCount += 1" in source
    assert "already_released_skipped_count: alreadyReleasedSkippedCount" in source


def test_owner_approval_release_preserves_timestamp_and_task_identity():
    source = _read(SERVICE)
    assert "const releasedAt = text(offer.approval_released_at) || new Date().toISOString();" in source
    assert "const releasedAt = text(document.approval_released_at) || new Date().toISOString();" in source
    assert "approval_release_task_external_id: externalId" in source
    assert "idempotent_release_enabled: true" in source
    assert "stable_release_timestamp_enabled: true" in source


def test_owner_approval_release_deploy_contract_is_validated():
    workflow = _read(WORKFLOW)
    assert "pull_request:" in workflow
    assert "deno check supabase/functions/commandcore-owner-approval-release/index.ts" in workflow
    assert 'data.get("version") == "2026-08-29.2"' in workflow
    assert 'data.get("idempotent_release_enabled") is True' in workflow
    assert 'data.get("stable_release_timestamp_enabled") is True' in workflow
    assert 'data.get("external_execution_enabled") is False' in workflow
