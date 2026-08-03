from cfh_disposition.security import scan_text_for_secrets


def test_openai_style_key_is_detected() -> None:
    findings = scan_text_for_secrets("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456")
    assert findings


def test_safe_placeholder_is_not_detected() -> None:
    assert not scan_text_for_secrets("OPENAI_API_KEY=")
