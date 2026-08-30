from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MY_WORK = ROOT / "pages" / "35_CommandCore_My_Work.py"
OPERATOR = ROOT / "src" / "cfh_disposition" / "my_work_operator.py"


def test_my_work_owns_operator_review_flow() -> None:
    source = MY_WORK.read_text(encoding="utf-8")
    helper = OPERATOR.read_text(encoding="utf-8")

    assert "from cfh_disposition.my_work_operator import render_operator_review" in source
    assert "render_operator_review(" in source
    assert '"commandcore-aging-escalation"' in helper
    assert '"commandcore-operator-state"' in helper
    assert '"commandcore-operator-action"' in helper
    assert "Retry internal dispatch" in helper


def test_operator_review_cannot_bypass_consequential_gates() -> None:
    helper = OPERATOR.read_text(encoding="utf-8")

    assert "No external action or approval was bypassed." in helper
    assert "do not change readiness, approvals, consent, budgets, legal terms" in helper
