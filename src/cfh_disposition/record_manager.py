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


def _property_options(properties: list[OwnerFinanceProperty]) -> dict[str, OwnerFinanceProperty]:
    return {f"{item.display_address or 'Unnamed property'} — {str(item.property_id)[:8]}": item for item in properties}


def _buyer_options(buyers: list[BuyerProfile]) -> dict[str, BuyerProfile]:
    options: dict[str, BuyerProfile] = {}
    for item in buyers:
        name = f"{item.first_name} {item.last_name}".strip() or "Unnamed buyer"
        contact = item.email or item.phone or "No contact"
        options[f"{name} — {contact} — {str(item.buyer_id)[:8]}"] = item
    return options


def _ensure_record_manager_state(storage: Storage) -> None:
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


def _property_with_photos(selected: OwnerFinanceProperty, photo_urls: list[str]) -> OwnerFinanceProperty:
    data = selected.model_dump(mode="python")
    data.update({"photo_urls": photo_urls, "updated_at": datetime.now(UTC)})
    record = OwnerFinanceProperty.model_validate(data)
    if selected.status in {PropertyStatus.DRAFT, PropertyStatus.NEEDS_INFORMATION, PropertyStatus.READY}:
        record.status = PropertyStatus.READY if build_launch_plan(record).can_launch else PropertyStatus.NEEDS_INFORMATION
    return record


def _render_property_photos(storage: Storage, selected: OwnerFinanceProperty) -> None:
    st.write("#### Property photos")
    st.caption("Upload JPG, PNG, or WEBP photos. Each photo may be up to 10 MB.")
    st.info("Uploaded property photos are public marketing assets. Do not upload IDs, contracts, applications, or private documents.")
    uploaded_files = st.file_uploader("Choose property photos", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key=f"property_photos_{selected.property_id}")
    upload_disabled = not uploaded_files or not storage.supports_photo_uploads
    if not storage.supports_photo_uploads:
        st.warning("Connect Supabase before uploading property photos.")
    if st.button("Upload Selected Photos", type="primary", disabled=upload_disabled, key=f"upload_property_photos_{selected.property_id}"):
        try:
            files = [(item.name, item.getvalue(), item.type or "") for item in uploaded_files]
            new_urls = storage.upload_property_photos(selected.property_id, files)
            combined_urls = [str(item) for item in selected.photo_urls]
            combined_urls.extend(url for url in new_urls if url not in combined_urls)
            record = _property_with_photos(selected, combined_urls)
            storage.save_property(record)
            _replace_property(record)
            st.session_state.record_manager_message = f"{len(new_urls)} property photo(s) uploaded."
            st.rerun()
        except (ValidationError, StorageError) as exc:
            st.error(str(exc))
    existing_urls = [str(item) for item in selected.photo_urls]
    if not existing_urls:
        st.info("No property photos are saved yet.")
        return
    st.write(f"**Saved photos: {len(existing_urls)}**")
    columns = st.columns(3)
    for index, url in enumerate(existing_urls):
        with columns[index % 3]:
            st.image(url, caption=f"Photo {index + 1}", use_container_width=True)
    remove_options = {f"Photo {index + 1}": url for index, url in enumerate(existing_urls)}
    selected_labels = st.multiselect("Choose photos to remove", list(remove_options), key=f"remove_property_photos_{selected.property_id}")
    if st.button("Remove Selected Photos", disabled=not selected_labels, key=f"remove_selected_photos_{selected.property_id}"):
        try:
            urls_to_remove = [remove_options[label] for label in selected_labels]
            for url in urls_to_remove:
                storage.delete_property_photo(url)
            remaining_urls = [url for url in existing_urls if url not in urls_to_remove]
            record = _property_with_photos(selected, remaining_urls)
            storage.save_property(record)
            _replace_property(record)
            st.session_state.record_manager_message = f"{len(urls_to_remove)} property photo(s) removed."
            st.rerun()
        except (ValidationError, StorageError) as exc:
            st.error(str(exc))


