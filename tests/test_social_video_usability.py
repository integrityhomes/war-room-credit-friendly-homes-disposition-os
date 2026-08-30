from pathlib import Path


def social_video_source() -> str:
    return Path("pages/26_Instagram_TikTok_YouTube_Shorts.py").read_text(encoding="utf-8")


def test_social_video_starts_with_business_workflow() -> None:
    source = social_video_source()

    for marker in (
        'st.title("Social Video")',
        'with st.expander("How Social Video stays safe and trackable", expanded=False):',
        'selected_label = st.selectbox("Property", list(property_options))',
        'with st.expander("Campaign tracking details", expanded=False):',
        'st.write("### Ready-to-post packages")',
        'st.write("### Review & publish")',
    ):
        assert marker in source


def test_social_video_empty_state_routes_to_setup() -> None:
    source = social_video_source()

    for marker in (
        '"Open Marketing Home"',
        'st.switch_page("pages/90_CFH_Marketing_Dispo.py")',
        '"Review Properties"',
        'st.switch_page("pages/01_Record_Manager.py")',
    ):
        assert marker in source


def test_social_video_keeps_publication_confirmation_gate() -> None:
    source = social_video_source()

    confirmed = source.index('confirmed = st.checkbox(')
    handoff = source.index('handoff_clicked = st.button(')
    dispatch = source.index('receipt = dispatch_social_publish_handoff(')
    assert confirmed < handoff < dispatch
    assert 'disabled=not publish_settings.configured or not confirmed' in source
