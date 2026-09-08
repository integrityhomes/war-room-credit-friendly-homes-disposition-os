from cfh_disposition.corepilot_sources import (
    COREPILOT_READ_SOURCES,
    CRM_CORE_ENTITIES,
    validated_crm_entities,
)
from cfh_disposition.corepilot_tools import COREPILOT_TOOLS, CorePilotActionClass


def test_every_read_tool_has_a_valid_existing_source() -> None:
    read_keys = {tool.key for tool in COREPILOT_TOOLS if tool.action_class is CorePilotActionClass.READ}
    assert set(COREPILOT_READ_SOURCES) == read_keys
    assert all(set(entities) <= CRM_CORE_ENTITIES for entities in COREPILOT_READ_SOURCES.values())


def test_unsupported_approvals_entity_is_never_sent_to_crm_core() -> None:
    entities = validated_crm_entities()
    assert "approvals" not in entities
    assert set(entities) == CRM_CORE_ENTITIES
    assert COREPILOT_READ_SOURCES["read_approvals"] == ("offers", "documents")
