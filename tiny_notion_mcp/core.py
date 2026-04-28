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
        
        lines.append(f"{title_text} | {r.get('id', '')} | {r.get('url', '')}")
    
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
    """
    client = _get_client()
    blocks = _markdown_to_blocks(markdown)
    return client.blocks_children_append(page_id, blocks)


def _blocks_to_markdown(blocks: list[dict]) -> str:
    """Convert Notion blocks to markdown."""
    lines = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        block_type = block.get("type", "")

        if block_type == "table":
            table_info = block.get("table", {})
            table_rows = table_info.get("table_rows", 0)
            table_lines = []
            row_count = 0
            i += 1
            while i < len(blocks) and row_count < table_rows:
                row_block = blocks[i]
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
                    row_count += 1
                i += 1
            lines.extend(table_lines)
            i -= 1
        elif block_type == "paragraph":
            text = _get_rich_text(block.get("paragraph", {}))
            lines.append(text)
        elif block_type == "heading_1":
            text = _get_rich_text(block.get("heading_1", {}))
            lines.append(f"# {text}")
        elif block_type == "heading_2":
            text = _get_rich_text(block.get("heading_2", {}))
            lines.append(f"## {text}")
        elif block_type == "heading_3":
            text = _get_rich_text(block.get("heading_3", {}))
            lines.append(f"### {text}")
        elif block_type == "bulleted_list_item":
            text = _get_rich_text(block.get("bulleted_list_item", {}))
            lines.append(f"- {text}")
        elif block_type == "numbered_list_item":
            text = _get_rich_text(block.get("numbered_list_item", {}))
            lines.append(f"1. {text}")
        else:
            i += 1
            continue
        i += 1

    return "\n\n".join(lines)


def _get_rich_text(block: dict) -> str:
    """Extract rich text from rich_text array with markdown formatting."""
    rich_text = block.get("rich_text", [])
    result = []
    for t in rich_text:
        text = t.get("plain_text", "")
        annotations = t.get("annotations", {})
        href = t.get("href") or t.get("text", {}).get("link")

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
            non_table_blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": ""}}]},
            })
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
    """Create table blocks. Falls back to paragraph blocks if table creation fails."""
    if not rows:
        return []

    table_paragraphs = []
    for row in rows:
        table_paragraphs.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": " | ".join(row)}}]},
        })

    num_cols = len(rows[0]) if rows else 1

    table_block = {
        "object": "block",
        "type": "table",
        "table": {
            "table_rows": len(rows),
            "table_width": num_cols,
            "has_column_header": True,
            "has_row_header": False,
        },
    }

    blocks = [table_block]

    for row in rows:
        cells = []
        for cell in row:
            cells.append([{"text": {"content": cell}}])
        blocks.append({
            "object": "block",
            "type": "table_row",
            "table_row": {"cells": cells},
        })

    return blocks


def _parse_line_to_blocks(line: str) -> list[dict]:
    """Parse a single line of markdown to blocks (with inline formatting)."""
    import re

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