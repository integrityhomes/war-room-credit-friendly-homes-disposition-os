from pathlib import Path

APPROVED_AREAS = (
    "Home / Command Center",
    "Leads & CRM",
    "Deals",
    "Tasks & Follow-Up",
    "Marketing & Dispo",
    "Management",
)


def shell_source() -> str:
    return Path("pages/00_CommandCore.py").read_text(encoding="utf-8")


def test_commandcore_shell_has_only_the_six_approved_top_level_areas() -> None:
    source = shell_source()
    selector = source.split('with st.expander("Advanced tool directory"', 1)[1].split('if area == "Home / Command Center":', 1)[0]

    assert 'area = st.selectbox(' in selector
    for area in APPROVED_AREAS:
        assert f'"{area}"' in selector
    assert "Marketing Planning" not in selector
    assert "System & Setup" not in selector
    assert 'st.segmented_control(' not in selector


def test_planning_and_setup_tools_remain_reachable_inside_main_areas() -> None:
    source = shell_source()

    assert 'elif area == "Marketing & Dispo":' in source
    assert '"pages/28_Meta_Google_Paid_Traffic.py"' in source
    assert '"pages/33_ChatGPT_Ads_Channel_16.py"' in source
    assert 'elif area == "Management":' in source
    assert 'with st.expander("Administrator tools", expanded=False):' in source
    assert '"pages/50_CommandCore_Contract_Templates.py"' in source
    assert '"pages/43_CommandCore_CRM_Migration.py"' in source
    assert '"pages/32_Go_Live_Connection_Center.py"' in source
    assert '"pages/34_Safe_Full_Payload_Test.py"' not in source


def test_command_bot_is_part_of_home_workspace() -> None:
    source = shell_source()
    home_index = source.index('if area == "Home / Command Center":')
    bot_index = source.index('"pages/49_CommandCore_Command_Bot.py"')
    leads_index = source.index('elif area == "Leads & CRM":')

    assert home_index < bot_index < leads_index
