# tiny-notion-mcp

A lightweight Notion MCP server that minimises token usage compared to the [official Notion MCP](https://github.com/makenotion/notion-mcp-server).

Instead of returning raw Notion API JSON, every tool returns the smallest useful representation: pages come back as plain Markdown, search results as a single line per hit. In practice this cuts token consumption significantly on read-heavy workflows.

## Tools

| Tool | Description |
| --- | --- |
| `notion_search` | Search pages by title. Returns one line per result in TOON format. |
| `notion_read` | Read a page as Markdown. |
| `notion_write` | Append Markdown to an existing page. |
| `notion_create_page` | Create a sub-page under a parent, optionally with content. |
| `notion_delete_page` | ⚠️ Move a page to Notion's trash (recoverable within 30 days). |

### TOON format

Search results and page creation responses use the compact **TOON** format:

```
Page title | page-id | https://notion.so/... | parent:<parent-id>
```

This keeps search responses to a single line per result instead of hundreds of tokens of JSON.

## Supported block types

### Read (`notion_read`)

| Block type | Markdown output |
| --- | --- |
| Paragraph | Plain text |
| Heading 1 / 2 / 3 | `#` / `##` / `###` |
| Bulleted list item | `- item` |
| Numbered list item | `1. item`, `2. item`, … |
| Code block | ` ```lang … ``` ` |
| Divider | `---` |
| Table | Pipe-delimited rows |
| Child page | `[Subpage: title](id)` |

Inline formatting (bold, italic, bold-italic, strikethrough, underline, inline code, links) is preserved as Markdown.

### Write (`notion_write`)

The same block types are supported on write. Markdown is parsed and appended to the target page as native Notion blocks.

## Not yet implemented or coming soon

The following block types are recognised by Notion but not yet handled. They are silently skipped on read and cannot be written:

- Block quotes
- To-do / checkbox lists
- Callout blocks
- Toggle lists
- Table of contents
- Files, images, and videos

## Known limitations

- **Empty paragraph blocks are not round-tripped.** Explicit empty paragraphs used as spacers in Notion are lost on a read → write cycle. This is an inherent limitation of a flat Markdown representation.

- **Table header flag is not round-tripped.** Notion tables can be created without a column-header row (`has_column_header: false`). The current writer always sets `has_column_header: true` because standard Markdown tables imply a header. Tables written back will look identical but have the header flag set.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed
- A Notion integration token ([create one here](https://www.notion.so/profile/integrations))

## Installation

### Claude Code

One command — no cloning needed:

```bash
claude mcp add tiny-notion-mcp -e NOTION_TOKEN=secret_... -- uvx --from git+https://github.com/AyanoT1/tiny-notion-mcp tiny-notion-mcp
```

### Claude Desktop

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tiny-notion-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AyanoT1/tiny-notion-mcp", "tiny-notion-mcp"],
      "env": {
        "NOTION_TOKEN": "secret_..."
      }
    }
  }
}
```

`uvx` handles downloading and running the package automatically — no manual install step required. `NOTION_API_KEY` is accepted as an alias for `NOTION_TOKEN`.

## Development

```bash
git clone https://github.com/AyanoT1/tiny-notion-mcp
cd tiny-notion-mcp
uv sync --dev
uv run pytest
```

To update a local Claude Code installation after making changes:

```bash
uv tool install . --force
```

Then reconnect the MCP server from Claude Code's `/mcp` menu.

Tests use a stub `NotionClient` and make no real API calls.

## Design goals

- **Token efficiency first.** Every response is as small as it can be while still being actionable.
- **No intermediate files.** All content is returned inline as strings — no temp files, no file-path references.
- **Testable without a Notion account.** The `NotionClient` interface is injected so the core logic can be tested in isolation.
