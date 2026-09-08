"""Shared presentation helpers for CommandCore's simple user experience."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import streamlit as st

ADVANCED_SETTINGS_LABEL = "Advanced settings"
SUCCESS_NOTICE_KEY = "commandcore_success_notice"

SAVE = "Save"
NEXT = "Next"
ASSIGN = "Assign"
REVIEW = "Review"
SEND_FOR_APPROVAL = "Send for approval"
APPROVE = "Approve"
CANCEL = "Cancel"


@dataclass(frozen=True, slots=True)
class NavigationItem:
    """One stable link in the CommandCore application shell."""

    path: str
    label: str


@dataclass(frozen=True, slots=True)
class NavigationSection:
    """A plain-English group of CommandCore destinations."""

    label: str
    items: tuple[NavigationItem, ...]


def render_page_header(
    title: str,
    purpose: str,
    *,
    primary_action_label: str | None = None,
    primary_action_page: str | None = None,
    primary_action_key: str | None = None,
) -> bool:
    """Render a compact page introduction and optional primary action."""
    heading, action = st.columns((4, 1), vertical_alignment="bottom")
    with heading:
        st.title(title)
        st.caption(purpose)

    if not primary_action_label:
        return False
    with action:
        if primary_action_page:
            st.page_link(
                primary_action_page,
                label=primary_action_label,
                use_container_width=True,
            )
            return False
        return st.button(
            primary_action_label,
            key=primary_action_key,
            type="primary",
            use_container_width=True,
        )


@contextmanager
def advanced_settings() -> Iterator[None]:
    """Keep rare or technical controls out of the everyday workflow."""
    with st.expander(ADVANCED_SETTINGS_LABEL, expanded=False):
        yield


def _message_body(what_happened: str, next_step: str | None) -> str:
    body = what_happened.strip()
    if next_step:
        body += f"\n\n**What to do next:** {next_step.strip()}"
    return body


def show_success(what_happened: str, *, next_step: str | None = None) -> None:
    """Confirm completion and, when useful, show the next safe step."""
    st.success(_message_body(what_happened, next_step))


def queue_success(what_happened: str, *, next_step: str | None = None) -> None:
    """Keep a success message visible after a safe rerun or page change."""
    st.session_state[SUCCESS_NOTICE_KEY] = (what_happened, next_step)


def show_queued_success() -> None:
    """Show and clear a success message saved by the previous user action."""
    notice = st.session_state.pop(SUCCESS_NOTICE_KEY, None)
    if isinstance(notice, tuple) and len(notice) == 2:
        show_success(notice[0], next_step=notice[1])


def show_needs_attention(what_happened: str, *, next_step: str) -> None:
    """Explain a non-fatal blocker and the next action in plain language."""
    st.warning(_message_body(what_happened, next_step))


def show_warning(what_happened: str, *, next_step: str | None = None) -> None:
    """Explain a risk without exposing implementation details."""
    st.warning(_message_body(what_happened, next_step))


def show_error(what_happened: str, *, next_step: str) -> None:
    """Explain a safe failure and tell the user how to continue."""
    st.error(_message_body(what_happened, next_step))


def render_sidebar_navigation(
    everyday_sections: Sequence[NavigationSection],
    advanced_sections: Sequence[NavigationSection],
) -> None:
    """Render daily work first while keeping every specialty route reachable."""
    with st.sidebar:
        st.markdown("## CommandCore")
        st.caption("Your real estate work, organized simply")

        for section in everyday_sections:
            st.markdown(f"#### {section.label}")
            for item in section.items:
                st.page_link(item.path, label=item.label, use_container_width=True)

        with st.expander("Admin / Advanced Tools", expanded=False):
            st.caption("Setup, specialty workflows, reports, and diagnostics")
            for section in advanced_sections:
                st.markdown(f"**{section.label}**")
                for item in section.items:
                    st.page_link(item.path, label=item.label, use_container_width=True)
