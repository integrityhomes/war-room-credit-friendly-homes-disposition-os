from cfh_disposition.corepilot_tools import (
    COREPILOT_TOOLS,
    CorePilotActionClass,
)


def test_registry_has_unique_real_capabilities_and_complete_safety_metadata() -> None:
    assert len(COREPILOT_TOOLS) >= 30
    assert len({tool.key for tool in COREPILOT_TOOLS}) == len(COREPILOT_TOOLS)
    assert {tool.action_class for tool in COREPILOT_TOOLS} == {
        CorePilotActionClass.READ,
        CorePilotActionClass.PREPARE,
        CorePilotActionClass.APPROVAL_REQUIRED,
    }
    for tool in COREPILOT_TOOLS:
        assert tool.display_name
        assert tool.description
        assert tool.entity_types
        assert tool.safe_failure_behavior
        assert tool.source_engine


def test_read_and_prepare_tools_cannot_mutate_or_act_externally() -> None:
    automatic = [tool for tool in COREPILOT_TOOLS if tool.action_class is not CorePilotActionClass.APPROVAL_REQUIRED]
    assert automatic
    assert all(tool.mutates_commandcore is False for tool in automatic)
    assert all(tool.performs_external_action is False for tool in automatic)
