from pathlib import Path

PAGE = Path("pages/51_CommandCore_Communications.py")


def source() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_hub_reuses_canonical_communications_and_nevaeh() -> None:
    value = source()

    assert 'list_records("communications")' in value
    assert "build_nevaeh_inbox(" in value
    assert '"action": "list"' in value
    assert "create_client" in value
    assert "storage.from_" not in value


def test_hub_has_all_simple_views_and_advanced_details() -> None:
    value = source()

    for label in (
        "New",
        "Needs attention",
        "Assigned to me",
        "Seller",
        "Buyer",
        "Deal-related",
        "STOP / Consent",
        "Money / Legal",
        "Unmatched",
    ):
        assert f'"{label}"' in value
    assert 'with st.expander("Advanced details", expanded=False):' in value


def test_hub_is_read_only_and_has_no_provider_or_consent_actions() -> None:
    value = source().casefold()
    list_helper = value[value.index("def list_records"):value.index("def category_count")]

    for forbidden in (
        '"action": "upsert"',
        '"action": "record_consent"',
        "send_sms",
        "send_email",
        "make_call",
        "dispatch_",
        "webhook",
        "xleads",
    ):
        assert forbidden not in list_helper
    assert '"action": "list"' in list_helper
    assert "st.button(\"send" not in value


def test_hub_response_normalization_accepts_bytes_and_fails_closed() -> None:
    value = source()

    assert "isinstance(value, (bytes, bytearray))" in value
    assert 'bytes(value).decode("utf-8")' in value
    assert "json.loads" in value
    assert "except (UnicodeDecodeError, json.JSONDecodeError):" in value
    assert "return value if isinstance(value, dict) else {}" in value


def test_navigation_registers_one_canonical_communications_page() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    registry = Path("src/cfh_disposition/app_completion.py").read_text(encoding="utf-8")

    assert app.count('NavigationItem("pages/51_CommandCore_Communications.py", "Communications")') == 1
    assert app.count('st.Page("pages/51_CommandCore_Communications.py", title="Communications"') == 1
    assert registry.count('"pages/51_CommandCore_Communications.py"') == 1
