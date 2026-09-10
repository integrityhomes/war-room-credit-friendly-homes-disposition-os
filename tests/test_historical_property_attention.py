"""Historical source discrepancies remain auditable, not ignored-review priorities."""
import copy
from pathlib import Path
from types import SimpleNamespace

import streamlit as st
from streamlit.testing.v1 import AppTest
from test_property_sync_preview import property_record, source_row

from cfh_disposition.corepilot_orchestrator import run_corepilot
from cfh_disposition.property_change_detection import detect_property_changes
from cfh_disposition.property_change_review import current_attention_changes, record_review_decision


def test_ignored_historical_events_leave_history_and_current_clocks_intact(monkeypatch, tmp_path):
    from dataclasses import replace

    from cfh_disposition.property_change_cache import encode_result, read_cache, save_cache
    prop = property_record(availability='Sold / Unavailable', interest_rate='10')
    row = replace(source_row(availability='Sold / Unavailable', interest_rate='12'), tab='SOLD')
    result = detect_property_changes([row], [prop], source_reference='fictional')
    assert result.changes and result.observed_changes
    cache = {'version': 1, 'result': encode_result(result), 'inventory_observations': {}, 'change_evidence': {'preserved': {'source': 'historical'}}}
    path = tmp_path/'checkpoint.json'
    save_cache(path, cache)
    cache = read_cache(path)
    monkeypatch.setattr('cfh_disposition.property_change_review.cache_path', lambda _: path)
    for event in (*result.changes, *result.observed_changes):
        record_review_decision({}, event.event_id, 'Ignored')
    after = read_cache(path)
    assert all(after[key] == value for key, value in cache.items())
    filtered = current_attention_changes(result, after['review_decisions'])
    assert not filtered.changes and not filtered.observed_changes
    assert filtered.state == result.state and result.changes
    assert current_attention_changes(result, {}) == result
    records = {'properties': [prop]}
    for query in ('What should we work on first?', 'What needs my attention?', 'Which properties are stale?'):
        answer = run_corepilot(query, records, property_changes=filtered, inventory_evidence={})
        assert prop['address'] not in ' '.join(answer.what_i_found)

    monkeypatch.setattr('supabase.create_client', lambda *a, **kw: SimpleNamespace(functions=SimpleNamespace(
        invoke=lambda name, options: {'ok': True, 'records': records.get(options['body']['entity'], [])})))
    monkeypatch.setattr('cfh_disposition.property_change_runtime.read_property_changes', lambda *a: result)
    monkeypatch.setattr('cfh_disposition.property_change_runtime.latest_property_check', lambda *a: after)
    before = copy.deepcopy(after)
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/49_CommandCore_Command_Bot.py'))
        page.secrets.update(APP_PASSWORD='fictional', SUPABASE_URL='fictional', SUPABASE_SERVICE_ROLE_KEY='fictional')
        page.session_state.authenticated = True
        page.run()
        for query in ('What should we work on first?', 'What needs my attention?', 'Show me all important property changes.'):
            page.text_input(key='corepilot_request').set_value(query)
            page.button(key='FormSubmitter:corepilot_request_form-Ask CorePilot').click().run()
            assert not page.exception
            shown = ' '.join(str(x.value) for group in (page.markdown, page.info, page.warning) for x in group)
            assert prop['address'] not in shown
        assert after == before
    finally:
        st.cache_resource.clear()
