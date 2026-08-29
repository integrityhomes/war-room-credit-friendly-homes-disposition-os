from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/commandcore-auto-rebalance.yml"


def test_auto_rebalance_workflow_keeps_inline_python_yaml_safe() -> None:
    source = WORKFLOW.read_text()
    assert "python -c 'import json, sys;" in source
    assert "\nimport json, sys\n" not in source
    assert 'cron: "17 * * * *"' in source
    assert "commandcore-auto-rebalance" in source
