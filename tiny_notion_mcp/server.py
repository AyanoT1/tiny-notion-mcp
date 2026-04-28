"""MCP server for Notion - stdio transport."""

import os
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from tiny_notion_mcp.core import notion_search, notion_read, notion_write, notion_create_page, NotionClient


class NotionClientImpl(NotionClient):
    def __init__(self, api_key: str):
        from notion_client import Client
        self._client = Client(auth=api_key)

    def search(self, query: str, limit: int = 10) -> list[dict]:
        response = self._client.search(
            query=query,
            filter={"property": "object", "value": "page"},
            page_size=limit,
        )
        return response.get("results", [])

    def blocks_children_list(self, block_id: str) -> list[dict]:
        response = self._client.blocks.children.list(block_id=block_id)
        return response.get("results", [])

    def blocks_children_append(self, block_id: str, children: list[dict]) -> dict:
        return self._client.blocks.children.append(block_id=block_id, children=children)

    def pages_create(self, parent_id: str, title: str) -> dict:
        return self._client.pages.create(
            parent={"type": "page_id", "page_id": parent_id},
            properties={"title": {"title": [{"text": {"content": title}}]}},
        )


def _create_client() -> NotionClient:
    api_key = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_KEY")
    if not api_key:
        raise RuntimeError("NOTION_TOKEN or NOTION_API_KEY environment variable not set")
    return NotionClientImpl(api_key)


app = Server("tiny-notion-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="notion_search",
            description="Search Notion pages. Returns TOON format: Title | ID | URL (one per line)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="notion_read",
            description="Read a Notion page as markdown. Returns markdown string directly.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Notion page ID"},
                },
                "required": ["page_id"],
            },
        ),
        Tool(
            name="notion_write",
            description="Append markdown to a Notion page. Converts markdown to blocks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Notion page ID"},
                    "markdown": {"type": "string", "description": "Markdown content to append"},
                },
                "required": ["page_id", "markdown"],
            },
        ),
        Tool(
            name="notion_create_page",
            description="Create a new subpage under a parent page. Returns TOON format with the new page ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "parent_id": {"type": "string", "description": "Parent page ID"},
                    "title": {"type": "string", "description": "Title of the new page"},
                    "markdown": {"type": "string", "description": "Optional content to write to the new page"},
                },
                "required": ["parent_id", "title"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    from tiny_notion_mcp.core import set_client

    client = _create_client()
    set_client(client)

    if name == "notion_search":
        result = notion_search(
            query=arguments["query"],
            limit=arguments.get("limit", 10),
        )
    elif name == "notion_read":
        result = notion_read(arguments["page_id"])
    elif name == "notion_write":
        result = notion_write(
            page_id=arguments["page_id"],
            markdown=arguments["markdown"],
        )
    elif name == "notion_create_page":
        result = notion_create_page(
            parent_id=arguments["parent_id"],
            title=arguments["title"],
            markdown=arguments.get("markdown", ""),
        )
    else:
        raise ValueError(f"Unknown tool: {name}")

    return [TextContent(type="text", text=str(result))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())