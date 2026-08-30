EXPECTED_ENTITIES = {
    "contacts",
    "properties",
    "deals",
    "activities",
    "communications",
    "tasks",
    "offers",
    "documents",
    "transactions",
}


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def quoted_values(block: str) -> set[str]:
    values: set[str] = set()
    for part in block.split('"')[1::2]:
        value = part.strip()
        if value and all(character.islower() or character == "_" for character in value):
            values.add(value)
    return values


def staging_entities() -> set[str]:
    source = read_text("supabase/functions/commandcore-crm-import-staging/index.ts")
    values: set[str] = set()
    for line in source.splitlines():
        if 'entity: "' not in line:
            continue
        values |= quoted_values(line)
    return values


def reconciliation_entities() -> set[str]:
    source = read_text("supabase/functions/commandcore-crm-reconciliation/index.ts")
    block = source.split("const ENTITY_TYPES = [", 1)[1].split("] as const", 1)[0]
    return quoted_values(block)


def launch_readiness_entities() -> set[str]:
    source = read_text("supabase/functions/commandcore-launch-readiness/index.ts")
    block = source.split("const SYSTEM_OF_RECORD_ENTITIES = [", 1)[1].split("] as const", 1)[0]
    return quoted_values(block)


def test_all_cutover_services_cover_the_same_system_of_record_entities() -> None:
    assert staging_entities() == EXPECTED_ENTITIES
    assert reconciliation_entities() == EXPECTED_ENTITIES
    assert launch_readiness_entities() == EXPECTED_ENTITIES


def test_cutover_contract_includes_deal_history_and_financial_workflow_records() -> None:
    required = {"activities", "communications", "tasks", "offers", "documents", "transactions"}
    assert required <= EXPECTED_ENTITIES
