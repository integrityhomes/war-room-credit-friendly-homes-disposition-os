from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channels import CHANNELS
from cfh_disposition.dwelyx_attribution import (
    DwelyxAttributionError,
    DwelyxAttributionEvent,
    DwelyxAttributionStore,
    DwelyxEventType,
    attribution_rows,
    build_campaign_attribution,
    build_channel_attribution,
    build_dwelyx_delivery,
    build_funnel,
    build_journeys,
    build_property_attribution,
    event_rows,
    journey_rows,
    parse_signed_dwelyx_event,
    receiver_endpoint,
)
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Dwelyx Results Tracking & Attribution Center",
    page_icon="🔄",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Dwelyx Results Tracking & Attribution Center")
    st.caption("Private internal access")
    with st.form("dwelyx_attribution_login"):
        submitted_password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(submitted_password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


@st.cache_resource
def get_property_storage():
    return build_storage(st.secrets, SAMPLE_PROPERTIES, SAMPLE_BUYERS)


def property_labels(properties, secrets=None) -> dict[str, str]:
    labels = {
        str(item.property_id): item.display_address or str(item.property_id)
        for item in properties
    }
    if secrets is not None:
        overrides = secrets.get("DWELYX_PROPERTY_ADDRESSES", {})
        try:
            override_items = overrides.items()
        except AttributeError:
            override_items = ()
        for property_id, address in override_items:
            clean_id = str(property_id or "").strip()
            clean_address = str(address or "").strip()
            if clean_id and clean_address:
                labels[clean_id] = clean_address
    return labels


def filtered_events(events, days: int, include_tests: bool):
    cutoff = datetime.now(UTC) - timedelta(days=days)
    return [
        event
        for event in events
        if event.occurred_at >= cutoff and (include_tests or not event.test_mode)
    ]


def top_channel_name(channel_rows) -> str:
    active = [row for row in channel_rows if row.registrations]
    if not active:
        return "No results yet"
    winner = max(
        active,
        key=lambda row: (
            row.filled,
            row.contracts,
            row.applications,
            row.registrations,
        ),
    )
    return winner.name


def compact_id(value: str, *, prefix: int = 8, suffix: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return "Unassigned"
    if len(text) <= prefix + suffix + 3:
        return text
    return f"{text[:prefix]}…{text[-suffix:]}"


def local_timestamp(value: datetime) -> str:
    return value.astimezone().strftime("%b %d, %Y • %I:%M %p")


require_password()
st.title("Dwelyx Results Tracking & Attribution Center")
st.caption(
    "Shows which marketing channels produce Dwelyx registrations, applications, showings, contracts, and filled homes."
)
st.info(
    "Dwelyx remains the buyer system of record. This center stores Dwelyx IDs and attribution events only—not buyer names, emails, phone numbers, applications, documents, or financial information."
)

try:
    attribution_store = DwelyxAttributionStore(st.secrets)
    all_events = attribution_store.list_events()
    properties = get_property_storage().list_properties()
except (DwelyxAttributionError, StorageError) as exc:
    st.error(f"Dwelyx attribution is safety-locked: {exc}")
    st.stop()

labels = property_labels(properties, st.secrets)
results_tab, journeys_tab, test_tab, connection_tab = st.tabs(
    [
        "Results Dashboard",
        "Dwelyx Journey Inbox",
        "Signed Test Event",
        "Connection Setup",
    ]
)

with results_tab:
    left, right = st.columns(2)
    days = left.selectbox(
        "Reporting window",
        [7, 30, 90, 365],
        index=1,
        format_func=lambda value: f"Last {value} days",
    )
    include_tests = right.checkbox("Include test events", value=False)
    events = filtered_events(all_events, days, include_tests)
    journeys = build_journeys(events)
    funnel = build_funnel(journeys)
    channels = build_channel_attribution(journeys)

    metrics = st.columns(6)
    metrics[0].metric("Registrations", funnel.registrations)
    metrics[1].metric("Applications", funnel.applications_submitted)
    metrics[2].metric("Showings", funnel.showings_scheduled)
    metrics[3].metric("Contracts", funnel.contracts_signed)
    metrics[4].metric("Filled Homes", funnel.filled)
    metrics[5].metric("Top Channel", top_channel_name(channels))

    rates = st.columns(3)
    rates[0].metric("Registration → Application", f"{funnel.registration_to_application_rate:.1%}")
    rates[1].metric("Application → Contract", f"{funnel.application_to_contract_rate:.1%}")
    rates[2].metric("Contract → Filled", f"{funnel.contract_to_filled_rate:.1%}")

    st.write("### All 15 marketing channels")
    channel_frame = pd.DataFrame(attribution_rows(channels))
    st.dataframe(
        channel_frame,
        use_container_width=True,
        hide_index=True,
        height=max(420, len(channels) * 35 + 45),
    )
    st.download_button(
        "Download Channel Results",
        channel_frame.to_csv(index=False).encode("utf-8"),
        "dwelyx-channel-results.csv",
        "text/csv",
    )

    campaign_tab, property_tab, event_tab = st.tabs(
        ["Campaign Results", "Property Results", "Event History"]
    )
    with campaign_tab:
        campaign_frame = pd.DataFrame(
            attribution_rows(build_campaign_attribution(journeys))
        )
        if campaign_frame.empty:
            st.info("No Dwelyx campaign results have arrived in this reporting window.")
        else:
            st.dataframe(campaign_frame, use_container_width=True, hide_index=True)
    with property_tab:
        property_results = build_property_attribution(journeys)
        rows = attribution_rows(property_results)
        for row, result in zip(rows, property_results, strict=True):
            row["Source"] = labels.get(result.key, result.name)
        property_frame = pd.DataFrame(rows)
        if property_frame.empty:
            st.info("No property-specific Dwelyx results have arrived yet.")
        else:
            st.dataframe(property_frame, use_container_width=True, hide_index=True)
    with event_tab:
        history_frame = pd.DataFrame(event_rows(events, labels))
        if history_frame.empty:
            st.info("No Dwelyx events have arrived in this reporting window.")
        else:
            st.dataframe(history_frame, use_container_width=True, hide_index=True)
            st.download_button(
                "Download Event History",
                history_frame.to_csv(index=False).encode("utf-8"),
                "dwelyx-attribution-events.csv",
                "text/csv",
            )

with journeys_tab:
    include_test_journeys = st.checkbox(
        "Include test journeys",
        value=False,
        key="include_test_journeys",
    )
    journey_events = [
        event for event in all_events if include_test_journeys or not event.test_mode
    ]
    journeys = build_journeys(journey_events)
    if not journeys:
        st.info(
            "No Dwelyx journeys have arrived yet. The dashboard will populate after the receiver accepts events from Dwelyx."
        )
    else:
        journey_frame = pd.DataFrame(journey_rows(journeys, labels))
        st.dataframe(
            journey_frame,
            use_container_width=True,
            hide_index=True,
            height=520,
        )
        journey_options = {
            (
                f"{compact_id(item.dwelyx_buyer_id)} • "
                f"{labels.get(item.cfh_property_id or item.dwelyx_property_id, compact_id(item.cfh_property_id or item.dwelyx_property_id))} • "
                f"{item.stage.value}"
            ): item
            for item in journeys
        }
        selected_label = st.selectbox(
            "Open one pseudonymous Dwelyx journey",
            list(journey_options),
        )
        selected = journey_options[selected_label]
        property_id = selected.cfh_property_id or selected.dwelyx_property_id
        property_name = labels.get(property_id, "")
        property_display = property_name or "Address not linked"

        st.write("### Buyer Journey Detail")
        with st.container(border=True):
            primary = st.columns(3)
            primary[0].write("**Stage**")
            primary[0].write(selected.stage.value)
            primary[1].write("**Property Address**")
            primary[1].write(property_display)
            primary[2].write("**Requested / Latest Activity**")
            primary[2].write(local_timestamp(selected.latest_event_at))

            attribution = st.columns(3)
            attribution[0].write("**Marketing Channel**")
            attribution[0].write(selected.channel_name)
            attribution[1].write("**Campaign**")
            attribution[1].write(selected.campaign or "Not specified")
            attribution[2].write("**Events in Journey**")
            attribution[2].write(str(selected.event_count))

            identity = st.columns(2)
            identity[0].write("**Dwelyx Buyer ID**")
            identity[0].code(selected.dwelyx_buyer_id, language=None)
            identity[1].write("**Property ID**")
            identity[1].code(property_id or "Unassigned", language=None)

            st.caption(
                f"Journey first seen {local_timestamp(selected.first_event_at)}. "
                "This center is for marketing attribution and funnel tracking; Dwelyx remains the system of record for buyer and showing details."
            )

        if selected.dwelyx_record_url:
            st.link_button(
                "Open This Journey in Dwelyx",
                selected.dwelyx_record_url,
                type="primary",
            )
        else:
            st.caption(
                "Dwelyx did not include a permitted deep link for this journey. Use the Dwelyx buyer ID to locate it inside Dwelyx."
            )

with test_tab:
    st.write("### Send one signed test event through the same contract")
    st.caption(
        "Test events are marked separately and excluded from normal business results unless you choose to include them."
    )
    secret = str(st.secrets.get("DWELYX_WEBHOOK_SECRET", "")).strip()
    if not secret:
        st.warning(
            "Add DWELYX_WEBHOOK_SECRET to Streamlit Secrets before testing the signed event contract."
        )
    property_options = {"No property — registration only": ""}
    property_options.update({label: property_id for property_id, label in labels.items()})
    with st.form("signed_dwelyx_test_event"):
        event_type = st.selectbox(
            "Dwelyx event",
            list(DwelyxEventType),
            format_func=lambda value: value.value,
        )
        selected_property_label = st.selectbox(
            "Credit Friendly Homes property",
            list(property_options),
        )
        cfh_property_id = property_options[selected_property_label]
        dwelyx_buyer_id = st.text_input(
            "Test Dwelyx buyer ID",
            value=f"test-buyer-{uuid4().hex[:10]}",
        )
        dwelyx_property_id = st.text_input(
            "Dwelyx property ID — optional",
            value="",
        )
        source = st.text_input("Source", value="credit_friendly_homes")
        medium = st.selectbox(
            "Marketing channel",
            [channel.key for channel in CHANNELS],
            format_func=lambda key: next(
                channel.name for channel in CHANNELS if channel.key == key
            ),
        )
        campaign = st.text_input("Campaign", value="signed_receiver_test")
        dwelyx_record_url = st.text_input(
            "Dwelyx deep link — optional",
            value="",
            placeholder="https://app.dwelyx.com/admin/buyers/test-buyer-id",
        )
        event_id = st.text_input(
            "Event ID",
            value=f"test-event-{uuid4().hex}",
        )
        submit_test = st.form_submit_button(
            "Validate Signature and Store Test Event",
            type="primary",
            disabled=not bool(secret),
        )
    if submit_test:
        try:
            event = DwelyxAttributionEvent(
                event_id=event_id,
                event_type=event_type,
                occurred_at=datetime.now(UTC),
                dwelyx_buyer_id=dwelyx_buyer_id,
                dwelyx_property_id=dwelyx_property_id,
                cfh_property_id=cfh_property_id,
                source=source,
                medium=medium,
                campaign=campaign,
                dwelyx_record_url=dwelyx_record_url,
                test_mode=True,
            )
            body, headers = build_dwelyx_delivery(event, secret)
            verified = parse_signed_dwelyx_event(
                body,
                headers,
                secret,
                now=datetime.now(UTC),
            )
            created = attribution_store.record(verified)
            if created:
                st.success(
                    "The signed test event passed privacy, signature, replay, and contract validation and was stored."
                )
            else:
                st.info("That event ID was already received, so the duplicate was ignored.")
            st.rerun()
        except (DwelyxAttributionError, ValueError) as exc:
            st.error(str(exc))

with connection_tab:
    st.write("### Dwelyx connection status")
    secret_configured = bool(
        str(st.secrets.get("DWELYX_WEBHOOK_SECRET", "")).strip()
    )
    endpoint = receiver_endpoint(st.secrets)
    production_events = [event for event in all_events if not event.test_mode]
    latest_event = max(
        (event.occurred_at for event in production_events),
        default=None,
    )
    status = st.columns(3)
    status[0].metric(
        "Shared Secret",
        "Configured" if secret_configured else "Missing",
    )
    status[1].metric(
        "Receiver Endpoint",
        "Ready to Deploy" if endpoint else "Missing Supabase URL",
    )
    status[2].metric(
        "Live Dwelyx Events",
        latest_event.astimezone().strftime("%Y-%m-%d %I:%M %p")
        if latest_event
        else "None received yet",
    )

    st.write("#### Receiver URL")
    st.code(endpoint or "Add SUPABASE_URL or DWELYX_RESULTS_ENDPOINT")
    st.write("#### Required secrets")
    st.code(
        'DWELYX_WEBHOOK_SECRET = "use-a-long-random-shared-secret"\n'
        '# Optional override after deploying the receiver:\n'
        'DWELYX_RESULTS_ENDPOINT = "https://your-project.supabase.co/functions/v1/dwelyx-results"\n\n'
        '# Optional address labels for Dwelyx-only property IDs:\n'
        '[DWELYX_PROPERTY_ADDRESSES]\n'
        '"dwelyx-property-uuid" = "123 Main St, Decatur, IL 62521"'
    )
    st.warning(
        "The receiver source is included in this repository, but it is not live until the Supabase Edge Function is deployed. The separate Dwelyx repository must then send signed events to this URL."
    )

    st.write("#### Event body Dwelyx will send")
    st.code(
        """{
  "schema_version": "1.0",
  "event_id": "evt_12345678",
  "event_type": "application.submitted",
  "occurred_at": "2026-08-05T20:00:00Z",
  "dwelyx_buyer_id": "buyer_abc123",
  "dwelyx_property_id": "dwelyx_property_456",
  "cfh_property_id": "credit_friendly_homes_property_uuid",
  "source": "credit_friendly_homes",
  "medium": "nextdoor",
  "campaign": "saltville_august_2026",
  "dwelyx_record_url": "https://app.dwelyx.com/admin/buyers/buyer_abc123",
  "test_mode": false
}""",
        language="json",
    )
    st.write("#### Required signed headers")
    st.code(
        "X-Dwelyx-Event-Id: evt_12345678\n"
        "X-Dwelyx-Timestamp: Unix timestamp\n"
        "X-Dwelyx-Signature: sha256=HMAC(timestamp + '.' + exact JSON body)"
    )
    st.success(
        "Connecting the other Dwelyx GitHub repository later will only require adding its event sender and deploying this receiver with the matching shared secret."
    )