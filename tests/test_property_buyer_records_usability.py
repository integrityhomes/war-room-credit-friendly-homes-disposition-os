from pathlib import Path


def test_property_buyer_records_use_business_language() -> None:
    page = Path("pages/01_Record_Manager.py").read_text(encoding="utf-8")
    renderer = Path("src/cfh_disposition/record_manager_safe.py").read_text(encoding="utf-8")
    app = Path("app.py").read_text(encoding="utf-8")

    for marker in (
        'st.title("Property & Buyer Records")',
        'title="Properties & Buyers"',
        'st.subheader("Review and update saved records")',
        'st.write("#### Property details")',
        'st.write("#### Add buyer")',
    ):
        assert marker in page + renderer + app

    assert "Edit, Add Photos, or Delete Saved Records" not in renderer
    assert 'st.title("Record Manager")' not in page


def test_empty_property_records_have_safe_next_actions() -> None:
    renderer = Path("src/cfh_disposition/record_manager_safe.py").read_text(encoding="utf-8")

    for marker in (
        'st.info("No property records are saved here yet.")',
        '"Open Marketing Home"',
        'st.switch_page("pages/90_CFH_Marketing_Dispo.py")',
        '"Open Deal Workspace"',
        'st.switch_page("pages/45_CommandCore_Deal_Record.py")',
    ):
        assert marker in renderer
