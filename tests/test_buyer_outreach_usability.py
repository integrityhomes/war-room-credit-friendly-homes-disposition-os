from pathlib import Path


def buyer_outreach_source() -> str:
    return Path("pages/29_Email_SMS_Reactivation.py").read_text(encoding="utf-8")


def test_buyer_outreach_starts_with_simple_daily_flow() -> None:
    source = buyer_outreach_source()

    for marker in (
        'st.title("Buyer Outreach")',
        'with st.expander("How outreach stays safe and trackable", expanded=False):',
        'selected = options[st.selectbox("Property", list(options))]',
        'with st.expander("Campaign tracking details", expanded=False):',
        'st.write("### Prepared message")',
        'with st.expander("Tracking & sending guardrails", expanded=False):',
    ):
        assert marker in source


def test_buyer_outreach_keeps_consent_and_sender_gates() -> None:
    source = buyer_outreach_source()

    assert "buyer.email_consent and not buyer.do_not_contact" in source
    assert "buyer.sms_consent and not buyer.do_not_contact" in source
    assert "disabled=not email_settings.configured or not email_confirmed" in source
    assert "disabled=not sms_settings.configured or not confirmed" in source
    assert "dispatch_email_handoff(" in source
    assert "dispatch_sms_handoff(" in source
    assert "does not claim inbox delivery" in source
    assert "does not claim carrier delivery" in source


def test_buyer_outreach_empty_state_routes_to_setup() -> None:
    source = buyer_outreach_source()

    for marker in (
        '"Open Marketing Home"',
        'st.switch_page("pages/90_CFH_Marketing_Dispo.py")',
        '"Review Properties & Buyers"',
        'st.switch_page("pages/01_Record_Manager.py")',
    ):
        assert marker in source
