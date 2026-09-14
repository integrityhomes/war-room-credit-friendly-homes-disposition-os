"""Marketplace receipt validation only: fictional records, no external transport."""
from copy import deepcopy

import pytest
from test_marketing_attribution import WHEN, closing, fake_client
from test_marketing_attribution import observations as observations
from test_marketing_attribution import records as records

from cfh_disposition.marketing_attribution import UNKNOWN, bind, project, save, touch


def inquiry(data, receipt, prop='property-1', buyer='contact-1', **evidence):
    refs = {'property_id': prop}
    if buyer:
        refs['contact_id'] = buyer
    return touch('manual-marketplace', receipt,
                 {'occurred_at': WHEN, 'medium': 'FACEBOOK_MARKETPLACE',
                  'source': 'FACEBOOK_MARKETPLACE', 'post_id': 'fictional-post',
                  'listing_url': 'https://example.invalid/listing/fictional-post', **evidence},
                 references=refs, records=data)


def test_marketplace_one_property_and_original_source(records):
    before = deepcopy(records)
    records['activities'].append(inquiry(records, 'receipt-1'))
    row, = project(records)
    assert (row['channel'], row['source'], row['property_id'], row['contact_id'], row['deal_id']) == (
        'marketplace', 'FACEBOOK_MARKETPLACE', 'property-1', 'contact-1', 'deal-1')
    assert row['post_id'] == 'fictional-post' and row['original_evidence']['listing_url'].endswith('fictional-post')
    assert all(records[k] == before[k] for k in records if k != 'activities')


def test_same_buyer_two_properties_then_other_channel(records):
    records['properties'].append({'id': 'property-2', 'availability': 'Available'})
    records['activities'].extend([inquiry(records, 'one'), inquiry(records, 'two', prop='property-2'),
                                  inquiry(records, 'three', medium='google', source='google')])
    rows = project(records)
    assert len(rows) == 3 and len(records['contacts']) == 1
    assert {r['contact_id'] for r in rows} == {'contact-1'}
    assert rows[1]['property_id'] == 'property-2' and rows[1]['deal_id'] == UNKNOWN
    assert {r['channel'] for r in rows} == {'marketplace', 'google_ads'}


def test_duplicate_marketplace_receipt_conflicting_retry(records):
    client = fake_client(records)
    original = inquiry(records, 'stable-inquiry')
    assert save(client, original) and not save(client, deepcopy(original))
    with pytest.raises(RuntimeError):
        save(client, inquiry(records, 'stable-inquiry', post_id='different'))
    assert len(records['activities']) == 1


def test_unknown_listing_and_delayed_buyer_deal(records):
    records['deals'] = []
    original = inquiry(records, 'anonymous', buyer=None, post_id=None, listing_url=None)
    records['activities'].append(original)
    before = deepcopy(original)
    row, = project(records)
    assert row['post_id'] == row['contact_id'] == row['deal_id'] == UNKNOWN
    assert row['property_id'] == 'property-1'
    records['deals'].append({'id': 'deal-1', 'links': {'property_id': 'property-1', 'contact_id': 'contact-1'}})
    records['activities'].append(bind(original, 'verified-existing-deal', {'deal_id': 'deal-1'}, records))
    assert project(records)[0]['deal_id'] == 'deal-1' and original == before


@pytest.mark.parametrize('status', ['Sold / Unavailable', 'Pending'])
def test_unavailable_marketplace_inquiry_never_current(records, observations, status):
    records['properties'][0]['availability'] = status
    records['activities'].append(inquiry(records, 'old'))
    row, = project(records, observations)
    assert not row['current_marketing'] and row['result'] == UNKNOWN
    assert records['properties'][0]['availability'] == status


def test_returned_marketplace_period_preserves_history(records, observations):
    evidence = {'occurred_at': WHEN, 'medium': 'FACEBOOK_MARKETPLACE'}
    refs = {'property_id': 'property-1'}
    old = touch('manual-marketplace', 'old', evidence, references=refs, records=records, observations=observations)
    records['activities'].append(old)
    observations['property-1'].update(marketing_observed_since='2026-09-11T00:00:00Z', checked_at='2026-09-12T00:00:00Z')
    records['activities'].append(touch('manual-marketplace', 'returned', {**evidence, 'occurred_at': '2026-09-11T12:00:00Z'},
                                      references=refs, records=records, observations=observations))
    rows = project(records, observations)
    assert not rows[0]['current_marketing'] and rows[1]['current_marketing']
    assert rows[0]['marketing_period'] != rows[1]['marketing_period']


def test_marketplace_sold_wording_is_not_closing(records):
    records['activities'].append(inquiry(records, 'inquiry', status='sold', outcome='filled'))
    records['deals'][0]['status'] = 'closed'
    assert project(records)[0]['result'] == UNKNOWN
    records['transactions'].append(closing())
    assert project(records)[0]['result'] == 'VERIFIED_CLOSING'
