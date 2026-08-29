from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages/39_CommandCore_Operations_Hub.py"


def test_operations_hub_separates_operational_and_crm_cutover_readiness() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert 'r1.metric("Critical Chain", "READY" if launch_ready else "NOT READY")' in source
    assert 'r4.metric("CRM Cutover", "READY" if crm_cutover_ready else "NOT READY")' in source
    assert 'cutover = readiness.get("crm_cutover")' in source
    assert 'unsupported_migration_entities' in source
    assert 'source_crm_data_reconciliation_verified' in source
    assert 'Do not discontinue the outside CRM yet.' in source


def test_operations_hub_cutover_panel_remains_read_only() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert 'CRM Replacement / Cutover' in source
    assert 'CRM cutover blockers' in source
    assert 'apply' not in source.lower() or 'apply approved' not in source.lower()
    assert 'delete' not in source.lower() or 'delete crm' not in source.lower()
