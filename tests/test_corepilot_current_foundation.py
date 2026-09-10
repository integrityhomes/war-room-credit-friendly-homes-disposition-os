"""Current canonical inventory must win over old pre-import display snapshots."""
import copy
from pathlib import Path
from types import SimpleNamespace

import streamlit as st
from streamlit.testing.v1 import AppTest
from test_property_sync_preview import property_record, source_row

from cfh_disposition.corepilot_inventory import foundation_summary
from cfh_disposition.property_change_detection import detect_property_changes
from cfh_disposition.property_change_review import current_attention_changes
from cfh_disposition.property_sync_preview import address_key


def test_imported_new_event_reconciled_without_erasing_history_or_other_work():
    rows = [source_row()]
    old = detect_property_changes(rows, [], source_reference='fictional')
    prop = property_record(source='cfh-google-sheet')
    prop['sync_metadata'] = {'normalized_address': address_key(prop)}
    snapshot = copy.deepcopy(old)
    current = current_attention_changes(old, {}, [prop])
    assert not current.changes and not current.new_events
    assert old == snapshot and old.changes and old.state == current.state
    assert current_attention_changes(old, {}, []) == old
    assert current_attention_changes(old, {}, [prop, {**prop, 'id': 'duplicate'}]) == old
    assert current_attention_changes(old, {}, [{**prop, 'sync_metadata': {}}]) == old


def test_real_page_counts_live_records_and_clocks_not_old_coverage(monkeypatch):
    prop = property_record(source='cfh-google-sheet')
    prop['sync_metadata'] = {'normalized_address': address_key(prop)}
    old = detect_property_changes([source_row()], [], source_reference='fictional')
    checkpoint = {'source_coverage': {'tab_count': 99, 'source_colors': {'yellow': 99}, 'eligible_canonical_yellow': 0, 'unresolved_address_rows': 99},
                  'inventory_observations': {prop['id']: {'status': 'available', 'marketing_status': 'yellow', 'marketing_observed_since': '2030-01-01'}}}
    # Use an actual past observation, never a future clock fixture.
    checkpoint['inventory_observations'][prop['id']]['marketing_observed_since'] = '2020-01-01'
    before = copy.deepcopy(checkpoint)
    records = {'properties': [prop]}
    monkeypatch.setattr('supabase.create_client', lambda *a, **kw: SimpleNamespace(functions=SimpleNamespace(
        invoke=lambda name, options: {'ok': True, 'records': records.get(options['body']['entity'], [])})))
    monkeypatch.setattr('cfh_disposition.property_change_runtime.read_property_changes', lambda *a: old)
    monkeypatch.setattr('cfh_disposition.property_change_runtime.latest_property_check', lambda *a: checkpoint)
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/49_CommandCore_Command_Bot.py'))
        page.secrets.update(APP_PASSWORD='fictional', SUPABASE_URL='fictional', SUPABASE_SERVICE_ROLE_KEY='fictional')
        page.session_state.authenticated = True
        page.run()
        for query, expected in [('How many properties are currently being marketed?', '1 properties are currently being marketed.'),
                                ('How many marketed properties have tracking clocks?', '1 marketed properties have valid tracking clocks.'),
                                ('What should we work on first?', 'stale inventory review')]:
            page.text_input(key='corepilot_request').set_value(query)
            page.button(key='FormSubmitter:corepilot_request_form-Ask CorePilot').click().run()
            assert not page.exception
            shown = ' '.join(str(x.value) for group in (page.markdown, page.info, page.warning, page.caption) for x in group)
            assert expected in shown and 'NEW PROPERTY' not in shown and 'Only 0' not in shown
        assert checkpoint == before and old.changes
    finally:
        st.cache_resource.clear()
    counts = foundation_summary([prop], checkpoint['inventory_observations'])
    assert counts['valid_clocks'] == counts['current_yellow'] == 1 and not counts['missing_clocks']
