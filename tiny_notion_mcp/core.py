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

    def blocks_children_append(self, block_id: str, children: list[dict]) -> dict:
        """Append blocks to a page."""
        ...

    def pages_create(self, parent_id: str, title: str) -> dict:
        """Create a new page under parent_id."""
        ...

    def page_trash(self, page_id: str) -> dict:
        """Trash (move to bin) a page."""
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
        title = r.get("properties", {}).get("title", {}).get("title", [])
        title_text = "".join(t.get("plain_text", "") for t in title)

        parent = r.get("parent", {})
        parent_id = parent.get("page_id") or parent.get("database_id") or ""
        parent_part = f" | parent:{parent_id}" if parent_id else ""

        lines.append(f"{title_text} | {r.get('id', '')} | {r.get('url', '')}{parent_part}")
    
    return "\n".join(lines)


def notion_read(page_id: str) -> str:
    """
    Read a Notion page as markdown.
    
    Returns markdown string directly - no file paths.
    """
    client = _get_client()
    blocks = client.blocks_children_list(page_id)
    
    return _blocks_to_markdown(blocks)


def notion_write(page_id: str, markdown: str) -> dict:
    """
    Append markdown to a Notion page.

    Converts markdown to blocks and appends to page.
    Tables use two API calls: create the table block, then append rows to its ID.
    """
    client = _get_client()
    blocks = _markdown_to_blocks(markdown)

    result = {}
    pending: list[dict] = []
    i = 0

    def _flush():
        nonlocal result
        if pending:
            result = client.blocks_children_append(page_id, pending)
            pending.clear()

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
            result = client.blocks_children_append(page_id, [table_with_children])
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


def notion_create_page(parent_id: str, title: str, markdown: str = "") -> str:
    """
    Create a subpage under parent_id with the given title.
    Optionally appends markdown content to the new page.
    Returns TOON format: Title | ID | URL
    """
    client = _get_client()
    page = client.pages_create(parent_id, title)
    page_id = page.get("id", "")
    url = page.get("url", "")
    if markdown:
        notion_write(page_id, markdown)
    return f"{title} | {page_id} | {url}"


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
        cells = [[{"text": {"content": cell}, "annotations": {"bold": is_header}}] for cell in row]
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