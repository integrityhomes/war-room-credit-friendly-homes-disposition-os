from pathlib import Path


def test_sidebar_uses_only_the_six_approved_commandcore_areas() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    for area in (
        '"Home / Command Center": [',
        '"Leads & CRM": [',
        '"Deals": [',
        '"Tasks & Follow-Up": [',
        '"Marketing & Dispo": [',
        '"Management": [',
    ):
        assert area in source

    assert '"Marketing Planning": [' not in source
    assert '"System & Setup": [' not in source


def test_sidebar_keeps_tools_under_their_commandcore_area() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert '"pages/46_CommandCore_Pipeline_Followup.py"' in source
    assert '"pages/48_CommandCore_Owner_Approvals.py"' in source
    assert '"pages/28_Meta_Google_Paid_Traffic.py"' in source
    assert '"pages/43_CommandCore_CRM_Migration.py"' in source
