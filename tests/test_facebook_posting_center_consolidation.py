from pathlib import Path


def source() -> str:
    return Path("pages/7_Facebook_Group_Posting_Center.py").read_text(encoding="utf-8")


def test_facebook_support_tools_live_under_posting_center() -> None:
    page = source()

    assert page.index("render_facebook_group_posting_center(") < page.index(
        'with st.expander("Facebook setup & supporting tools", expanded=False):'
    )
    for marker in (
        '"pages/8_Facebook_Group_Bulk_Import.py"',
        'label="Add / Import Groups"',
        '"pages/9_Facebook_Group_Variation_Pack.py"',
        'label="Create Variation Pack"',
        '"pages/10_Facebook_Daily_Assignments.py"',
        'label="Daily Assignments"',
    ):
        assert marker in page