def _render_property_manager(storage: Storage) -> None:
    st.write("### Properties")
    options = _property_options(st.session_state.properties)
    if not options:
        st.info("No properties are saved yet.")
        return
    selected_name = st.selectbox("Choose a property to manage", list(options), key="record_property")
    selected = options[selected_name]
    plan = build_launch_plan(selected)
    if plan.can_launch:
        st.success("This property currently passes the launch-readiness gate.")
    else:
        st.warning(f"This property has {len(plan.validation.errors)} blocking issue(s).")
    _render_property_photos(storage, selected)
    st.divider()
    st.write("#### Central property truth")
    st.info("This is the only place to change locked marketing facts. Price, down payment, monthly payment, bedrooms, and availability flow from here into landing pages and marketing packages.")
    with st.form("edit_property_form"):
        left, middle, right = st.columns(3)
        address = left.text_input("Street address*", value=selected.address)
        city = middle.text_input("City*", value=selected.city)
        state = right.text_input("State abbreviation*", value=selected.state, max_chars=2)
        zip_code = left.text_input("ZIP code*", value=selected.zip_code)
        county = middle.text_input("County", value=selected.county)
        bedrooms = right.number_input("Bedrooms*", min_value=0, max_value=20, value=selected.bedrooms if selected.bedrooms is not None else 0)
        bathrooms = left.number_input("Bathrooms*", min_value=0.0, max_value=20.0, value=float(selected.bathrooms or 0), step=0.5)
        total_price = middle.text_input("Total price*", value=_decimal_text(selected.total_price))
        down_payment = right.text_input("Down payment*", value=_decimal_text(selected.down_payment))
        monthly_payment = left.text_input("Monthly payment*", value=_decimal_text(selected.monthly_payment))
        available_date = right.text_input("Available date", value=selected.available_date, help="Use a clear date or wording such as Available now. Downstream marketing reads this field; it does not maintain a separate availability value.")
        statuses = list(PropertyStatus)
        status = middle.selectbox("Status", statuses, index=statuses.index(selected.status), format_func=lambda item: item.value)
        condition = st.text_area("Condition summary*", value=selected.condition_summary)
        repairs = st.text_area("Known repairs needed", value=selected.repairs_needed)
        showing = st.text_area("Showing instructions*", value=selected.showing_instructions)
        disclosures = st.text_area("Public disclosures*", value=selected.public_disclosures)
        photo_text = st.text_area("Photo URLs — one per line", value="\n".join(str(item) for item in selected.photo_urls), help="Direct uploads are preferred. This field also supports existing external photo URLs.")
        application_url = st.text_input("Application URL", value=str(selected.application_url) if selected.application_url else "")
        submitted = st.form_submit_button("Save Property Changes", type="primary")
    if submitted:
        try:
            data = selected.model_dump(mode="python")
            data.update({"status": status, "address": address, "city": city, "state": state, "zip_code": zip_code, "county": county, "bedrooms": bedrooms, "bathrooms": Decimal(str(bathrooms)), "total_price": _decimal(total_price), "down_payment": _decimal(down_payment), "monthly_payment": _decimal(monthly_payment), "available_date": available_date, "condition_summary": condition, "repairs_needed": repairs, "showing_instructions": showing, "public_disclosures": disclosures, "photo_urls": [line.strip() for line in photo_text.splitlines() if line.strip()], "application_url": application_url or None, "updated_at": datetime.now(UTC)})
            record = OwnerFinanceProperty.model_validate(data)
            storage.save_property(record)
            _replace_property(record)
            st.session_state.record_manager_message = "Property changes saved. Downstream marketing must regenerate from these facts."
            st.rerun()
        except (ValidationError, InvalidOperation, StorageError) as exc:
            st.error(f"Property could not be updated: {exc}")
    st.write("#### Delete property")
    st.caption("Deletion permanently removes this record and its uploaded photos from Supabase.")
    confirmed = st.checkbox("I understand this property will be permanently deleted.", key=f"confirm_property_{selected.property_id}")
    if st.button("Delete Property", type="secondary", disabled=not confirmed):
        try:
            storage.delete_property(selected.property_id)
            st.session_state.properties = [item for item in st.session_state.properties if item.property_id != selected.property_id]
            st.session_state.record_manager_message = "Property deleted."
            st.rerun()
        except StorageError as exc:
            st.error(str(exc))


