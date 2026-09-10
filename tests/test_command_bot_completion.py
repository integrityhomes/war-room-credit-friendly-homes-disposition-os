"""Permanent real-page conversations using only synthetic canonical transports."""
import copy
from datetime import UTC, date, datetime, timedelta

import pytest
from test_simulator_business_surfaces import page_for, surfaces  # noqa: F401

from cfh_disposition.corepilot_orchestrator import run_corepilot
from cfh_disposition.property_change_detection import detect_property_changes


@pytest.fixture
def command_page(surfaces, monkeypatch):  # noqa: F811
    backend, _ = surfaces
    backend.allow_internal = True
    class Wednesday(date):
        @classmethod
        def today(cls):
            return cls(2030, 1, 2)
    monkeypatch.setattr('cfh_disposition.corepilot_internal.date', Wednesday)
    backend.data['tasks'] = []
    backend.data['contacts'][0]['assigned_to'] = 'Sabrina'
    backend.data['properties'][0].update(assigned_to='Gabe', down_payment=3000, monthly_payment=850,
                                       sync_metadata={'field_warnings': ['Insurance needs review']})
    checkpoint = {'inventory_observations': {'simulation-property': {
        'status': 'available', 'marketing_status': 'yellow',
        'marketing_observed_since': (datetime.now(UTC)-timedelta(days=21)).isoformat()}}}
    changes = detect_property_changes([], [], source_reference='simulation')
    monkeypatch.setattr('cfh_disposition.property_change_runtime.read_property_changes', lambda *a, **kw: changes)
    monkeypatch.setattr('cfh_disposition.property_change_runtime.latest_property_check', lambda *a: checkpoint)
    app = page_for('pages/49_CommandCore_Command_Bot.py').run()

    def ask(query):
        app.text_input(key='corepilot_request').set_value(query)
        app.button(key='FormSubmitter:corepilot_request_form-Ask CorePilot').click().run()
        assert not app.exception and not backend.denied
        return ' '.join(str(x.value) for group in (app.markdown, app.info, app.warning, app.success) for x in group)
    return backend, app, ask


def test_complete_property_task_followup_sequence(command_page):
    backend, app, ask = command_page
    protected = copy.deepcopy({k: v for k, v in backend.data.items() if k != 'tasks'})
    assert 'Property' in ask('Find 101 Example Lane.') or app.session_state.corepilot_context['property_id'] == 'simulation-property'
    assert 'No matching' in ask('What changed on it?')
    assert 'PROPOSED PLAN' in ask("Why isn't it selling?")
    assert 'Task created' in ask('Have Sabrina follow up tomorrow.')
    task = backend.data['tasks'][0]
    assert app.session_state.corepilot_context['task_id'] == task['id']
    assert 'duplicate prevented' in ask('Have Sabrina follow up tomorrow.')
    assert len(backend.data['tasks']) == 1
    ask('Move that to Friday.')
    assert datetime.fromisoformat(task['due_date']).weekday() == 4
    ask('Give it to Gabe.')
    assert task['assigned_to'] == 'Gabe'
    assert 'What should the private note say?' in ask('Add a note.')
    ask('Add a note that we are waiting on the seller.')
    ask('Mark it done.')
    assert task['status'] == 'done' and len(task['internal_history']) == 4
    assert protected == {k: backend.data[k] for k in protected}


def test_portfolio_and_readonly_business_questions(command_page):
    backend, app, ask = command_page
    before = copy.deepcopy(backend.data)
    for query in ('What needs my attention?', 'What should we work on first?', 'Which properties are stale?',
                  'Give me a plan for every stale property.', 'Which properties hit 10 days?',
                  'Which ones are at 14 days?', 'Which ones are urgent at 21 days?'):
        assert '101 Example Lane' in ask(query)
    ask('Find 101 Example Lane.')
    assert '3000' in ask('What is the down payment?')
    assert '850' in ask('What is the monthly payment?')
    assert 'Insurance needs review' in ask('What are the current terms?')
    assert 'legal ownership' in ask('Who owns this property?')
    assert 'Linked documents' in ask('Show me everything related to this property.')
    assert 'approval' in ask('What approvals are waiting?').lower()
    assert 'No approval' in ask('What happens if I approve this?')
    assert 'Fictional' in ask('What communications need responses?')
    assert app.session_state.corepilot_context['communication_id'] == 'simulation-message'
    ask('Draft a reply.')  # Missing consent stays a private withheld preview.
    assert app.session_state.corepilot_context['communication_id'] == 'simulation-message'
    assert backend.data == before


def test_deal_attention_followup_selects_only_unique_match(command_page):
    backend, app, ask = command_page
    backend.data['tasks'] = [{'id': 'blocked', 'title': 'Waiting for title', 'status': 'blocked', 'blocker': 'Title report needed',
                              'links': {'deal_id': 'simulation-deal'}}]
    ask('What deals need attention?')
    assert app.session_state.corepilot_context['deal_id'] == 'simulation-deal'
    assert 'approval' in ask('What is holding this one up?').lower()


def test_missing_details_and_unknown_request_never_guess():
    records = {'properties': [{'id': 'synthetic', 'address': '101 Example Lane'}]}
    for query in ('Who owns this property?', 'What is the down payment?'):
        result = run_corepilot(query, records, context={'property_id': 'synthetic'})
        assert 'Not recorded' in ' '.join(result.what_i_found)
        assert result.records_written == result.external_actions_started == 0
    assert run_corepilot('Something unspecified', records).clarification


def test_overdue_and_today_queries_filter_canonical_tasks():
    records = {'tasks': [{'id': 'old', 'title': 'Old work', 'due_date': '2000-01-01', 'status': 'open'},
                         {'id': 'future', 'title': 'Future work', 'due_date': '2099-01-01', 'status': 'open'}]}
    result = run_corepilot('Show overdue work', records)
    assert result.what_i_found == ('Old work',)
