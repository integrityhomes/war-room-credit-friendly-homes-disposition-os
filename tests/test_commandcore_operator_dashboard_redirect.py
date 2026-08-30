from pathlib import Path


def test_legacy_operator_dashboard_redirects_to_my_work() -> None:
    source = Path("pages/21_CommandCore_Operator_Dashboard.py").read_text(encoding="utf-8")

    assert 'st.switch_page("pages/35_CommandCore_My_Work.py")' in source
    assert "ACTION_BUCKET" not in source
    assert "OPERATOR_STATE_BUCKET" not in source
