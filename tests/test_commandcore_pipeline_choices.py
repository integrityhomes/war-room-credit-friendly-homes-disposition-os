from pathlib import Path


def test_pipeline_stage_and_status_use_controlled_choices() -> None:
    source = Path("pages/46_CommandCore_Pipeline_Followup.py").read_text(encoding="utf-8")

    for marker in (
        'PIPELINE_STAGES = [',
        'DEAL_STATUSES = ["Active", "On Hold", "Closed", "Dead"]',
        'new_stage = c1.selectbox(',
        'new_status = c2.selectbox(',
        'choice_options(current_stage, PIPELINE_STAGES)',
        'choice_options(current_status, DEAL_STATUSES)',
        'Existing legacy values remain available until you change them.',
    ):
        assert marker in source

    assert 'c1.text_input("Stage"' not in source
    assert 'c2.text_input("Status"' not in source


def test_pipeline_choices_match_guided_lead_intake() -> None:
    pipeline = Path("pages/46_CommandCore_Pipeline_Followup.py").read_text(encoding="utf-8")
    crm = Path("pages/44_CommandCore_CRM.py").read_text(encoding="utf-8")

    expected_stages = (
        "New Lead",
        "Contacted",
        "Follow-Up",
        "Analyzing",
        "Offer Pending",
        "Offer Made",
        "Under Contract",
        "Title / Closing",
        "Marketing / Dispo",
        "Closed",
        "Dead / Not Moving Forward",
    )
    for stage in expected_stages:
        assert f'"{stage}"' in pipeline
        assert f'"{stage}"' in crm

    for status in ("Active", "On Hold", "Closed", "Dead"):
        assert f'"{status}"' in pipeline
        assert f'"{status}"' in crm
