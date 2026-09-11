import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from cfh_disposition.harness import business_simulator


def test_simulator_results_screen_uses_only_isolated_results(monkeypatch, tmp_path):
    run = tmp_path / "run-fictional"
    run.mkdir()
    result = {"counts": {"PASS": 1, "WARNING": 0, "FAIL": 0}, "scenarios_run": 1,
              "modules_exercised": 1, "modules_inventoried": 2,
              "production_access_attempted": False, "results": [], "coverage": []}
    (run / "results.json").write_text(json.dumps(result))
    monkeypatch.setattr(business_simulator, "RESULTS", tmp_path)

    def forbidden_launch(*args, **kwargs):
        raise AssertionError("Viewing results must not execute a new run")

    monkeypatch.setattr(business_simulator, "launch", forbidden_launch)
    # Match the other simulator UI tests: traced cold Streamlit startup can exceed
    # the framework's three-second default. Keep all isolation assertions intact.
    page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/55_CommandCore_Business_Simulator.py"), default_timeout=30)
    page.session_state.authenticated = True
    page.run()
    assert not page.exception
    assert [(m.label, m.value) for m in page.metric] == [("PASS", "1"), ("WARNING", "0"), ("FAIL", "0")]
    assert "Apply" not in [button.label for button in page.button]
