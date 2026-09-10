"""Synthetic staff only. No questionnaire, real roster, or production writes."""
import copy
from datetime import date

import pytest

from cfh_disposition.corepilot_staff import staff_answer
from cfh_disposition.staff_profiles import (
    StaffProfile,
    delegation_check,
    resolve_member,
    route_function,
    weekly_budget_status,
    work_for,
)


def team():
    functions = [('Ops Example', ['operations_management']), ('Coordinator Example', ['closing_coordination', 'title_communication', 'cfd_preparation']),
                 ('Buyer Example', ['buyer_followup', 'buyer_communication']), ('Acquisition Example', ['acquisitions', 'offer_preparation']),
                 ('Data Example', ['lead_data_operations', 'crm_automation']), ('Social Example', ['property_marketing', 'paid_ad_management'])]
    members = []
    for index, (name, capabilities) in enumerate(functions):
        profile = StaffProfile(title=name, responsibilities=['Synthetic operational work'], functions=capabilities,
                               systems=['Fictional system'], communication_authority='Verified routine work only',
                               approval_limits=['Owner approval for consequential exceptions'], escalation=['Example Owner'],
                               handoffs={'next': ['Coordinator Example']}, prohibited_actions=['Owner exceptions'],
                               universal_staff_backup=index == 0, source={'file': 'fictional.xlsx'},
                               questionnaire='Original synthetic questionnaire answer. ' * 5)
        members.append({'id': f'staff-{index}', 'name': name, 'active': True, 'availability': 'available', 'profile': profile.model_dump()})
    return {'team_members': members, 'tasks': []}


@pytest.mark.parametrize('index,function', [(1, 'closing_coordination'), (2, 'buyer_followup'), (3, 'acquisitions'),
                                         (4, 'lead_data_operations'), (4, 'crm_automation'), (5, 'property_marketing')])
def test_profile_driven_routing_and_universal_backup(index, function):
    records = team()
    member = records['team_members'][index]
    assert route_function(function, records) == [member]
    assert route_function(function, records, backup_for=member['name']) == [records['team_members'][0]]
    assert not delegation_check(records['team_members'][0], function, owner_consequential=True)['eligible']
    assert resolve_member('Future Unconfigured Worker', records) is None
    assert not route_function(function, records, backup_for='Future Unconfigured Worker')
    assert not delegation_check(records['team_members'][0], 'unknown_money_movement')['eligible']


@pytest.mark.parametrize('index,function', [(1, 'title_communication'), (2, 'buyer_communication'), (3, 'offer_preparation')])
def test_delegation_requires_existing_rules_facts_and_consent_without_sending(index, function):
    member = team()['team_members'][index]
    assert not delegation_check(member, function)['eligible']
    allowed = delegation_check(member, function, facts_verified=True, consent_verified=True, within_approved_rules=True)
    assert allowed['eligible'] and not allowed['external_execution']
    assert not delegation_check(member, function, facts_verified=True, consent_verified=True, within_approved_rules=False)['eligible']


@pytest.mark.parametrize('spent,level,allowed', [(0, 'Within', True), (74, 'Within', True), (75, 'Warning', True),
                                              (90, 'High-priority', True), (100, 'Blocked', False), (101, 'Blocked', False)])
def test_weekly_budget_thresholds(spent, level, allowed):
    evidence = {'approval_verified': True, 'week_start': '2030-01-07', 'week_end': '2030-01-13', 'approved_amount': 100, 'spent': spent}
    before = copy.deepcopy(evidence)
    status = weekly_budget_status(evidence, today=date(2030, 1, 8))
    assert status['level'].startswith(level) and status['new_spend_allowed'] is allowed
    assert evidence == before
    assert not weekly_budget_status(evidence, today=date(2030, 1, 14))['new_spend_allowed']
    assert not weekly_budget_status(evidence, today=date(2030, 1, 8), proposed_spend=101)['new_spend_allowed']


@pytest.mark.parametrize('patch', [{'approval_verified': False}, {'spent': 'NaN'}, {'approved_amount': -1}, {'week_end': '2030-02-01'}])
def test_unverified_budget_never_authorizes_spend(patch):
    evidence = {'approval_verified': True, 'week_start': '2030-01-07', 'week_end': '2030-01-13', 'approved_amount': 100, 'spent': 0, **patch}
    assert not weekly_budget_status(evidence, today=date(2030, 1, 8))['new_spend_allowed']


