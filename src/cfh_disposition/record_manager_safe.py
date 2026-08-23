from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import streamlit as st
from pydantic import ValidationError

from .launch_plan import build_launch_plan
from .models import BuyerProfile, CommunicationPreference, OwnerFinanceProperty, PropertyStatus
from .storage import Storage, StorageError


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", "").replace("$", "").strip())


def _decimal_text(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def _load_state(storage: Storage) -> None:
    if "properties" not in st.session_state:
        st.session_state.properties = storage.list_properties()
    if "buyers" not in st.session_state:
        st.session_state.buyers = storage.list_buyers()


def _replace_property(record: OwnerFinanceProperty) -> None:
    current = {str(item.property_id): item for item in st.session_state.properties}
    current[str(record.property_id)] = record
    st.session_state.properties = list(current.values())


def _replace_buyer(record: BuyerProfile) -> None:
    current = {str(item.buyer_id): item for item in st.session_state.buyers}
    current[str(record.buyer_id)] = record
    st.session_state.buyers = list(current.values())


def _render_properties(storage: Storage) -> None:
    st.write("### Properties")
    options = {
        f"{item.display_address or 'Unnamed property'} — {str(item.property_id)[:8]}": item
        for item in st.session_state.properties
    }
    if not options:
        st.info("No properties are saved yet.")
        return

    selected_name = st.selectbox("Choose a property to manage", list(options), key="safe_record_property")
    selected = options[selected_name]
    plan = build_launch_plan(selected)
    if plan.can_launch:
        st.success("This property currently passes the launch-readiness gate.")
    else:
        st.warning(f"This property has {len(plan.validation.errors)} blocking issue(s).")

    st.write("#### Property photos")
    existing_urls = [str(item) for item in selected.photo_urls]
    if existing_urls:
        st.write(f"**Saved photos: {len(existing_urls)}**")
        columns = st.columns(3)
        for index, url in enumerate(existing_urls):
            with columns[index % 3]:
                st.image(url, caption=f"Photo {index + 1}", use_container_width=True)
    else:
        st.info("No property photos are saved yet.")

    uploaded_files = st.file_uploader(
        "Choose property photos",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key=f"safe_property_photos_{selected.property_id}",
    )
    if st.button(
        "Upload Selected Photos",
        disabled=not uploaded_files or not storage.supports_photo_uploads,
        key=f"safe_upload_photos_{selected.property_id}",
    ):
        try:
            files = [(item.name, item.getvalue(), item.type or "") for item in uploaded_files]
            new_urls = storage.upload_property_photos(selected.property_id, files)
            data = selected.model_dump(mode="python")
            data["photo_urls"] = existing_urls + [url for url in new_urls if url not in existing_urls]
            data["updated_at"] = datetime.now(UTC)
            record = OwnerFinanceProperty.model_validate(data)
            storage.save_property(record)
            _replace_property(record)
            st.session_state.record_manager_message = f"{len(new_urls)} property photo(s) uploaded."
            st.rerun()
        except (ValidationError, StorageError) as exc:
            st.error(str(exc))

    st.divider()
    st.write("#### Central property truth")
    st.info("This is the only place to change locked marketing facts. Downstream marketing must read from this record.")

    with st.form("safe_edit_property_form"):
        left, middle, right = st.columns(3)
        address = left.text_input("Street address*", value=selected.address)
        city = middle.text_input("City*", value=selected.city)
        state = right.text_input("State abbreviation*", value=selected.state, max_chars=2)
        zip_code = left.text_input("ZIP code*", value=selected.zip_code)
        county = middle.text_input("County", value=selected.county)
        bedrooms = right.number_input("Bedrooms*", min_value=0, max_value=20, value=selected.bedrooms or 0)
        bathrooms = left.number_input("Bathrooms*", min_value=0.0, max_value=20.0, value=float(selected.bathrooms or 0), step=0.5)
        total_price = middle.text_input("Total price*", value=_decimal_text(selected.total_price))
        down_payment = right.text_input("Down payment*", value=_decimal_text(selected.down_payment))
        monthly_payment = left.text_input("Monthly payment*", value=_decimal_text(selected.monthly_payment))
        statuses = list(PropertyStatus)
        status = middle.selectbox("Status", statuses, index=statuses.index(selected.status), format_func=lambda item: item.value)
        available_date = right.text_input("Available date", value=selected.available_date)
        condition = st.text_area("Condition summary*", value=selected.condition_summary)
        repairs = st.text_area("Known repairs needed", value=selected.repairs_needed)
        showing = st.text_area("Showing instructions*", value=selected.showing_instructions)
        disclosures = st.text_area("Public disclosures*", value=selected.public_disclosures)
        application_url = st.text_input("Application URL", value=str(selected.application_url) if selected.application_url else "")
        submitted = st.form_submit_button("Save Property Changes", type="primary")

    if submitted:
        try:
            data = selected.model_dump(mode="python")
            data.update(
                {
                    "status": status,
                    "address": address,
                    "city": city,
                    "state": state,
                    "zip_code": zip_code,
                    "county": county,
                    "bedrooms": bedrooms,
                    "bathrooms": Decimal(str(bathrooms)),
                    "total_price": _decimal(total_price),
                    "down_payment": _decimal(down_payment),
                    "monthly_payment": _decimal(monthly_payment),
                    "available_date": available_date,
                    "condition_summary": condition,
                    "repairs_needed": repairs,
                    "showing_instructions": showing,
                    "public_disclosures": disclosures,
                    "application_url": application_url or None,
                    "updated_at": datetime.now(UTC),
                }
            )
            record = OwnerFinanceProperty.model_validate(data)
            storage.save_property(record)
            _replace_property(record)
            st.session_state.record_manager_message = "Property changes saved."
            st.rerun()
        except (ValidationError, InvalidOperation, StorageError) as exc:
            st.error(f"Property could not be updated: {exc}")


def _render_add_buyer(storage: Storage) -> None:
    st.write("#### Add buyer for marketing outreach")
    st.caption("Use a real contact only. Consent must reflect what the person actually authorized.")
    with st.form("safe_add_buyer_form", clear_on_submit=True):
        left, right = st.columns(2)
        first_name = left.text_input("First name*")
        last_name = right.text_input("Last name")
        phone = left.text_input("Phone*")
        source = right.text_input("Buyer source", value="CFH marketing")
        sms_consent = left.checkbox("SMS consent confirmed")
        do_not_contact = right.checkbox("Do not contact")
        st.info("For the controlled Zapier test, use a phone number you control and check SMS consent only if you authorize this test message.")
        submitted = st.form_submit_button("Save Buyer", type="primary")

    if not submitted:
        return
    if not first_name.strip() or not phone.strip():
        st.error("First name and phone are required.")
        return
    if do_not_contact and sms_consent:
        st.error("A Do Not Contact buyer cannot also be SMS-consented.")
        return

    try:
        record = BuyerProfile(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            phone=phone.strip(),
            communication_preference=CommunicationPreference.SMS if sms_consent else CommunicationPreference.ANY,
            sms_consent=sms_consent,
            do_not_contact=do_not_contact,
            source=source.strip() or "CFH marketing",
        )
        storage.save_buyer(record)
        _replace_buyer(record)
        st.session_state.record_manager_message = "Buyer saved. SMS still requires saved consent and active contact status before handoff."
        st.rerun()
    except (ValidationError, StorageError) as exc:
        st.error(f"Buyer could not be saved: {exc}")


def _render_buyers(storage: Storage) -> None:
    st.write("### Buyers")
    _render_add_buyer(storage)
    st.divider()

    options = {}
    for item in st.session_state.buyers:
        name = f"{item.first_name} {item.last_name}".strip() or "Unnamed buyer"
        contact = item.email or item.phone or "No contact"
        options[f"{name} — {contact} — {str(item.buyer_id)[:8]}"] = item

    if not options:
        st.info("No buyers are saved yet. Add the first buyer above.")
        return

    selected_name = st.selectbox("Choose a buyer to edit", list(options), key="safe_record_buyer")
    selected = options[selected_name]
    with st.form("safe_edit_buyer_form"):
        left, right = st.columns(2)
        first_name = left.text_input("First name*", value=selected.first_name)
        last_name = right.text_input("Last name", value=selected.last_name)
        phone = left.text_input("Phone", value=selected.phone)
        source = right.text_input("Buyer source", value=selected.source)
        sms_consent = left.checkbox("SMS consent", value=selected.sms_consent)
        do_not_contact = right.checkbox("Do not contact", value=selected.do_not_contact)
        submitted = st.form_submit_button("Save Buyer Changes", type="primary")

    if submitted:
        if do_not_contact and sms_consent:
            st.error("A Do Not Contact buyer cannot also be SMS-consented.")
            return
        try:
            data = selected.model_dump(mode="python")
            data.update(
                {
                    "first_name": first_name,
                    "last_name": last_name,
                    "phone": phone,
                    "source": source,
                    "sms_consent": sms_consent,
                    "do_not_contact": do_not_contact,
                    "communication_preference": CommunicationPreference.SMS if sms_consent else selected.communication_preference,
                }
            )
            record = BuyerProfile.model_validate(data)
            storage.save_buyer(record)
            _replace_buyer(record)
            st.session_state.record_manager_message = "Buyer changes saved."
            st.rerun()
        except (ValidationError, StorageError) as exc:
            st.error(f"Buyer could not be updated: {exc}")


def render_record_manager(storage: Storage) -> None:
    _load_state(storage)
    st.subheader("Edit, Add Photos, or Delete Saved Records")
    message = st.session_state.pop("record_manager_message", "")
    if message:
        st.success(message)

    property_tab, buyer_tab = st.tabs(["Properties", "Buyers"])
    with property_tab:
        _render_properties(storage)
    with buyer_tab:
        _render_buyers(storage)
