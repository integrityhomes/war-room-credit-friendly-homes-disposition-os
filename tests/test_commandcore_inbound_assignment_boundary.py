from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "supabase/functions/commandcore-inbound-lead-capture/index.ts"
WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-inbound-lead-capture.yml"


def test_external_inbound_token_cannot_override_assignment() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'type AuthMode = "none" | "inbound_token" | "service_role"' in source
    assert 'if (service && constantTimeEqual(supplied, service)) return "service_role";' in source
    assert 'if (inbound && constantTimeEqual(supplied, inbound)) return "inbound_token";' in source
    assert 'const explicitOwner = callerAuth === "service_role" ? requestedOwner : "";' in source
    assert 'const assignmentOverrideIgnored = Boolean(requestedOwner && callerAuth !== "service_role");' in source
    assert "external_assignment_override_allowed: false" in source
    assert "internal_assignment_override_requires_service_role: true" in source


def test_inbound_capture_still_fails_closed_before_processing() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'if (callerAuth === "none") return jsonResponse(401, { ok: false, error: "unauthorized" });' in source
    auth_position = source.index('if (callerAuth === "none")')
    parse_position = source.index("const raw = await req.text()")
    crm_position = source.index("const supabaseUrl =")
    assert auth_position < parse_position < crm_position


def test_inbound_deploy_validates_and_probes_unauthorized_boundary() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "deno check supabase/functions/commandcore-inbound-lead-capture/index.ts" in workflow
    assert "external_assignment_override_allowed" in workflow
    assert "internal_assignment_override_requires_service_role" in workflow
    assert "Verify unauthenticated lead cannot write" in workflow
    assert 'test "$STATUS" = "401"' in workflow
    assert 'assert data.get("error") == "unauthorized"' in workflow
