from pathlib import Path


def shell_source() -> str:
    return Path("pages/00_CommandCore.py").read_text(encoding="utf-8")


def test_marketing_workspace_starts_with_marketing_command() -> None:
    source = shell_source()
    marketing = source.split('elif area == "Marketing & Dispo":', 1)[1].split('elif area == "Management":', 1)[0]

    assert 'st.markdown("### Start here")' in marketing
    assert marketing.index('"pages/90_CFH_Marketing_Dispo.py"') < marketing.index('"pages/29_Email_SMS_Reactivation.py"')
    assert "connection required" in marketing.lower()
    assert "spend approval" in marketing.lower()


def test_management_workspace_starts_with_operations_hub() -> None:
    source = shell_source()
    management = source.split('elif area == "Management":', 1)[1]

    assert 'st.markdown("### Start here")' in management
    assert management.index('"pages/39_CommandCore_Operations_Hub.py"') < management.index('"pages/40_CommandCore_Team_Health.py"')
    assert 'st.markdown("### People & workload")' in management
    assert 'st.markdown("### Exceptions & audit")' in management
    assert 'st.markdown("### System & setup")' in management
