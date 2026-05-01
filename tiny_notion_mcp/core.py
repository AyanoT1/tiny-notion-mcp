"""Core Notion MCP tools - implementation-agnostic interface."""

from typing import TypedDict


class NotionClient:
    """Notion API client wrapper."""

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search Notion pages."""
        ...

    def blocks_children_list(self, block_id: str) -> list[dict]:
        """List block children."""
        ...

    def blocks_children_append(self, block_id: str, children: list[dict], after_block_id: str | None = None) -> dict:
        """Append blocks to a page. Pass after_block_id to insert after a specific block."""
        ...

    def pages_create(self, parent_id: str, title: str, parent_type: str = "page_id", extra_properties: dict | None = None) -> dict:
        """Create a new page or database entry under parent_id."""
        ...

    def page_trash(self, page_id: str) -> dict:
        """Trash (move to bin) a page."""
        ...

    def database_query(self, database_id: str, limit: int = 100) -> list[dict]:
        """Query a database and return page results."""
        ...

    def pages_update(self, page_id: str, properties: dict) -> dict:
        """Update page properties."""
        ...


_client: NotionClient | None = None


def _get_client() -> NotionClient:
    """Get or create Notion client."""
    global _client
    if _client is None:
        raise RuntimeError("Notion client not initialized. Set NOTION_API_KEY.")
    return _client


def set_client(client: NotionClient) -> None:
    """Set Notion client (for testing)."""
    global _client
    _client = client


def notion_search(query: str, limit: int = 10) -> str:
    """
    Search Notion pages.
    
    Returns TOON format: Title | ID | URL (one per line)
    """
    client = _get_client()
    results = client.search(query, limit=limit)
    
    lines = []
    for r in results:
        obj_type = r.get("object", "page")
        if obj_type == "database":
            title_parts = r.get("title", [])
        else:
            title_parts = r.get("properties", {}).get("title", {}).get("title", [])
        title_text = "".join(t.get("plain_text", "") for t in title_parts)

        parent = r.get("parent", {})
        parent_id = parent.get("page_id") or parent.get("database_id") or ""
        parent_part = f" | parent:{parent_id}" if parent_id else ""
        type_part = f" [database]" if obj_type == "database" else ""

        lines.append(f"{title_text}{type_part} | {r.get('id', '')} | {r.get('url', '')}{parent_part}")
    
    return "\n".join(lines)


def notion_read(page_id: str) -> str:
    """
    Read a Notion page as markdown.
    
    Returns markdown string directly - no file paths.
    """
    client = _get_client()
    blocks = client.blocks_children_list(page_id)
    
    return _blocks_to_markdown(blocks)


def notion_get_blocks(page_id: str) -> str:
    """
    List all blocks on a page with their IDs.

    Returns one line per block: block-id | block_type | text_preview
    Use the block-id with notion_write's after_block_id to insert content
    after a specific block.
    """
    client = _get_client()
    blocks = client.blocks_children_list(page_id)

    lines = []
    for block in blocks:
        block_id = block.get("id", "")
        block_type = block.get("type", "unknown")
        data = block.get(block_type, {})
        if "rich_text" in data:
            preview = "".join(t.get("plain_text", "") for t in data["rich_text"])
        elif block_type == "child_page":
            preview = data.get("title", "")
        elif block_type == "table":
            preview = f"({data.get('table_width', '?')} columns)"
        elif block_type == "divider":
            preview = "---"
        else:
            preview = ""
        lines.append(f"{block_id} | {block_type} | {preview}")

    return "\n".join(lines)


def notion_write(page_id: str, markdown: str, after_block_id: str | None = None) -> dict:
    """
    Append markdown to a Notion page.

    Converts markdown to blocks and appends to page.
    If after_block_id is given, the first batch is inserted after that block (positional insert).
    Tables use two API calls: create the table block, then append rows to its ID.
    """
    client = _get_client()
    blocks = _markdown_to_blocks(markdown)

    result = {}
    pending: list[dict] = []
    i = 0
    used_after = False

    def _flush():
        nonlocal result, used_after
        if pending:
            after = after_block_id if not used_after else None
            result = client.blocks_children_append(page_id, pending, after_block_id=after)
            pending.clear()
            used_after = True

    while i < len(blocks):
        block = blocks[i]
        if block.get("type") == "table":
            _flush()
            # Collect rows that follow the table block
            rows = []
            i += 1
            while i < len(blocks) and blocks[i].get("type") == "table_row":
                rows.append(blocks[i])
                i += 1
            # Notion requires rows as children inside the table object at creation time
            table_with_children = {**block, "table": {**block["table"], "children": rows}}
            after = after_block_id if not used_after else None
            result = client.blocks_children_append(page_id, [table_with_children], after_block_id=after)
            used_after = True
        elif block.get("type") != "table_row":
            pending.append(block)
            i += 1
        else:
            i += 1

    _flush()
    return result


def notion_delete_page(page_id: str) -> str:
    """
    Trash a Notion page (moves it to Notion's trash — reversible from the Notion UI).

    WARNING: This is a destructive operation. The page will no longer appear in search
    or reads. It can be restored from Notion's trash within 30 days.
    Returns a confirmation string with the trashed page ID.
    """
    client = _get_client()
    client.page_trash(page_id)
    return f"Trashed page {page_id}"


def notion_query_database(database_id: str, limit: int = 100) -> str:
    """
    Query a Notion database and return results as a markdown table.

    Each row is one database entry. Columns match the database properties in
    their defined order. An ID column is appended for follow-up tool calls.
    Returns 'No results.' if the database is empty or has no matching entries.
    """
    client = _get_client()
    results = client.database_query(database_id, limit=limit)

    if not results:
        return "No results."

    columns = list(results[0].get("properties", {}).keys())
    header = "| " + " | ".join(columns + ["ID"]) + " |"
    separator = "| " + " | ".join(["---"] * (len(columns) + 1)) + " |"

    rows = [header, separator]
    for page in results:
        props = page.get("properties", {})
        values = [_extract_property_value(props.get(col, {})) for col in columns]
        values.append(page.get("id", ""))
        rows.append("| " + " | ".join(v.replace("|", "\\|") for v in values) + " |")

    return "\n".join(rows)


def _extract_property_value(prop: dict) -> str:
    """Normalize any Notion property object to a plain string."""
    t = prop.get("type", "")

    if t == "title":
        return "".join(r.get("plain_text", "") for r in prop.get("title", []))
    if t == "rich_text":
        return "".join(r.get("plain_text", "") for r in prop.get("rich_text", []))
    if t == "number":
        v = prop.get("number")
        return str(v) if v is not None else ""
    if t == "select":
        s = prop.get("select")
        return s.get("name", "") if s else ""
    if t == "multi_select":
        return ", ".join(s.get("name", "") for s in prop.get("multi_select", []))
    if t == "status":
        s = prop.get("status")
        return s.get("name", "") if s else ""
    if t == "date":
        d = prop.get("date")
        if not d:
            return ""
        start = d.get("start", "")
        end = d.get("end")
        return f"{start} → {end}" if end else start
    if t == "checkbox":
        return "✓" if prop.get("checkbox") else "✗"
    if t == "people":
        return ", ".join(p.get("name", p.get("id", "")) for p in prop.get("people", []))
    if t == "relation":
        return ", ".join(r.get("id", "") for r in prop.get("relation", []))
    if t == "url":
        return prop.get("url") or ""
    if t == "email":
        return prop.get("email") or ""
    if t == "phone_number":
        return prop.get("phone_number") or ""
    if t == "formula":
        f = prop.get("formula", {})
        ft = f.get("type", "")
        if ft == "string":
            return f.get("string") or ""
        if ft == "number":
            v = f.get("number")
            return str(v) if v is not None else ""
        if ft == "boolean":
            return "✓" if f.get("boolean") else "✗"
        if ft == "date":
            d = f.get("date")
            return d.get("start", "") if d else ""
        return ""
    if t == "rollup":
        r = prop.get("rollup", {})
        rt = r.get("type", "")
        if rt == "number":
            v = r.get("number")
            return str(v) if v is not None else ""
        if rt == "array":
            return f"[{len(r.get('array', []))} items]"
        return ""
    if t in ("created_time", "last_edited_time"):
        return prop.get(t, "")
    if t == "created_by":
        u = prop.get("created_by", {})
        return u.get("name", u.get("id", ""))
    if t == "last_edited_by":
        u = prop.get("last_edited_by", {})
        return u.get("name", u.get("id", ""))
    if t == "unique_id":
        uid = prop.get("unique_id", {})
        prefix = uid.get("prefix")
        number = uid.get("number", "")
        return f"{prefix}-{number}" if prefix else str(number)
    if t == "files":
        return ", ".join(f.get("name", "") for f in prop.get("files", []))
    return ""


def notion_create_page(parent_id: str, title: str, markdown: str = "", parent_type: str = "page_id", properties: dict | None = None) -> str:
    """
    Create a subpage (parent_type='page_id') or database entry (parent_type='database_id').
    For database entries, pass extra properties as a dict of Notion property objects.
    Optionally appends markdown content to the new page.
    Returns TOON format: Title | ID | URL
    """
    client = _get_client()
    page = client.pages_create(parent_id, title, parent_type=parent_type, extra_properties=properties)
    page_id = page.get("id", "")
    url = page.get("url", "")
    if markdown:
        notion_write(page_id, markdown)
    return f"{title} | {page_id} | {url}"


def notion_update_page(page_id: str, properties: dict) -> str:
    """
    Update properties of a Notion page or database entry.
    properties must be a dict of Notion property objects, e.g.:
      {"Status": {"status": {"name": "Done"}}}
      {"Date": {"date": {"start": "2026-04-30"}}}
    Returns a confirmation string.
    """
    client = _get_client()
    client.pages_update(page_id, properties)
    return f"Updated page {page_id}"


_LIST_TYPES = {"bulleted_list_item", "numbered_list_item", "to_do"}
_HEADING_TYPES = {"heading_1", "heading_2", "heading_3"}
_SINGLE_NEWLINE_TYPES = _HEADING_TYPES | {"divider"}


def _block_separator(prev_type: str, curr_type: str) -> str:
    """Return the newline separator to use between two consecutive block types."""
    if prev_type in _SINGLE_NEWLINE_TYPES or curr_type in _SINGLE_NEWLINE_TYPES:
        return "\n"
    if prev_type in _LIST_TYPES and curr_type in _LIST_TYPES:
        return "\n" if prev_type == curr_type else "\n\n"
    return "\n"


def _blocks_to_markdown(blocks: list[dict]) -> str:
    """Convert Notion blocks to markdown."""
    entries: list[tuple[str, str]] = []  # (block_type, text)
    i = 0
    numbered_index = 0
    while i < len(blocks):
        block = blocks[i]
        block_type = block.get("type", "")
        if block_type != "numbered_list_item":
            numbered_index = 0

        if block_type == "table":
            row_blocks = _get_client().blocks_children_list(block["id"])
            table_lines = []
            for row_block in row_blocks:
                if row_block.get("type") == "table_row":
                    cells = row_block.get("table_row", {}).get("cells", [])
                    cell_texts = []
                    for cell in cells:
                        if not cell:
                            cell_text = ""
                        elif isinstance(cell[0], dict):
                            cell_text = "".join(c.get("plain_text", "") for c in cell)
                        else:
                            cell_text = str(cell[0])
                        cell_texts.append(cell_text)
                    table_lines.append("| " + " | ".join(cell_texts) + " |")
            entries.append(("table", "\n".join(table_lines)))
        elif block_type == "paragraph":
            text = _get_rich_text(block.get("paragraph", {}))
            entries.append(("paragraph", text))
        elif block_type == "heading_1":
            text = _get_rich_text(block.get("heading_1", {}))
            entries.append(("heading_1", f"# {text}"))
        elif block_type == "heading_2":
            text = _get_rich_text(block.get("heading_2", {}))
            entries.append(("heading_2", f"## {text}"))
        elif block_type == "heading_3":
            text = _get_rich_text(block.get("heading_3", {}))
            entries.append(("heading_3", f"### {text}"))
        elif block_type == "child_page":
            child_title = block.get("child_page", {}).get("title", "")
            child_id = block.get("id", "")
            entries.append(("child_page", f"[Subpage: {child_title}]({child_id})"))
        elif block_type == "bulleted_list_item":
            text = _get_rich_text(block.get("bulleted_list_item", {}))
            entries.append(("bulleted_list_item", f"- {text}"))
        elif block_type == "numbered_list_item":
            numbered_index += 1
            text = _get_rich_text(block.get("numbered_list_item", {}))
            entries.append(("numbered_list_item", f"{numbered_index}. {text}"))
        elif block_type == "to_do":
            text = _get_rich_text(block.get("to_do", {}))
            checked = block.get("to_do", {}).get("checked", False)
            mark = "x" if checked else " "
            entries.append(("to_do", f"[{mark}] {text}"))
        elif block_type == "quote":
            text = _get_rich_text(block.get("quote", {}))
            entries.append(("quote", f"> {text}"))
        elif block_type == "callout":
            text = _get_rich_text(block.get("callout", {}))
            icon = block.get("callout", {}).get("icon", {})
            emoji = icon.get("emoji", "💡") if icon.get("type") == "emoji" else "💡"
            entries.append(("callout", f"> [{emoji}] {text}"))
        elif block_type == "divider":
            entries.append(("divider", "---"))
        else:
            i += 1
            continue
        i += 1

    if not entries:
        return ""
    result = entries[0][1]
    for (prev_type, _), (curr_type, text) in zip(entries, entries[1:]):
        result += _block_separator(prev_type, curr_type) + text
    return result


def _get_rich_text(block: dict) -> str:
    """Extract rich text from rich_text array with markdown formatting."""
    rich_text = block.get("rich_text", [])
    result = []
    for t in rich_text:
        text = t.get("plain_text", "")
        annotations = t.get("annotations", {})
        link = t.get("href") or t.get("text", {}).get("link")
        href = link.get("url") if isinstance(link, dict) else link

        if annotations.get("code"):
            text = f"`{text}`"
        if annotations.get("bold"):
            text = f"**{text}**"
        if annotations.get("italic"):
            text = f"*{text}*"
        if annotations.get("strikethrough"):
            text = f"~~{text}~~"
        if annotations.get("underline"):
            text = f"__{text}__"

        if href:
            text = f"[{text}]({href})"

        result.append(text)
    return "".join(result)


def _markdown_to_blocks(markdown: str) -> list[dict]:
    """Convert markdown to Notion blocks."""
    import re

    table_rows = []
    non_table_blocks = []

    for line in markdown.split("\n"):
        line = line.strip()
        if not line:
            if table_rows:
                non_table_blocks.extend(_create_table_blocks(table_rows))
                table_rows = []
        elif line.startswith("|") and line.endswith("|"):
            if not any(x in line for x in ["---", ":-", ":-:"]):
                cells = [c.strip() for c in line.split("|")[1:-1]]
                table_rows.append(cells)
        else:
            if table_rows:
                non_table_blocks.extend(_create_table_blocks(table_rows))
                table_rows = []
            non_table_blocks.extend(_parse_line_to_blocks(line))

    if table_rows:
        non_table_blocks.extend(_create_table_blocks(table_rows))

    return non_table_blocks


def _create_table_blocks(rows: list[list[str]]) -> list[dict]:
    """Return [table_block, row_block, ...] for a set of markdown table rows."""
    if not rows:
        return []

    num_cols = len(rows[0])
    blocks = [{
        "object": "block",
        "type": "table",
        "table": {
            "table_width": num_cols,
            "has_column_header": True,
            "has_row_header": False,
        },
    }]

    for idx, row in enumerate(rows):
        is_header = idx == 0
        cells = []
        for cell in row:
            rich_text = _parse_inline_formatting(cell)
            if is_header:
                for rt in rich_text:
                    ann = rt.setdefault("annotations", {})
                    ann["bold"] = True
            cells.append(rich_text)
        blocks.append({
            "object": "block",
            "type": "table_row",
            "table_row": {"cells": cells},
        })

    return blocks


def _parse_line_to_blocks(line: str) -> list[dict]:
    """Parse a single line of markdown to blocks (with inline formatting)."""
    import re

    if line == "---":
        return [{"object": "block", "type": "divider", "divider": {}}]
    if re.match(r"^\[[ x]\] ", line):
        checked = line[1] == "x"
        content = _parse_inline_formatting(line[4:])
        return [{"object": "block", "type": "to_do", "to_do": {"rich_text": content, "checked": checked}}]
    if re.match(r"^> \[.+?\] ", line):
        # Callout: "> [emoji] text"
        m = re.match(r"^> \[(.+?)\] (.*)", line)
        emoji = m.group(1) if m else "💡"
        text = m.group(2) if m else line[2:]
        content = _parse_inline_formatting(text)
        return [{"object": "block", "type": "callout", "callout": {
            "rich_text": content,
            "icon": {"type": "emoji", "emoji": emoji},
        }}]
    if line.startswith("> "):
        content = _parse_inline_formatting(line[2:])
        return [{"object": "block", "type": "quote", "quote": {"rich_text": content}}]
    if line.startswith("# "):
        content = _parse_inline_formatting(line[2:])
        return [{
            "object": "block",
            "type": "heading_1",
            "heading_1": {"rich_text": content},
        }]
    elif line.startswith("## "):
        content = _parse_inline_formatting(line[3:])
        return [{
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": content},
        }]
    elif line.startswith("### "):
        content = _parse_inline_formatting(line[4:])
        return [{
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": content},
        }]
    elif line.startswith("- "):
        content = _parse_inline_formatting(line[2:])
        return [{
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": content},
        }]
    elif re.match(r"^\d+\. ", line):
        content = _parse_inline_formatting(re.sub(r"^\d+\. ", "", line))
        return [{
            "object": "block",
            "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": content},
        }]
    else:
        content = _parse_inline_formatting(line)
        return [{
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": content},
        }]


def _parse_inline_formatting(text: str) -> list[dict]:
    """Parse markdown inline formatting to rich_text array."""
    import re

    pattern = r'(\*\*\*(.+?)\*\*\*)|(\*\*(.+?)\*\*)|(\*(.+?)\*)|(`(.+?)`)|(\[([^\]]+)\]\(([^\)]+)\))'
    parts = []
    last_end = 0

    for match in re.finditer(pattern, text):
        if match.start() > last_end:
            parts.append({"text": {"content": text[last_end:match.start()]}})

        if match.group(1):
            parts.append({"text": {"content": match.group(2)}, "annotations": {"bold": True, "italic": True}})
        elif match.group(3):
            parts.append({"text": {"content": match.group(4)}, "annotations": {"bold": True}})
        elif match.group(5):
            parts.append({"text": {"content": match.group(6)}, "annotations": {"italic": True}})
        elif match.group(7):
            parts.append({"text": {"content": match.group(8)}, "annotations": {"code": True}})
        elif match.group(9):
            parts.append({"text": {"content": match.group(10), "link": {"url": match.group(11)}}})

        last_end = match.end()

    if last_end < len(text):
        parts.append({"text": {"content": text[last_end:]}})

    if not parts:
        return [{"text": {"content": text}}]
    
    return parts