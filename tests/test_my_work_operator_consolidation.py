ROOT = "."
MY_WORK = "pages/35_CommandCore_My_Work.py"
OPERATOR = "src/cfh_disposition/my_work_operator.py"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_my_work_owns_operator_review_flow() -> None:
    source = _read(MY_WORK)
    helper = _read(OPERATOR)

    assert "from cfh_disposition.my_work_operator import render_operator_review" in source
    assert "render_operator_review(" in source
    assert '"commandcore-aging-escalation"' in helper
    assert '"commandcore-operator-state"' in helper
    assert '"commandcore-operator-action"' in helper
    assert "Retry internal dispatch" in helper


def test_operator_review_cannot_bypass_consequential_gates() -> None:
    helper = _read(OPERATOR)

    assert "No external action or approval was bypassed." in helper
    assert "do not change readiness, approvals, consent, budgets, legal terms" in helper
