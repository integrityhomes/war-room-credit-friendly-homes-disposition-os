from pathlib import Path


def test_crm_deal_form_links_seller_and_property() -> None:
    source = Path("pages/44_CommandCore_CRM.py").read_text(encoding="utf-8")

    for marker in (
        '"Seller / contact"',
        '"Property"',
        'updated_links["contact_id"] = contact_id',
        'updated_links["property_id"] = property_id',
        '"links": updated_links',
        'deal_form(selected, load_records("contacts"), load_records("properties"))',
    ):
        assert marker in source


def test_crm_has_clear_daily_navigation() -> None:
    source = Path("pages/44_CommandCore_CRM.py").read_text(encoding="utf-8")

    for marker in (
        'label="← Command Center"',
        'label="Pipeline & Follow-Up"',
        'label="Unified Deal Record"',
        '"Open Unified Deal Record"',
    ):
        assert marker in source
