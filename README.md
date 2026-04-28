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

### TOON format

Search results and page creation responses use the compact **TOON** (Title | Object | Optional Notes) format:

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
| Table | Pipe-delimited rows |
| Child page | `[Subpage: title](id)` |

Inline formatting (bold, italic, bold-italic, strikethrough, underline, inline code, links) is preserved as Markdown.

### Write (`notion_write`)

The same block types are supported on write. Markdown is parsed and appended to the target page as native Notion blocks.

## Not yet implemented (v2)

The following block types are recognised by Notion but not yet handled. They are silently skipped on read and cannot be written:

- Dividers (`---`)
- Block quotes
- To-do / checkbox lists
- Callout blocks
- Toggle lists
- Table of contents
- Files, images, and videos

## Known limitations

- **Empty paragraph blocks between different list types are not round-tripped.** When a page has an explicit empty paragraph separating, say, a bulleted list from a numbered list, that separator is lost on a read → write cycle. The `"\n\n"` that Markdown already places between blocks is visually equivalent but does not produce a Notion empty-paragraph block on write. This is an inherent limitation of a flat Markdown representation and will stay until a v2 format is designed.

- **Table header flag is not round-tripped.** Notion tables can be created without a column-header row (`has_column_header: false`). The current writer always sets `has_column_header: true` because standard Markdown tables imply a header. Tables written back will look identical but have the header flag set.

## Requirements

- Python 3.12+
- A Notion integration token with read/write access to the pages you want to use

## Installation

```bash
# From source
git clone https://github.com/your-username/tiny-notion-mcp
cd tiny-notion-mcp
pip install .
```

Or install directly with `uv`:

```bash
uv tool install .
```

## Configuration

Set your Notion integration token as an environment variable:

```bash
export NOTION_TOKEN=secret_...
```

`NOTION_API_KEY` is accepted as an alias.

### Claude Desktop / Claude Code

Add the server to your MCP configuration:

```json
{
  "mcpServers": {
    "tiny-notion-mcp": {
      "command": "tiny-notion-mcp",
      "env": {
        "NOTION_TOKEN": "secret_..."
      }
    }
  }
}
```

If you installed with `uv` into an isolated environment, use the full path:

```json
{
  "mcpServers": {
    "tiny-notion-mcp": {
      "command": "uv",
      "args": ["run", "--", "tiny-notion-mcp"],
      "env": {
        "NOTION_TOKEN": "secret_..."
      }
    }
  }
}
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

Tests use a stub `NotionClient` and make no real API calls.

## Design goals

- **Token efficiency first.** Every response is as small as it can be while still being actionable.
- **No intermediate files.** All content is returned inline as strings — no temp files, no file-path references.
- **Testable without a Notion account.** The `NotionClient` interface is injected so the core logic can be tested in isolation.
