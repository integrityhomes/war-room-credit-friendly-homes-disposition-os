from __future__ import annotations

from types import SimpleNamespace

from cfh_disposition import contract_build_service as service


def _prep(*, missing: list[str] | None = None) -> dict:
    return {
        "document_type": "contract_prep_facts",
        "contract_type": "Illinois CFD",
        "status": "ready",
        "version": 1,
        "missing_facts": missing or [],
        "facts": {"state": "IL", "purchase_price": 50000},
        "links": {"deal_id": "deal-1"},
    }


def test_build_contract_generates_once_and_saves_history(monkeypatch) -> None:
    prepared = _prep()
    saved_prep = {**prepared, "id": "prep-1"}
    template = {
        "id": "template-1",
        "document_type": "contract_template",
        "contract_type": "Illinois CFD",
        "state": "IL",
        "version": 4,
        "status": "approved",
        "approved_for_use": True,
        "legal_approved": True,
        "storage_object_path": "templates/il/v4.docx",
    }
    refreshed = [saved_prep, template]
    saved: list[tuple[str, dict]] = []

    monkeypatch.setattr(service, "contract_prep_document", lambda **kwargs: dict(prepared))
    monkeypatch.setattr(service, "is_illinois_cfd", lambda value: True)
    monkeypatch.setattr(service, "select_exact_approved_template", lambda *args, **kwargs: template)
    monkeypatch.setattr(
        service,
        "generate_and_store_contract",
        lambda **kwargs: SimpleNamespace(
            document_record={
                "document_type": "generated_contract",
                "contract_type": "Illinois CFD",
                "storage_object_path": "deals/deal-1/generated_contract/v1/contract.docx",
                "generation_provenance": {},
                "links": {"deal_id": "deal-1"},
            },
            activity_record={"activity_type": "contract_generated"},
            template_id="template-1",
            insurance_version="Insurance Included",
        ),
    )

    def save_related(entity: str, deal_id: str, record: dict) -> bool:
        assert deal_id == "deal-1"
        saved.append((entity, record))
        return True

    outcome = service.build_contract_for_deal(
        client=object(),
        deal={"contract_type": "Illinois CFD"},
        deal_id="deal-1",
        seller={},
        property_record={},
        contract_type="Illinois CFD",
        documents=[],
        save_related=save_related,
        list_documents=lambda: refreshed,
    )

    assert outcome.state == service.ContractBuildState.GENERATED
    assert outcome.generated_document is not None
    provenance = outcome.generated_document["generation_provenance"]
    assert provenance["facts_fingerprint"]
    assert any(entity == "activities" for entity, _record in saved)
    generated_saves = [record for entity, record in saved if entity == "documents" and record.get("document_type") == "generated_contract"]
    assert len(generated_saves) == 1
    prep_updates = [record for entity, record in saved if entity == "documents" and record.get("document_type") == "contract_prep_facts"]
    assert prep_updates[-1]["document_assembled"] is True
    assert prep_updates[-1]["signing_started"] is False
    assert prep_updates[-1]["external_action_started"] is False


def test_build_contract_does_not_duplicate_current_generation(monkeypatch) -> None:
    prepared = _prep()
    saved_prep = {**prepared, "id": "prep-1"}
    template = {"id": "template-1"}
    fingerprint = service._facts_fingerprint(saved_prep["facts"])
    existing_generated = {
        "id": "generated-1",
        "document_type": "generated_contract",
        "contract_type": "Illinois CFD",
        "approved_legal_template_id": "template-1",
        "generation_provenance": {"facts_fingerprint": fingerprint},
        "links": {"deal_id": "deal-1"},
    }
    refreshed = [saved_prep, template, existing_generated]

    monkeypatch.setattr(service, "contract_prep_document", lambda **kwargs: dict(prepared))
    monkeypatch.setattr(service, "is_illinois_cfd", lambda value: True)
    monkeypatch.setattr(service, "select_exact_approved_template", lambda *args, **kwargs: template)

    def should_not_generate(**kwargs):
        raise AssertionError("duplicate contract generation should not run")

    monkeypatch.setattr(service, "generate_and_store_contract", should_not_generate)

    outcome = service.build_contract_for_deal(
        client=object(),
        deal={},
        deal_id="deal-1",
        seller={},
        property_record={},
        contract_type="Illinois CFD",
        documents=[],
        save_related=lambda *args, **kwargs: True,
        list_documents=lambda: refreshed,
    )

    assert outcome.state == service.ContractBuildState.ALREADY_CURRENT
    assert outcome.generated_document == existing_generated


def test_build_contract_stops_when_required_facts_are_missing(monkeypatch) -> None:
    prepared = _prep(missing=["buyer_1_name", "legal_description"])
    monkeypatch.setattr(service, "contract_prep_document", lambda **kwargs: dict(prepared))

    outcome = service.build_contract_for_deal(
        client=object(),
        deal={},
        deal_id="deal-1",
        seller={},
        property_record={},
        contract_type="Illinois CFD",
        documents=[],
        save_related=lambda *args, **kwargs: True,
        list_documents=lambda: [],
    )

    assert outcome.state == service.ContractBuildState.MISSING_FACTS
    assert "buyer_1_name" in outcome.message
    assert "legal_description" in outcome.message


def test_non_illinois_package_stays_on_existing_coordinator(monkeypatch) -> None:
    prepared = {
        **_prep(),
        "contract_type": "Missouri AFD",
        "facts": {"state": "MO"},
    }
    saved_prep = {**prepared, "id": "prep-mo-1"}
    monkeypatch.setattr(service, "contract_prep_document", lambda **kwargs: dict(prepared))
    monkeypatch.setattr(service, "is_illinois_cfd", lambda value: False)

    outcome = service.build_contract_for_deal(
        client=object(),
        deal={},
        deal_id="deal-1",
        seller={},
        property_record={},
        contract_type="Missouri AFD",
        documents=[],
        save_related=lambda *args, **kwargs: True,
        list_documents=lambda: [saved_prep],
    )

    assert outcome.state == service.ContractBuildState.COORDINATOR_REQUIRED
    assert "coordinator" in outcome.message.lower()
