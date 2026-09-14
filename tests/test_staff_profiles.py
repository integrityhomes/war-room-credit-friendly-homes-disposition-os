"""Selected synthetic read-only routing coverage; no private roster or writer."""
import copy

import pytest

from cfh_disposition.corepilot_staff import staff_answer
from cfh_disposition.staff_profiles import resolve_member, route_function, work_for


def team():
    functions = [('Ops Example', ['operations_management']), ('Coordinator Example', ['closing_coordination', 'title_communication', 'cfd_preparation']),
                 ('Buyer Example', ['buyer_followup', 'buyer_communication']), ('Acquisition Example', ['acquisitions', 'offer_preparation']),
                 ('Data Example', ['lead_data_operations', 'crm_automation']), ('Social Example', ['property_marketing', 'paid_ad_management'])]
    members = []
    for index, (name, capabilities) in enumerate(functions):
        profile = dict(title=name, responsibilities=['Synthetic operational work'], functions=capabilities,
                               systems=['Fictional system'], communication_authority='Verified routine work only',
                               approval_limits=['Owner approval for consequential exceptions'], escalation=['Example Owner'],
                               handoffs={'next': ['Coordinator Example']}, prohibited_actions=['Owner exceptions'],
                               universal_staff_backup=index == 0, source={'file': 'fictional.xlsx'},
                               questionnaire='Original synthetic questionnaire answer. ' * 5)
        members.append({'id': f'staff-{index}', 'name': name, 'active': True, 'availability': 'available', 'profile': profile})
    return {'team_members': members, 'tasks': []}


@pytest.mark.parametrize('index,function', [(1, 'closing_coordination'), (2, 'buyer_followup'), (3, 'acquisitions'),
                                         (4, 'lead_data_operations'), (4, 'crm_automation'), (5, 'property_marketing')])
def test_profile_driven_routing_and_universal_backup(index, function):
    records = team()
    member = records['team_members'][index]
    assert route_function(function, records) == [member]
    assert route_function(function, records, backup_for=member['name']) == [records['team_members'][0]]
    assert resolve_member('Future Unconfigured Worker', records) is None
    assert not route_function(function, records, backup_for='Future Unconfigured Worker')


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
