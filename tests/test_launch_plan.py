from cfh_disposition.channels import CHANNELS
from cfh_disposition.launch_plan import LaunchState, build_launch_plan
from cfh_disposition.sample_data import SAMPLE_PROPERTIES


def test_ready_property_has_one_item_per_channel() -> None:
    plan = build_launch_plan(SAMPLE_PROPERTIES[0])
    assert plan.can_launch
    assert len(plan.items) == len(CHANNELS)


def test_incomplete_property_blocks_every_channel() -> None:
    plan = build_launch_plan(SAMPLE_PROPERTIES[1])
    assert not plan.can_launch
    assert all(item.state == LaunchState.BLOCKED for item in plan.items)


def test_ready_plan_contains_assisted_tasks() -> None:
    plan = build_launch_plan(SAMPLE_PROPERTIES[0])
    assert any(item.state == LaunchState.ASSISTED_TASK for item in plan.items)