def test_staff_context_workload_handoffs_and_private_details():
    records = team()
    records['tasks'] = [{'id': 't', 'assigned_to': 'staff-2', 'title': 'Buyer review', 'status': 'open'}]
    assert len(work_for(records['team_members'][2], records['tasks'])) == 1
    before = copy.deepcopy(records)
    for query in ('Who should handle this closing issue?', 'Who can cover this if someone is out?', 'Who is overloaded?',
                  "What is Social Example's weekly ad budget?", 'Ops Example is covering Coordinator Example today'):
        result = staff_answer(query, records, {'property_id': 'fictional-property'})
        assert result and dict(result.context)['property_id'] == 'fictional-property'
        assert not result.records_written and not result.external_actions_started
    assert records == before


def test_profile_creation_is_gated_duplicate_safe_and_preserves_source():
    import json
    from types import SimpleNamespace

    from cfh_disposition.staff_profiles import create_profile
    stored = {}
    class Bucket:
        def list(self, prefix, options):
            return [{'name': k.split('/')[-1]} for k in stored]
        def download(self, path):
            return stored[path]
        def upload(self, path, data, file_options):
            assert file_options['upsert'] == 'false' and path not in stored
            stored[path] = data
    client = SimpleNamespace(storage=SimpleNamespace(from_=lambda name: Bucket()))
    member = {**team()['team_members'][0], 'email': 'ops@example.invalid'}
    with pytest.raises(PermissionError):
        create_profile(client, member)
    assert not stored
    assert create_profile(client, member, preservation_verified=True)
    assert not create_profile(client, member, preservation_verified=True)
    assert json.loads(next(iter(stored.values()))) == member
    with pytest.raises(ValueError):
        create_profile(client, {**member, 'id': 'different'}, preservation_verified=True)


def test_handoff_never_routes_to_unconfigured_worker_and_preserves_context():
    from cfh_disposition.staff_profiles import handoff_targets
    records = team()
    member = records['team_members'][2]
    member['profile']['handoffs']['next'].append('Future Worker')
    assert handoff_targets(member, 'next', records) == [records['team_members'][1]]
    records['contacts'] = [{'id': 'lead', 'source': 'XLeads', 'external_id': 'fictional-external', 'assigned_to': 'Acquisition Example'}]
    result = staff_answer('Show XLeads lists', records, {'contact_id': 'lead'})
    assert 'fictional-external' in str(result.what_i_found) and dict(result.context) == {'contact_id': 'lead'}
    assert not result.records_written


@pytest.mark.parametrize('text', ['Review an agent lead', 'Review a FSBO lead', 'Review an off-market seller'])
def test_acquisition_channels_share_verified_profile_routing(text):
    from cfh_disposition.staff_profiles import requested_function
    assert requested_function(text) == 'acquisitions'
    assert route_function(requested_function(text), team())[0]['name'] == 'Acquisition Example'


def test_actual_streamlit_staff_routing_and_verified_task(surfaces, monkeypatch):  # noqa: F811
    from test_simulator_business_surfaces import page_for
    records = team()
    backend, _ = surfaces
    backend.allow_internal = True
    monkeypatch.setattr('cfh_disposition.staff_profiles.read_team', lambda client: records['team_members'])
    page = page_for('pages/49_CommandCore_Command_Bot.py').run()
    before = copy.deepcopy({k: v for k, v in backend.data.items() if k != 'tasks'})
    for query in ('Who should handle this closing issue?', 'Find 101 Example Lane.', 'Have Buyer Example follow up tomorrow.'):
        page.text_input(key='corepilot_request').set_value(query)
        page.button(key='FormSubmitter:corepilot_request_form-Ask CorePilot').click().run()
        assert not page.exception
    assert any(t.get('assigned_to') == 'Buyer Example' for t in backend.data['tasks'])
    assert before == {k: v for k, v in backend.data.items() if k != 'tasks'}
    assert not backend.denied


# Reuse the simulator's canonical transport fixture, not live staff records.
from test_simulator_business_surfaces import surfaces  # noqa: E402,F401
