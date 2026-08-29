from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS_HUB = ROOT / "pages/39_CommandCore_Operations_Hub.py"


def test_operations_hub_surfaces_existing_launch_readiness_auditor() -> None:
    source = OPERATIONS_HUB.read_text()
    assert 'commandcore-launch-readiness' in source
    assert 'CommandCore System Readiness' in source
    assert 'Critical Chain' in source
    assert 'Failed Required' in source
    assert 'failed_required_services' in source


def test_operations_hub_readiness_remains_visibility_only() -> None:
    source = OPERATIONS_HUB.read_text()
    assert 'Read-only management visibility' in source
    assert 'data=b"{}"' in source
    assert 'method="POST"' in source
    assert 'launch_ready' in source
