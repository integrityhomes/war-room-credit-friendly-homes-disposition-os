"""Regression coverage for routing failures; fictional people and linked records."""
import copy

import pytest
from test_staff_profiles import team

from cfh_disposition.corepilot_conversation import answer
from cfh_disposition.corepilot_staff import staff_answer


def records():
    data = team()
    members = data['team_members']
    members[1]['profile']['functions'].append('buyer_onboarding')
    members[0]['profile']['functions'] = sorted({f for m in members for f in m['profile']['functions']})
    data.update(contacts=[{'id': 'example-contact'}], properties=[{'id': 'example-property'}],
                deals=[{'id': 'example-deal', 'links': {'property_id': 'example-property', 'contact_id': 'example-contact'}}],
                tasks=[{'id': 'example-task', 'title': 'Coordinate CFD contracts', 'links': {'deal_id': 'example-deal'}}])
    return data


@pytest.mark.parametrize('phrase,index', [
    ('wholesale closing', 1), ('CFD contracts', 1), ('buyer onboarding', 1), ('title coordination', 1),
    ('buyer follow-up', 2), ('agent lead', 3), ('FSBO lead', 3), ('off-market acquisition', 3),
    ('offers within approved rules', 3), ('XLeads intake', 4), ('CRM automation', 4),
    ('GHL duties and XLeads assignment', 4), ('paid property marketing', 5), ('unpaid property marketing', 5),
])
def test_exact_failed_phrases_select_specialist_not_universal_backup(phrase, index):
    data = records()
    before = copy.deepcopy(data)
    result = answer(f'Who should handle this {phrase}?', data)
    assert result.what_i_found == (f"{data['team_members'][index]['name']} — {data['team_members'][index]['profile']['title']}",)
    assert not result.clarification and 'specialist' in result.recommended_next_step
    assert not result.records_written and not result.external_actions_started and data == before


def test_context_only_routing_resolves_all_canonical_links_and_preserves_handoff():
    data = records()
    before = copy.deepcopy(data)
    result = answer('Who should handle this?', data, context={'task_id': 'example-task'})
    expected = {'task_id': 'example-task', 'deal_id': 'example-deal', 'property_id': 'example-property', 'contact_id': 'example-contact'}
    assert dict(result.context) == expected
    assert result.what_i_found[0].startswith('Coordinator Example')
    followup = staff_answer('Ops Example is covering Coordinator Example today', data, expected)
    assert dict(followup.context) == expected and not followup.records_written
    assert data == before


@pytest.mark.parametrize('change', ['missing', 'archived', 'duplicate', 'conflicting'])
def test_invalid_context_asks_without_guessing_or_replacing_links(change):
    data = records()
    ctx = {'task_id': 'example-task'}
    if change == 'missing':
        data['deals'] = []
    elif change == 'archived':
        data['tasks'][0]['archived'] = True
    elif change == 'duplicate':
        data['tasks'].append(copy.deepcopy(data['tasks'][0]))
    else:
        ctx['deal_id'] = 'different-deal'
    result = answer('Who should handle this?', data, context=ctx)
    assert result.clarification and not result.what_i_found and dict(result.context) == ctx


def test_competing_work_and_duplicate_specialists_require_one_clarification():
    data = records()
    result = answer('Who should handle buyer follow-up and title coordination?', data)
    assert result.clarification.count('?') == 1 and not result.what_i_found
    duplicate = copy.deepcopy(data['team_members'][1])
    duplicate.update(id='another-coordinator', name='Second Example')
    data['team_members'].append(duplicate)
    result = answer('Who should handle this closing?', data)
    assert 'Second Example' in result.clarification and not result.what_i_found


def test_unavailable_specialist_uses_available_backup_without_owner_authority():
    data = records()
    data['team_members'][1]['availability'] = 'unavailable'
    result = answer('Who should handle this closing?', data)
    assert result.what_i_found[0].startswith('Ops Example')
    assert 'backup because' in result.recommended_next_step
    assert 'owner approval authority' in ' '.join(result.needs_attention)
    data['team_members'][0]['availability'] = 'unavailable'
    assert answer('Who should handle this closing?', data).clarification


def test_unknown_context_and_owner_request_do_not_grant_staff_authority():
    data = records()
    assert answer('Who should handle this?', data).clarification
    result = answer('Who should handle owner approval?', data)
    assert result.what_i_found == ('Shawn or Sabrina must make owner-level approval decisions.',)
    assert not result.records_written and not result.external_actions_started


@pytest.mark.parametrize('title', ['Approve offer', 'Owner approval'])
def test_selected_owner_decision_never_routes_to_acquisitions_or_backup(title):
    data = records()
    data['tasks'][0]['title'] = title
    result = answer('Who should handle this?', data, context={'task_id': 'example-task'})
    assert result.what_i_found == ('Shawn or Sabrina must make owner-level approval decisions.',)
    assert dict(result.context)['task_id'] == 'example-task'
    assert not result.records_written
