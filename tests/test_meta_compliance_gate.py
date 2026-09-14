from cfh_disposition.meta_compliance_gate import (
    ComplianceDecision,
    MetaAccessState,
    MetaAccountHealth,
    MetaCommerceHealth,
    MetaCommerceState,
    MetaHousingAdConfig,
    review_meta_compliance,
)


def compliant_housing_ad() -> MetaHousingAdConfig:
    return MetaHousingAdConfig(
        special_ad_category="Housing",
        min_age=18,
        max_age=65,
        max_age_is_plus=True,
        gender="All",
    )


def test_compliant_meta_health_and_housing_ad_pass() -> None:
    result = review_meta_compliance(
        account=MetaAccountHealth(),
        housing_ad=compliant_housing_ad(),
        commerce=MetaCommerceHealth(state=MetaCommerceState.NOT_REQUIRED),
    )

    assert result.decision == ComplianceDecision.PASS
    assert result.blocked_channels == ()
    assert result.findings == ()


def test_housing_age_must_be_18_to_65_plus() -> None:
    result = review_meta_compliance(
        housing_ad=MetaHousingAdConfig(
            special_ad_category="Housing",
            min_age=25,
            max_age=65,
            max_age_is_plus=True,
            gender="All",
        )
    )

    assert result.decision == ComplianceDecision.BLOCK
    assert result.is_blocked("meta_ads")
    assert "18–65+" in result.block_reason("meta_ads")


def test_housing_special_category_gender_and_targeting_are_enforced() -> None:
    result = review_meta_compliance(
        housing_ad=MetaHousingAdConfig(
            special_ad_category="None",
            min_age=18,
            max_age=65,
            max_age_is_plus=True,
            gender="Women",
            detailed_targeting=("Real estate", "Keller Williams Realty"),
        )
    )

    assert result.decision == ComplianceDecision.BLOCK
    reason = result.block_reason("meta_ads")
    assert "Housing Special Ad Category" in reason
    assert "gender must be All" in reason
    assert "Detailed targeting must be empty" in reason


def test_any_active_meta_ad_error_blocks_and_known_housing_codes_are_recognized() -> None:
    ad = compliant_housing_ad()
    result = review_meta_compliance(
        housing_ad=MetaHousingAdConfig(
            special_ad_category=ad.special_ad_category,
            min_age=ad.min_age,
            max_age=ad.max_age,
            max_age_is_plus=ad.max_age_is_plus,
            gender=ad.gender,
            active_error_codes=("2909037", "2909036", "2909035", "9999999"),
        )
    )

    assert result.is_blocked("meta_ads")
    reason = result.block_reason("meta_ads")
    assert "2909037" in reason
    assert "previously observed Housing audience/targeting error family" in reason


def test_marketplace_restriction_blocks_marketplace_only() -> None:
    result = review_meta_compliance(
        account=MetaAccountHealth(
            marketplace_access=MetaAccessState.ACCESS_BLOCKED_BY_META,
        )
    )

    assert result.is_blocked("marketplace")
    assert not result.is_blocked("facebook_groups")
    assert not result.is_blocked("meta_ads")


def test_ad_account_restriction_blocks_paid_meta_ads() -> None:
    result = review_meta_compliance(
        account=MetaAccountHealth(
            ad_account_access=MetaAccessState.NEEDS_REVIEW,
        )
    )

    assert result.is_blocked("meta_ads")
    assert not result.is_blocked("marketplace")


def test_profile_restriction_blocks_all_meta_channels() -> None:
    result = review_meta_compliance(
        account=MetaAccountHealth(
            profile_access=MetaAccessState.ACCESS_BLOCKED_BY_META,
        )
    )

    assert set(result.blocked_channels) == {
        "marketplace",
        "facebook_groups",
        "meta_ads",
        "instagram",
    }


def test_anti_circumvention_rule_blocks_all_meta_channels() -> None:
    result = review_meta_compliance(
        account=MetaAccountHealth(alternate_account_bypass_requested=True)
    )

    assert result.decision == ComplianceDecision.BLOCK
    assert set(result.blocked_channels) == {
        "marketplace",
        "facebook_groups",
        "meta_ads",
        "instagram",
    }
    assert "bypass" in result.block_reason("marketplace").lower()


def test_stale_or_deprecated_commerce_blocks_marketplace_and_meta_ads() -> None:
    result = review_meta_compliance(
        commerce=MetaCommerceHealth(
            state=MetaCommerceState.STALE_OFFSITE,
            detail="legacy offsite checkout flag",
        )
    )

    assert result.is_blocked("marketplace")
    assert result.is_blocked("meta_ads")
    assert "unnecessary Shop" in result.block_reason("marketplace")


def test_deactivated_or_not_required_commerce_is_healthy() -> None:
    for state in (MetaCommerceState.DEACTIVATED, MetaCommerceState.NOT_REQUIRED):
        result = review_meta_compliance(commerce=MetaCommerceHealth(state=state))
        assert result.decision == ComplianceDecision.PASS
        assert result.blocked_channels == ()


def test_unknown_health_warns_without_silently_blocking() -> None:
    result = review_meta_compliance(
        account=MetaAccountHealth(marketplace_access=MetaAccessState.UNKNOWN),
        commerce=MetaCommerceHealth(state=MetaCommerceState.UNKNOWN),
    )

    assert result.decision == ComplianceDecision.WARNING
    assert result.blocked_channels == ()
    snapshot = result.as_dict()
    assert snapshot["decision"] == "WARNING"
    assert snapshot["policy_version"]
