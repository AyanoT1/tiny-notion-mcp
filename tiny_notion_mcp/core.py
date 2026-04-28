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
    for block in blocks:
        block_type = block.get("type", "")
        
        if block_type == "paragraph":
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
    
    return "\n\n".join(lines)


def _get_rich_text(block: dict) -> str:
    """Extract plain text from rich_text array."""
    rich_text = block.get("rich_text", [])
    return "".join(t.get("plain_text", "") for t in rich_text)


def _markdown_to_blocks(markdown: str) -> list[dict]:
    """Convert markdown to Notion blocks."""
    blocks = []
    for line in markdown.split("\n"):
        line = line.strip()
        if not line:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": ""}}]},
            })
        elif line.startswith("# "):
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": [{"text": {"content": line[2:]}}]},
            })
        elif line.startswith("## "):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": line[3:]}}]},
            })
        elif line.startswith("### "):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"text": {"content": line[4:]}}]},
            })
        elif line.startswith("- "):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"text": {"content": line[2:]}}]},
            })
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": line}}]},
            })
    
    return blocks