from cfh_disposition.facebook_group_import import (
    apply_group_import,
    csv_template,
    parse_csv_groups,
    parse_pasted_groups,
)
from cfh_disposition.facebook_groups import FacebookGroupLedger, upsert_group


def test_pasted_pipe_rows_add_multiple_groups() -> None:
    rows = parse_pasted_groups(
        "\n".join(
            [
                "Group One | https://www.facebook.com/groups/111 | 7 | Mondays only",
                "Group Two | https://www.facebook.com/groups/222 | 3",
            ]
        ),
        FacebookGroupLedger(),
    )

    assert [row.action for row in rows] == ["Add", "Add"]
    assert rows[0].cooldown_days == 7
    assert rows[0].notes == "Mondays only"
    assert rows[1].cooldown_days == 3

    result = apply_group_import(FacebookGroupLedger(), rows)
    assert result.added == 2
    assert result.updated == 0
    assert result.skipped == 0
    assert len(result.ledger.groups) == 2


def test_url_only_row_gets_temporary_name() -> None:
    rows = parse_pasted_groups(
        "https://www.facebook.com/groups/1305510733671893",
        FacebookGroupLedger(),
    )

    assert rows[0].action == "Add"
    assert rows[0].name == "Facebook Group 1305510733671893"


def test_existing_url_is_updated_instead_of_duplicated() -> None:
    ledger = upsert_group(
        FacebookGroupLedger(),
        name="Old Group Name",
        group_url="https://www.facebook.com/groups/111",
        cooldown_days=7,
    )
    rows = parse_pasted_groups(
        "New Group Name | https://www.facebook.com/groups/111 | 14 | New rules",
        ledger,
    )

    assert rows[0].action == "Update"
    assert rows[0].existing_group_id == ledger.groups[0].group_id

    result = apply_group_import(ledger, rows)
    assert result.added == 0
    assert result.updated == 1
    assert len(result.ledger.groups) == 1
    assert result.ledger.groups[0].name == "New Group Name"
    assert result.ledger.groups[0].cooldown_days == 14


def test_duplicate_rows_inside_same_batch_are_skipped() -> None:
    rows = parse_pasted_groups(
        "\n".join(
            [
                "Group One | https://www.facebook.com/groups/111",
                "Group One Again | https://www.facebook.com/groups/111",
            ]
        ),
        FacebookGroupLedger(),
    )

    assert rows[0].action == "Add"
    assert rows[1].action == "Skip"
    assert "Duplicate Facebook URL" in rows[1].issue


def test_invalid_non_facebook_url_is_skipped() -> None:
    rows = parse_pasted_groups(
        "Bad Group | https://example.com/groups/111",
        FacebookGroupLedger(),
    )

    assert rows[0].action == "Skip"
    assert "facebook.com" in rows[0].issue.lower()


def test_csv_alias_columns_and_template() -> None:
    content = (
        "name,url,cooldown,rules\n"
        "Group One,https://www.facebook.com/groups/111,5,No links on Sunday\n"
    )
    rows = parse_csv_groups(content, FacebookGroupLedger())

    assert rows[0].action == "Add"
    assert rows[0].name == "Group One"
    assert rows[0].cooldown_days == 5
    assert rows[0].notes == "No links on Sunday"
    assert b"group_name,group_url,cooldown_days,notes" in csv_template()


def test_bad_cooldown_is_skipped_without_crashing() -> None:
    rows = parse_pasted_groups(
        "Group One | https://www.facebook.com/groups/111 | 999",
        FacebookGroupLedger(),
    )

    assert rows[0].action == "Skip"
    assert "between 1 and 90" in rows[0].issue
