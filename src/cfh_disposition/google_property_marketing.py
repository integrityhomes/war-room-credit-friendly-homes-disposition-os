"""Read-only address-row highlight evidence, separate from availability and facts."""

from dataclasses import replace


def highlight_status(cell, default_format=None):
    fmt = cell.get("effectiveFormat") or default_format or {}
    style = fmt.get("backgroundColorStyle", {})
    rgb = style.get("rgbColor", fmt.get("backgroundColor"))
    if rgb is None:
        return "unknown"  # Missing metadata is not evidence of white or yellow.
    color = tuple(round(rgb.get(k, 0) * 255) for k in ("red", "green", "blue"))
    return {(255, 255, 0): "yellow", (255, 255, 255): "white"}.get(color, "unknown")


def read_row_highlights(session, sheet_id, worksheets):
    """One bounded metadata GET; verify row identity across the two read snapshots."""
    params = [("ranges", "'" + ws.tab_name.replace("'", "''") + f"'!A1:A{max(1, len(ws))}") for ws in worksheets]
    params.append(("fields", "properties(defaultFormat),sheets(properties(title),data(startRow,startColumn,rowData(values(formattedValue,effectiveFormat(backgroundColor,backgroundColorStyle)))))"))
    response = session.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}", params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()
    default = payload.get("properties", {}).get("defaultFormat", {})
    cells = {}
    names = set()
    for sheet in payload.get("sheets", []):
        title = sheet.get("properties", {}).get("title")
        names.add(title)
        for grid in sheet.get("data", []):
            if grid.get("startColumn", 0) != 0:
                raise ValueError("Unexpected highlight column")
            for offset, row in enumerate(grid.get("rowData", []), grid.get("startRow", 0) + 1):
                values = row.get("values", [])
                if values:
                    cells[title, offset] = values[0]
    statuses = {}
    for ws in worksheets:
        if ws.tab_name not in names:
            raise ValueError("Incomplete highlight read")
        for row, values in enumerate(ws, 1):
            if not values or not str(values[0]).strip():
                continue
            cell = cells.get((ws.tab_name, row), {})
            if str(cell.get("formattedValue", "")) != str(values[0]):
                raise ValueError("Source rows changed during highlight read; retry the complete read")
            statuses[ws.tab_name, row] = highlight_status(cell, default)
    return statuses


def attach_highlights(rows, statuses):
    return tuple(replace(row, marketing_status=statuses.get((row.tab, row.row), "unknown")) for row in rows)
