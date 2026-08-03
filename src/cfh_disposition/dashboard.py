from __future__ import annotations

from dataclasses import dataclass

from .launch_plan import build_launch_plan
from .matching import match_buyer_to_property
from .models import BuyerProfile, OwnerFinanceProperty, PropertyStatus


@dataclass(frozen=True, slots=True)
class DashboardMetrics:
    total_properties: int
    launch_ready: int
    live_properties: int
    needs_information: int
    total_buyers: int
    eligible_matches: int


def calculate_dashboard_metrics(
    properties: list[OwnerFinanceProperty], buyers: list[BuyerProfile]
) -> DashboardMetrics:
    eligible_matches = 0
    for property_record in properties:
        for buyer in buyers:
            if match_buyer_to_property(buyer, property_record).is_eligible:
                eligible_matches += 1

    return DashboardMetrics(
        total_properties=len(properties),
        launch_ready=sum(build_launch_plan(item).can_launch for item in properties),
        live_properties=sum(item.status == PropertyStatus.LIVE for item in properties),
        needs_information=sum(not build_launch_plan(item).can_launch for item in properties),
        total_buyers=len(buyers),
        eligible_matches=eligible_matches,
    )
