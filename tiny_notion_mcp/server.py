"""MCP server for Notion - stdio transport."""

import os
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from tiny_notion_mcp.core import notion_search, notion_read, notion_write, NotionClient


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
        has_table = any(b.get("type") == "table" for b in children)
        
        if has_table:
            fallback_blocks = []
            for child in children:
                if child.get("type") == "table":
                    fallback_blocks.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"text": {"content": "[TABLE: see Notion page for actual table]"}}]},
                    })
                elif child.get("type") == "table_row":
                    pass
                else:
                    fallback_blocks.append(child)
            response = self._client.blocks.children.append(block_id=block_id, children=fallback_blocks)
            return response
        else:
            response = self._client.blocks.children.append(block_id=block_id, children=children)
            return response


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