from pathlib import Path


def test_commandcore_shell_keeps_daily_work_and_marketing_tools_organized() -> None:
    source = Path("pages/00_CommandCore.py").read_text(encoding="utf-8")

    for marker in (
        'st.markdown("### Start work")',
        '"pages/35_CommandCore_My_Work.py"',
        '"pages/48_CommandCore_Owner_Approvals.py"',
        '"pages/45_CommandCore_Deal_Record.py"',
        '"pages/46_CommandCore_Pipeline_Followup.py"',
        'st.markdown("### Buyer lifecycle")',
        'st.markdown("### Marketing channels")',
        'st.markdown("### Optimize, recover & refresh")',
        'st.markdown("### Paid growth planning")',
        '"pages/13_AI_Buyer_Reactivation_Autopilot.py"',
        '"pages/15_AI_Buyer_Acquisition_Growth.py"',
        '"pages/16_AI_Buyer_Conversion_Command_Center.py"',
        '"pages/22_Showing_to_Contract_Conversion.py"',
        '"pages/14_AI_Creative_Winner_Rotation.py"',
        '"pages/20_Vacant_Home_Disposition_Escalation.py"',
        '"pages/18_Property_Shutdown_Buyer_Reroute.py"',
    ):
        assert marker in source


def test_paid_growth_section_stays_planning_only() -> None:
    source = Path("pages/00_CommandCore.py").read_text(encoding="utf-8")

    assert "Connecting ad accounts or spending money still requires owner authorization." in source
    assert "No campaign or spend starts here." in source


def test_management_keeps_maintenance_out_of_ordinary_work() -> None:
    source = Path("pages/00_CommandCore.py").read_text(encoding="utf-8")
    management = source.split('elif area == "Management":', 1)[1]
    daily, administrator = management.split(
        'with st.expander("Administrator tools", expanded=False):', 1
    )

    assert '"Priority Alerts"' in daily
    assert '"Workload History"' in daily
    assert '"Contract Templates"' not in daily
    assert '"Import Existing CRM Records"' not in daily
    assert '"Contract Templates"' in administrator
    assert '"Import Existing CRM Records"' in administrator
    assert '"Marketing Readiness"' in administrator
    assert '"Service Connections"' in administrator
    assert "Safe Payload Diagnostic" not in management
