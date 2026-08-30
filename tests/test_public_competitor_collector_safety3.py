import pytest

from cfh_disposition.public_competitor_collector import PublicCompetitorCollectionError, collect_public_competitor_page


def test_rejects_invalid_url_before_network() -> None:
    with pytest.raises(PublicCompetitorCollectionError, match="valid public"):
        collect_public_competitor_page(url="file:///tmp/test", market="Decatur, IL", source_name="Example")
