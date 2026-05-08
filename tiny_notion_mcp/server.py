"""MCP server for Notion - stdio transport."""

import os
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from tiny_notion_mcp.core import notion_search, notion_read, notion_get_blocks, notion_write, notion_create_page, notion_update_page, notion_delete_block, notion_delete_page, notion_query_database, NotionClient


class NotionClientImpl(NotionClient):
    def __init__(self, api_key: str):
        from notion_client import Client
        self._client = Client(auth=api_key)

    def search(self, query: str, limit: int = 10) -> list[dict]:
        response = self._client.search(
            query=query,
            page_size=limit,
        )
        return response.get("results", [])

    def blocks_children_list(self, block_id: str, start_cursor: str | None = None) -> tuple[list[dict], str | None]:
        kwargs = {"block_id": block_id}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
        response = self._client.blocks.children.list(**kwargs)
        results = response.get("results", [])
        next_cursor = response.get("next_cursor") if response.get("has_more") else None
        return results, next_cursor

    def blocks_children_append(self, block_id: str, children: list[dict], after_block_id: str | None = None) -> dict:
        kwargs = {"block_id": block_id, "children": children}
        if after_block_id:
            kwargs["after"] = after_block_id
        return self._client.blocks.children.append(**kwargs)

    def pages_create(self, parent_id: str, title: str, parent_type: str = "page_id", extra_properties: dict | None = None) -> dict:
        parent = {"type": parent_type, parent_type: parent_id}
        if parent_type == "database_id":
            props = dict(extra_properties or {})
            # Inject title into a "Name" property if not already present
            title_key = next((k for k, v in props.items() if isinstance(v, dict) and "title" in v), "Name")
            if title_key not in props:
                props[title_key] = {"title": [{"text": {"content": title}}]}
            return self._client.pages.create(parent=parent, properties=props)
        return self._client.pages.create(
            parent={"type": "page_id", "page_id": parent_id},
            properties={"title": {"title": [{"text": {"content": title}}]}},
        )

    def pages_update(self, page_id: str, properties: dict) -> dict:
        return self._client.pages.update(page_id=page_id, properties=properties)

    def block_delete(self, block_id: str) -> dict:
        return self._client.blocks.delete(block_id=block_id)

    def page_trash(self, page_id: str) -> dict:
        return self._client.pages.update(page_id=page_id, **{"in_trash": True})

    def database_query(self, database_id: str, limit: int = 100, start_cursor: str | None = None) -> tuple[list[dict], str | None]:
        db = self._client.databases.retrieve(database_id)
        data_sources = db.get("data_sources", [])
        if not data_sources:
            raise RuntimeError(f"No data source found for database {database_id}")
        data_source_id = data_sources[0]["id"]
        kwargs = {"data_source_id": data_source_id, "page_size": min(limit, 100)}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
        response = self._client.data_sources.query(**kwargs)
        results = response.get("results", [])
        next_cursor = response.get("next_cursor") if response.get("has_more") else None
        return results, next_cursor


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
            description=(
                "Read a Notion page as markdown. Returns markdown string directly. "
                "If the response ends with 'MORE: <cursor>', pass that cursor as "
                "start_cursor to read the next batch of blocks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Notion page ID"},
                    "start_cursor": {
                        "type": "string",
                        "description": "Cursor from a previous 'MORE:' response to get the next batch",
                    },
                },
                "required": ["page_id"],
            },
        ),
        Tool(
            name="notion_get_blocks",
            description=(
                "List all blocks on a page with their IDs. "
                "Returns one line per block: block-id | block_type | text_preview. "
                "If the response ends with 'MORE: <cursor>', pass that cursor as "
                "start_cursor to get the next batch. "
                "Use the block-id with notion_write's after_block_id to insert content after a specific block."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Notion page ID"},
                    "start_cursor": {
                        "type": "string",
                        "description": "Cursor from a previous 'MORE:' response to get the next batch",
                    },
                },
                "required": ["page_id"],
            },
        ),
        Tool(
            name="notion_write",
            description=(
                "Append markdown to a Notion page. Converts markdown to blocks. "
                "Pass after_block_id to insert the content after a specific block rather than at the end of the page. "
                "Use notion_read to find block IDs (each block object has an 'id' field)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Notion page ID"},
                    "markdown": {"type": "string", "description": "Markdown content to append"},
                    "after_block_id": {
                        "type": "string",
                        "description": "Block ID after which to insert the content. Omit to append at the end.",
                    },
                },
                "required": ["page_id", "markdown"],
            },
        ),
        Tool(
            name="notion_create_page",
            description=(
                "Create a new page or database entry. "
                "Set parent_type='page_id' (default) for a subpage, or 'database_id' to insert a row into a database. "
                "For database entries, pass extra properties (Status, Date, etc.) as Notion property objects via the 'properties' field. "
                "Returns TOON format with the new page ID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "parent_id": {"type": "string", "description": "Parent page ID or database ID"},
                    "title": {"type": "string", "description": "Title / Name of the new page or entry"},
                    "parent_type": {
                        "type": "string",
                        "enum": ["page_id", "database_id"],
                        "default": "page_id",
                        "description": "Whether parent_id is a page ('page_id') or database ('database_id')",
                    },
                    "properties": {
                        "type": "object",
                        "description": "Additional Notion property objects for database entries (e.g. Status, Date, Category)",
                        "additionalProperties": True,
                    },
                    "markdown": {"type": "string", "description": "Optional markdown content to write to the new page"},
                },
                "required": ["parent_id", "title"],
            },
        ),
        Tool(
            name="notion_update_page",
            description=(
                "Update properties of a Notion page or database entry. "
                "Pass a dict of Notion property objects, e.g. "
                "{\"Status\": {\"status\": {\"name\": \"Done\"}}} or "
                "{\"Date\": {\"date\": {\"start\": \"2026-04-30\"}}}."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "ID of the page or database entry to update"},
                    "properties": {
                        "type": "object",
                        "description": "Notion property objects to update",
                        "additionalProperties": True,
                    },
                },
                "required": ["page_id", "properties"],
            },
        ),
        Tool(
            name="notion_query_database",
            description=(
                "Query a Notion database and return results as a markdown table. "
                "Each row is one entry; columns match the database properties. "
                "An ID column is appended for follow-up reads or writes. "
                "If the response ends with 'MORE: <cursor>', pass that cursor as "
                "start_cursor to get the next batch."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "database_id": {"type": "string", "description": "Notion database ID"},
                    "limit": {"type": "integer", "description": "Max rows to return (default 100, max 100)", "default": 100},
                    "start_cursor": {
                        "type": "string",
                        "description": "Cursor from a previous 'MORE:' response to get the next batch",
                    },
                },
                "required": ["database_id"],
            },
        ),
        Tool(
            name="notion_delete_block",
            description=(
                "⚠️ DESTRUCTIVE — deletes a single block (moves to Notion's trash, recoverable within 30 days). "
                "Use notion_get_blocks to find the block ID first. "
                "Deleting a parent block (table, toggle) also deletes all its children."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "block_id": {"type": "string", "description": "ID of the block to delete"},
                },
                "required": ["block_id"],
            },
        ),
        Tool(
            name="notion_delete_page",
            description=(
                "⚠️ DESTRUCTIVE — moves a Notion page to trash. "
                "The page is recoverable from Notion's trash within 30 days. "
                "Only call this when the user explicitly asks to delete a page."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "ID of the page to trash"},
                },
                "required": ["page_id"],
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
        result = notion_read(
            page_id=arguments["page_id"],
            start_cursor=arguments.get("start_cursor"),
        )
    elif name == "notion_get_blocks":
        result = notion_get_blocks(
            page_id=arguments["page_id"],
            start_cursor=arguments.get("start_cursor"),
        )
    elif name == "notion_write":
        result = notion_write(
            page_id=arguments["page_id"],
            markdown=arguments["markdown"],
            after_block_id=arguments.get("after_block_id"),
        )
    elif name == "notion_create_page":
        result = notion_create_page(
            parent_id=arguments["parent_id"],
            title=arguments["title"],
            markdown=arguments.get("markdown", ""),
            parent_type=arguments.get("parent_type", "page_id"),
            properties=arguments.get("properties"),
        )
    elif name == "notion_update_page":
        result = notion_update_page(
            page_id=arguments["page_id"],
            properties=arguments["properties"],
        )
    elif name == "notion_query_database":
        result = notion_query_database(
            database_id=arguments["database_id"],
            limit=arguments.get("limit", 100),
            start_cursor=arguments.get("start_cursor"),
        )
    elif name == "notion_delete_block":
        result = notion_delete_block(block_id=arguments["block_id"])
    elif name == "notion_delete_page":
        result = notion_delete_page(page_id=arguments["page_id"])
    else:
        raise ValueError(f"Unknown tool: {name}")

    return [TextContent(type="text", text=str(result))]


def main():
    import asyncio

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )

    asyncio.run(_run())


if __name__ == "__main__":
    main()