def _render_add_buyer(storage: Storage) -> None:
    st.write("#### Add buyer for marketing outreach")
    st.caption("Use this only for a real buyer/contact. Consent must reflect what the person actually authorized.")
    with st.form("add_buyer_form", clear_on_submit=True):
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
        st.error("A Do Not Contact buyer cannot simultaneously be marked as SMS-consented.")
        return
    try:
        record = BuyerProfile(first_name=first_name.strip(), last_name=last_name.strip(), phone=phone.strip(), communication_preference=CommunicationPreference.SMS if sms_consent else CommunicationPreference.ANY, sms_consent=sms_consent, do_not_contact=do_not_contact, source=source.strip() or "CFH marketing")
        storage.save_buyer(record)
        _replace_buyer(record)
        st.session_state.record_manager_message = "Buyer saved. Marketing channels will still enforce consent and Do Not Contact status before sending."
        st.rerun()
    except (ValidationError, StorageError) as exc:
        st.error(f"Buyer could not be saved: {exc}")


def _render_buyer_manager(storage: Storage) -> None:
    st.write("### Buyers")
    _render_add_buyer(storage)
    st.divider()
    options = _buyer_options(st.session_state.buyers)
    if not options:
        st.info("No buyers are saved yet. Add the first buyer above.")
        return
    selected_name = st.selectbox("Choose a buyer to edit or delete", list(options), key="record_buyer")
    selected = options[selected_name]
    with st.form("edit_buyer_form"):
        left, right = st.columns(2)
        first_name = left.text_input("First name*", value=selected.first_name)
        last_name = right.text_input("Last name", value=selected.last_name)
        email = left.text_input("Email", value=selected.email)
        phone = right.text_input("Phone", value=selected.phone)
        cities = left.text_input("Preferred cities — comma separated", value=", ".join(selected.preferred_cities))
        states = right.text_input("Preferred states — comma separated", value=", ".join(selected.preferred_states))
        minimum_bedrooms = left.number_input("Minimum bedrooms", min_value=0, max_value=20, value=selected.minimum_bedrooms if selected.minimum_bedrooms is not None else 0)
        maximum_payment = right.text_input("Maximum monthly payment", value=_decimal_text(selected.maximum_monthly_payment))
        available_down = left.text_input("Available down payment", value=_decimal_text(selected.available_down_payment))
        move_days = right.number_input("Move timeframe in days", min_value=0, max_value=3650, value=selected.move_timeframe_days if selected.move_timeframe_days is not None else 0)
        preferences = list(CommunicationPreference)
        preference = left.selectbox("Preferred contact", preferences, index=preferences.index(selected.communication_preference), format_func=lambda item: item.value)
        source = right.text_input("Buyer source", value=selected.source)
        email_consent = left.checkbox("Email consent", value=selected.email_consent)
        sms_consent = right.checkbox("SMS consent", value=selected.sms_consent)
        call_consent = left.checkbox("Call consent", value=selected.call_consent)
        do_not_contact = right.checkbox("Do not contact", value=selected.do_not_contact)
        submitted = st.form_submit_button("Save Buyer Changes", type="primary")
    if submitted:
        try:
            data = selected.model_dump(mode="python")
            data.update({"first_name": first_name, "last_name": last_name, "email": email, "phone": phone, "preferred_cities": [item.strip() for item in cities.split(",") if item.strip()], "preferred_states": [item.strip().upper() for item in states.split(",") if item.strip()], "minimum_bedrooms": minimum_bedrooms, "maximum_monthly_payment": _decimal(maximum_payment) if maximum_payment.strip() else None, "available_down_payment": _decimal(available_down) if available_down.strip() else None, "move_timeframe_days": move_days, "communication_preference": preference, "email_consent": email_consent, "sms_consent": sms_consent, "call_consent": call_consent, "do_not_contact": do_not_contact, "source": source})
            record = BuyerProfile.model_validate(data)
            storage.save_buyer(record)
            _replace_buyer(record)
            st.session_state.record_manager_message = "Buyer changes saved."
            st.rerun()
        except (ValidationError, InvalidOperation, StorageError) as exc:
            st.error(f"Buyer could not be updated: {exc}")
    st.write("#### Delete buyer")
    st.caption("Deletion permanently removes this buyer from Supabase.")
    confirmed = st.checkbox("I understand this buyer will be permanently deleted.", key=f"confirm_buyer_{selected.buyer_id}")
    if st.button("Delete Buyer", type="secondary", disabled=not confirmed):
        try:
            storage.delete_buyer(selected.buyer_id)
            st.session_state.buyers = [item for item in st.session_state.buyers if item.buyer_id != selected.buyer_id]
            st.session_state.record_manager_message = "Buyer deleted."
            st.rerun()
        except StorageError as exc:
            st.error(str(exc))


def render_record_manager(storage: Storage) -> None:
   