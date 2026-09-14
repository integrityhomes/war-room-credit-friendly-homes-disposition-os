import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

from cfh_disposition.meta_marketplace_policy import (
    META_HOUSING_SAFETY_PROFILE,
    MetaSafetyContext,
    review_meta_action,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)
COPY = 'Owner financing. Approval is not guaranteed. Equal Housing Opportunity.'


def healthy(**changes):
    data = dict(health={k: 'WORKING' for k in ('profile', 'page', 'ad_account', 'group', 'marketplace', 'instagram')},
                health_checked_at=NOW, housing=dict(META_HOUSING_SAFETY_PROFILE), commerce_required=False,
                facts_verified=True, human_approved=True)
    data.update(changes)
    return MetaSafetyContext(**data)


def review(ctx=None, channel='meta_ads', action='publish', content=COPY):
    return review_meta_action(channel=channel, content=content, action=action, context=ctx, checked_at=NOW)


def test_correct_housing_can_pass_without_executing():
    result = review(healthy())
    assert result.status == 'PASS'
    assert not result.external_action_started
    assert result.human_approval_required


@pytest.mark.parametrize(('key', 'value'), [
    ('special_ad_category', 'NONE'), ('age_min', 21), ('age_max', 64), ('age_max', 65),
    ('gender', 'FEMALE'), ('detailed_targeting', ['interests']), ('excluded_audiences', ['families']),
    ('zip_codes', ['12345']), ('lookalike_audiences', ['audience']), ('protected_class', 'religion'),
])
def test_bad_housing_settings_block(key, value):
    settings = {**META_HOUSING_SAFETY_PROFILE, key: value}
    assert review(healthy(housing=settings)).status == 'BLOCK'


@pytest.mark.parametrize('code', ['2909037', '2909036', '2909035'])
def test_known_provider_errors_block_until_corrected(code):
    result = review(healthy(meta_error_codes=(code,)))
    assert result.status == 'BLOCK'
    assert any(f.code == 'meta.error.' + code for f in result.findings)
    assert result.meta_error_codes == (code,)


def test_restricted_marketplace_blocks_even_with_other_healthy_assets():
    ctx = healthy()
    ctx = ctx.model_copy(update={'health': {**ctx.health, 'marketplace': 'RESTRICTED'}})
    assert review(ctx, 'marketplace').status == 'BLOCK'
    assert review(ctx, 'meta_ads').status == 'PASS'


def test_restricted_ad_account_blocks_only_dependent_channel():
    ctx = healthy()
    ctx = ctx.model_copy(update={'health': {**ctx.health, 'ad_account': 'RESTRICTED'}})
    assert review(ctx).status == 'BLOCK'
    assert review(ctx, 'facebook_groups').status == 'PASS'


def test_no_switching_accounts_to_evade_restrictions_even_in_preparation():
    assert review(healthy(bypass_restriction=True)).status == 'BLOCK'
    assert review(healthy(bypass_restriction=True), action='prepare').status == 'BLOCK'


@pytest.mark.parametrize('state', ['DEPRECATED', 'STALE', 'STALE_OFFSITE_CHECKOUT', 'DISABLED', 'UNKNOWN'])
def test_required_unsafe_commerce_blocks(state):
    assert review(healthy(commerce_required=True, commerce_state=state)).status == 'BLOCK'
    assert review(healthy(commerce_required=False, commerce_state=state)).status == 'PASS'


@pytest.mark.parametrize('state', ['UNKNOWN', 'MANUAL', 'NEEDS_REVIEW', 'ACCESS_BLOCKED_BY_META'])
def test_unknown_or_unsafe_health_fails_closed(state):
    ctx = healthy(health={'profile': state})
    assert review(ctx).status == 'BLOCK'
    assert review(ctx, action='prepare').status == 'WARNING'


def test_missing_and_stale_evidence_fail_closed():
    assert review().status == 'BLOCK'
    assert review(action='prepare').status == 'WARNING'
    for stamp in (None, NOW - timedelta(days=2), NOW + timedelta(minutes=1), NOW.replace(tzinfo=None)):
        assert review(healthy(health_checked_at=stamp)).status == 'BLOCK'
    assert review(healthy(commerce_required=None)).status == 'BLOCK'
    assert review(healthy(facts_verified=None)).status == 'BLOCK'
    assert review(healthy(human_approved=False)).status == 'BLOCK'
    assert review(healthy(required_assets=('pixel',))).status == 'BLOCK'


@pytest.mark.parametrize('copy', ['Guaranteed approval', 'Everyone approved', 'No credit check',
    'Send your password', 'Send payment by gift card', 'Pay an application fee to qualify',
    'Double your money', 'Erase your bad credit', 'Adults only', 'Safe neighborhood'])
def test_existing_protections_remain(copy):
    assert review(healthy(), content=copy).status == 'BLOCK'


