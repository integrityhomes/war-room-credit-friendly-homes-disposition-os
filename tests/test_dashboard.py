from cfh_disposition.dashboard import calculate_dashboard_metrics
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES


def test_dashboard_counts_sample_data() -> None:
    metrics = calculate_dashboard_metrics(SAMPLE_PROPERTIES, SAMPLE_BUYERS)
    assert metrics.total_properties == 2
    assert metrics.total_buyers == 2
    assert metrics.launch_ready == 1
    assert metrics.needs_information == 1
