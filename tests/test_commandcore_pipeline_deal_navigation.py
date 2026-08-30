from pathlib import Path


def test_pipeline_cards_open_exact_unified_deal_record() -> None:
    source = Path("pages/46_CommandCore_Pipeline_Followup.py").read_text(encoding="utf-8")

    assert "def open_deal_button" in source
    assert "def show_followup_task" in source
    assert 'st.session_state["commandcore_selected_deal_id"] = deal_id' in source
    assert 'st.switch_page("pages/45_CommandCore_Deal_Record.py")' in source
    assert 'key=f"pipeline_open_{deal_id}"' in source
    assert 'key=f"{key_prefix}_{task_key}"' in source
    assert 'key_prefix="followup_attention"' in source
    assert 'key_prefix="followup_upcoming"' in source
