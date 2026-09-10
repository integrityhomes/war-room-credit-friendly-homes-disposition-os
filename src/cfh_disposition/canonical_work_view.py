"""Live read projection of canonical tasks; never a dispatch or task store."""

from collections import Counter

from .corepilot_work import payload

CLOSED = {"done", "completed", "closed", "cancelled", "canceled"}


def read_tasks(client):
    result = payload(client.functions.invoke("commandcore-crm-core", {
        "body": {"action": "list", "entity": "tasks", "limit": 500},
    }))
    rows = result.get("records")
    if not isinstance(rows, list) or any(not isinstance(r, dict) or not r.get("id") for r in rows):
        raise ValueError("Canonical task response is incomplete")
    if len(rows) >= 500:
        raise ValueError("Task list may be truncated; cannot report complete workload")
    return [r for r in rows if not r.get("archived")]


def task_rows(tasks):
    return [{"Task ID": r["id"], "Task": r.get("title") or "Untitled task",
             "Assigned to": r.get("assigned_to") or r.get("assigned_worker") or "Unassigned",
             "Due": r.get("due_date") or r.get("due_at") or "Not specified",
             "Status": r.get("status") or "Not specified",
             "Property": (r.get("links") or {}).get("property_id") or r.get("property_id") or ""}
            for r in tasks]


def render_canonical_work(client):
    """Used by all active work surfaces. Updates stay in the canonical executor."""
    import streamlit as st

    st.subheader("Internal tasks · canonical My Work")
    try:
        tasks = read_tasks(client)
    except Exception:
        st.warning("Canonical tasks could not be fully read. Internal workload is unavailable; refresh before making a workload decision.")
        return
    open_tasks = [r for r in tasks if str(r.get("status", "")).casefold() not in CLOSED]
    counts = Counter(r["Assigned to"] for r in task_rows(open_tasks))
    st.metric("Open internal tasks", len(open_tasks))
    st.caption("Same task records as Command Bot. Dispatch controls below apply only to campaign dispatch work.")
    if counts:
        st.dataframe([{"Assignee": owner, "Open internal tasks": n} for owner, n in sorted(counts.items())], hide_index=True)
    owners = sorted({r["Assigned to"] for r in task_rows(tasks)})
    owner = st.selectbox("Internal tasks for", ["All Team", *owners], key="canonical_work_owner")
    visible = [r for r in tasks if owner == "All Team" or task_rows([r])[0]["Assigned to"] == owner]
    if not st.checkbox("Include completed internal tasks", key="canonical_work_completed"):
        visible = [r for r in visible if str(r.get("status", "")).casefold() not in CLOSED]
    if visible:
        st.dataframe(task_rows(visible), hide_index=True)
    for r in visible:
        with st.expander(str(r.get("title") or "Untitled task")):
            st.write(str(r.get("title") or "Untitled task"))
            st.caption(f"Task ID: {r['id']} · Due: {r.get('due_date') or 'Not specified'} · Status: {r.get('status')}")
            for note in r.get("internal_notes", []):
                st.write(note.get("text", ""))
            st.write("History", r.get("internal_history", []))
    st.caption("Use Command Bot to select this task by exact title or ID, reschedule, reassign, add a private note, or mark it done.")

    return tasks
