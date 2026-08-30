from pathlib import Path

from cfh_disposition.commandcore_contract_template_ui import _approval_label, _latest_template


def test_latest_template_is_scoped_by_package_and_state() -> None:
    documents = [
        {"document_type": "contract_template", "contract_type": "Illinois CFD", "state": "IL", "version": 1},
        {"document_type": "contract_template", "contract_type": "Illinois CFD", "state": "IL", "version": 3},
        {"document_type": "contract_template", "contract_type": "Illinois CFD", "state": "MO", "version": 8},
    ]

    latest = _latest_template(documents, contract_type="Illinois CFD", state="IL")

    assert latest is not None
    assert latest["version"] == 3


def test_template_approval_label_never_treats_pending_upload_as_active() -> None:
    pending = {
        "status": "needs_legal_approval",
        "approved_for_use": False,
        "legal_approved": False,
    }
    approved = {
        "status": "approved",
        "approved_for_use": True,
        "legal_approved": True,
    }

    assert _approval_label(pending) == "Needs legal approval"
    assert _approval_label(approved) == "Approved for use"


def test_contract_templates_are_exposed_inside_commandcore_management() -> None:
    app_source = Path("app.py").read_text(encoding="utf-8")
    page_source = Path("pages/50_CommandCore_Contract_Templates.py").read_text(encoding="utf-8")

    assert '"pages/50_CommandCore_Contract_Templates.py"' in app_source
    assert 'title="Contract Templates"' in app_source
    assert "New versions stay pending until the required approval is recorded." in page_source
    assert "make active" not in page_source.lower()
