from pathlib import Path


def paid_ads_source() -> str:
    return Path("pages/28_Meta_Google_Paid_Traffic.py").read_text(encoding="utf-8")


def test_paid_ads_planning_keeps_spend_outside_page() -> None:
    source = paid_ads_source()

    for marker in (
        'st.title("Paid Ads Planning")',
        "This page cannot create or activate ads and cannot spend money",
        'with st.expander("Campaign tracking details", expanded=False):',
        'st.write("### Proposed budget")',
        'with st.expander("Ad account connection status", expanded=False):',
        'with st.expander("Tracking link & launch requirements", expanded=False):',
    ):
        assert marker in source

    assert '"spend_authorized": "NO"' in source
    assert '"launch_authorized": "NO"' in source
    assert "owner approval workflow records a separate approval" in source


def test_paid_ads_empty_state_routes_to_property_setup() -> None:
    source = paid_ads_source()

    for marker in (
        '"Open Marketing Home"',
        'st.switch_page("pages/90_CFH_Marketing_Dispo.py")',
        '"Review Properties"',
        'st.switch_page("pages/01_Record_Manager.py")',
    ):
        assert marker in source
