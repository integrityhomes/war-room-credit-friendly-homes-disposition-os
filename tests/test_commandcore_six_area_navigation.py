from pathlib import Path


def test_commandcore_navigation_uses_only_the_six_approved_areas() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    for area in (
        '"Home / Command Center"',
        '"Leads & CRM"',
        '"Deals"',
        '"Tasks & Follow-Up"',
        '"Marketing & Dispo"',
        '"Management"',
    ):
        assert area in source

    assert '"Marketing Planning"' not in source
    assert '"System & Setup"' not in source


def test_follow_up_paid_planning_and_setup_are_folded_into_the_right_areas() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    tasks_start = source.index('"Tasks & Follow-Up"')
    marketing_start = source.index('"Marketing & Dispo"')
    management_start = source.index('"Management"')

    tasks_block = source[tasks_start:marketing_start]
    marketing_block = source[marketing_start:management_start]
    management_block = source[management_start:]

    assert 'pages/35_CommandCore_My_Work.py' in tasks_block
    assert 'pages/46_CommandCore_Pipeline_Followup.py' in tasks_block
    assert 'pages/36_CommandCore_Coverage.py' in tasks_block

    assert 'pages/28_Meta_Google_Paid_Traffic.py' in marketing_block
    assert 'pages/33_ChatGPT_Ads_Channel_16.py' in marketing_block

    assert 'pages/43_CommandCore_CRM_Migration.py' in management_block
    assert 'pages/32_Go_Live_Connection_Center.py' in management_block
    assert 'pages/34_Safe_Full_Payload_Test.py' in management_block