def test_audit_logs_digest_and_fixed_findings_without_raw_sensitive_content(caplog):
    with caplog.at_level(logging.INFO):
        result = review(healthy(meta_error_codes=('2909037',)), content='Send your password: fictional-private-value')
    assert 'fictional-private-value' not in caplog.text
    assert result.content_hash in caplog.text
    assert result.policy_version in caplog.text
    record = json.loads(caplog.records[-1].message.split('meta_compliance_decision ', 1)[1])
    assert record['timestamp'] and record['health'] and record['meta_error_codes'] == ['2909037']


def test_live_marketplace_remains_on_hold_even_if_health_is_claimed_healthy():
    assert review(healthy(), 'marketplace').status == 'BLOCK'
    assert review(healthy(), 'marketplace', 'prepare').status == 'WARNING'


def test_public_group_tracking_link_blocks():
    assert review(healthy(), 'facebook_groups', content=COPY + ' https://example.com/tracking').status == 'BLOCK'


def test_instagram_transport_blocks_before_network(monkeypatch):
    from cfh_disposition.models import OwnerFinanceProperty
    from cfh_disposition.social_publish_handoff import SocialPublishHandoffError, dispatch_social_publish_handoff
    from cfh_disposition.social_video_channels import build_social_video_package
    prop = OwnerFinanceProperty(address='100 Fictional St', city='Example', state='IL', zip_code='12345', down_payment=1000, monthly_payment=500)
    package = build_social_video_package(prop, channel_key='instagram', channel_name='Instagram', tracked_link='https://example.com')
    def forbidden(*args, **kwargs):
        pytest.fail('Network must not be called')
    monkeypatch.setattr('cfh_disposition.social_publish_handoff.urlopen', forbidden)
    with pytest.raises(SocialPublishHandoffError, match='Meta publication blocked'):
        dispatch_social_publish_handoff({'SOCIAL_PUBLISH_WEBHOOK_URL': 'https://example.com/hook'},
            property_record=prop, package=package, campaign='test', caption=package.caption_variants[0], approved_by='Owner')


def test_stale_or_forged_meta_launch_payload_is_removed_before_transport(monkeypatch):
    from cfh_disposition.automatic_launch import AutomationDispatchSettings, dispatch_automatic_launch
    captured = []
    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{}'
    def fake_open(request, **kwargs):
        captured.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr('cfh_disposition.automatic_launch.urlopen', fake_open)
    payload = {'channels': [
        {'channel_key': ' META_ADS ', 'copy': 'unsafe', 'posting_blocked': False, 'meta_decision': {'status': 'PASS'}},
        {'channel_key': 'facebook_groups', 'copy': 'unsafe', 'posting_blocked': False},
        {'channel_key': 'email', 'copy': 'unchanged'}]}
    dispatch_automatic_launch(payload, AutomationDispatchSettings(webhook_url='https://example.com/hook'))
    assert captured[0]['channels'] == [{'channel_key': 'email', 'copy': 'unchanged'}]
    assert len(payload['channels']) == 3


@pytest.mark.parametrize('channel', ['marketplace', 'facebook_groups', 'meta_ads', 'instagram'])
def test_refresh_transport_rechecks_meta_even_with_claimed_approval(monkeypatch, channel):
    from cfh_disposition.automatic_launch import AutomationDispatchSettings
    from cfh_disposition.campaign_cadence import CampaignCadenceError, dispatch_refresh_payload
    def forbidden(*args, **kwargs):
        pytest.fail('Network must not be called')
    monkeypatch.setattr('cfh_disposition.campaign_cadence.urlopen', forbidden)
    with pytest.raises(CampaignCadenceError, match='Meta refresh blocked'):
        dispatch_refresh_payload({'channel': {'channel_key': channel, 'copy': COPY, 'approved': True}},
                                 AutomationDispatchSettings(webhook_url='https://example.com/hook'))


def test_saved_legacy_group_assignment_with_url_is_not_presented_as_safe_copy():
    from datetime import date

    from cfh_disposition.facebook_assignments import FacebookPostingAssignment
    from cfh_disposition.facebook_assignments_ui import _assignment_is_stale
    assignment = FacebookPostingAssignment(assignment_date=date(2026, 9, 14), property_id='synthetic',
        property_address='100 Fictional Test St', group_id='test-group', group_name='Test Group',
        assigned_to_id='test-operator', assigned_to_name='Test Operator', tracked_link='https://example.com/internal',
        variation_label='Legacy', post_copy='Old copy https://example.com/internal')
    stale, reason = _assignment_is_stale(assignment, None)
    assert stale and 'internal-only' in reason


def test_known_unavailable_property_blocks_despite_claimed_fact_verification():
    from cfh_disposition.models import OwnerFinanceProperty, PropertyStatus
    prop = OwnerFinanceProperty(address='100 Fictional Test St', status=PropertyStatus.SOLD, down_payment=1000, monthly_payment=500)
    result = review_meta_action(channel='meta_ads', content='100 Fictional Test St $1,000 $500',
                                action='advertise', context=healthy(), property_record=prop, checked_at=NOW)
    assert any(f.code == 'meta.property_status' for f in result.findings)
