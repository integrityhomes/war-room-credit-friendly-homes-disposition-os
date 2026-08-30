from pathlib import Path


def chatgpt_ads_source() -> str:
    return Path("pages/33_ChatGPT_Ads_Channel_16.py").read_text(encoding="utf-8")


def test_chatgpt_ads_is_presented_as_planning_only() -> None:
    source = chatgpt_ads_source()

    for marker in (
        'st.title("ChatGPT Ads Planning")',
        "This page cannot create an ad account or campaign and cannot spend money",
        'st.write("### Plan the audience")',
        'with st.expander("Tracking & destination details", expanded=False):',
        'st.write("### Ad plan")',
        'with st.expander("Tracking link & launch requirements", expanded=False):',
    ):
        assert marker in source

    assert '"spend_authorized": "NO"' in source
    assert '"launch_authorized": "NO"' in source
    assert '"ads_manager_action_started": "NO"' in source


def test_chatgpt_ads_removes_internal_channel_number_from_ui() -> None:
    source = chatgpt_ads_source()

    assert 'st.title("Channel 16 — ChatGPT Ads")' not in source
    assert 'page_title="ChatGPT Ads Channel 16"' not in source
