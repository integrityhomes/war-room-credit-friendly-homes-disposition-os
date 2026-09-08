import ast
from pathlib import Path

from cfh_disposition import commandcore_ux

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
UX = ROOT / "src/cfh_disposition/commandcore_ux.py"


def _literal_call_paths(source: str, function_name: str) -> set[str]:
    paths: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != function_name or not node.args:
            continue
        try:
            value = ast.literal_eval(node.args[0])
        except (ValueError, TypeError):
            continue
        if isinstance(value, str):
            paths.add(value)
    return paths


def test_shared_ux_foundation_has_simple_surface_helpers() -> None:
    source = UX.read_text(encoding="utf-8")

    assert commandcore_ux.ADVANCED_SETTINGS_LABEL == "Advanced settings"
    assert 'st.columns((4, 1), vertical_alignment="bottom")' in source
    assert '**What to do next:**' in source
    assert 'with st.expander("Admin / Advanced Tools", expanded=False):' in source
    assert {
        commandcore_ux.SAVE,
        commandcore_ux.NEXT,
        commandcore_ux.ASSIGN,
        commandcore_ux.REVIEW,
        commandcore_ux.SEND_FOR_APPROVAL,
        commandcore_ux.APPROVE,
        commandcore_ux.CANCEL,
    } == {"Save", "Next", "Assign", "Review", "Send for approval", "Approve", "Cancel"}


def test_every_registered_page_remains_linked_from_the_simple_shell() -> None:
    source = APP.read_text(encoding="utf-8")
    registered = _literal_call_paths(source, "Page")
    linked = _literal_call_paths(source, "NavigationItem")

    assert 'DIAGNOSTIC_PAGE = "pages/" + "34_Safe_Full_Payload_Test.py"' in source
    assert 'st.Page(DIAGNOSTIC_PAGE, title="Internal Check")' in source
    assert 'NavigationItem(DIAGNOSTIC_PAGE, "Internal Connection Check")' in source
    assert registered == linked


def test_advanced_navigation_does_not_claim_new_authorization() -> None:
    source = APP.read_text(encoding="utf-8")
    ux_source = UX.read_text(encoding="utf-8")

    assert "require_role" not in source
    assert "require_role" not in ux_source
    assert "Admin / Advanced Tools" in ux_source
