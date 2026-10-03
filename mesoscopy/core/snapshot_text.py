"""A QCoDeS instrument snapshot as rows, like ``print_readable_snapshot`` (no Qt).

``snapshot_rows`` flattens the snapshot into rows (depth, name, value, unit, updated) in tree order: a group
(the instrument, a module, a channel) is a row without value, followed by its parameters and sub-groups.
The Instruments tab shows the rows as a tree; ``rows_to_text`` gives the same rows as text for the clipboard.
"""
from mesoscopy.core.parameter_io import format_value


def snapshot_rows(snapshot, name):
    """Rows of an instrument snapshot: dicts with depth, name, value, unit, updated, group (bool)."""
    rows = []

    def walk(node, label, depth):
        rows.append({"depth": depth, "name": label, "value": "", "unit": "", "updated": "", "group": True})
        first = len(rows)
        for pname, entry in sorted((node.get("parameters") or {}).items()):
            value = entry.get("value")
            rows.append({
                "depth": depth + 1, "name": pname, "group": False,
                "value": "" if value is None else format_value(value), "unit": entry.get("unit") or "",
                "updated": entry.get("ts") or "",
            })
        for sname, entry in sorted((node.get("submodules") or {}).items()):
            if entry.get("parameters") or entry.get("submodules") or entry.get("channels"):
                walk(entry, sname, depth + 1)
            for cname, channel in sorted((entry.get("channels") or {}).items()):
                walk(channel, f"{sname}.{cname}", depth + 1)
        if len(rows) == first:  # nothing below: not worth a row
            rows.pop()

    walk(snapshot, name, 0)
    return rows


def rows_to_text(rows):
    """The rows as indented text, values aligned: easy to paste in a lab notebook or a bug report."""
    width = max((2 * r["depth"] + len(r["name"]) for r in rows if not r["group"]), default=0)
    lines = []
    for row in rows:
        indent = "  " * row["depth"]
        if row["group"]:
            lines.append(f"{indent}{row['name']}:")
        else:
            unit = f" {row['unit']}" if row["unit"] else ""
            lines.append(f"{indent}{row['name']:<{width - len(indent)}}  {row['value']}{unit}"
                         + (f"   [{row['updated']}]" if row["updated"] else ""))
    return "\n".join(lines)
