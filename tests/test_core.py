import pytest
from tiny_notion_mcp.core import (
    notion_search,
    notion_read,
    notion_write,
    notion_create_page,
    notion_delete_page,
    set_client,
    NotionClient,
)


class MockNotionClient(NotionClient):
    def __init__(self, pages=None):
        self._pages = pages or []
        self._blocks = {}
        self.appended = []
        self.created_pages = []

    def search(self, query, limit=10):
        results = []
        for p in self._pages:
            title = p.get("properties", {}).get("title", {}).get("title", [{}])[0].get("plain_text", "")
            if query.lower() in title.lower():
                results.append(p)
        return results[:limit]

    def blocks_children_list(self, block_id):
        return self._blocks.get(block_id, [])

    def blocks_children_append(self, block_id, children):
        self.appended.extend(children)
        results = [{"id": f"appended-block-{len(self.appended)-len(children)+i}"} for i in range(len(children))]
        return {"object": "list", "results": results}

    def pages_create(self, parent_id, title):
        page = {"id": f"new-page-{len(self.created_pages)}", "url": f"https://notion.so/new-page-{len(self.created_pages)}"}
        self.created_pages.append({"parent_id": parent_id, "title": title})
        return page

    def page_trash(self, page_id):
        self.trashed = getattr(self, "trashed", [])
        self.trashed.append(page_id)
        return {"id": page_id, "in_trash": True}


@pytest.fixture
def client():
    return MockNotionClient()


@pytest.fixture
def client_with_pages():
    return MockNotionClient(pages=[
        {
            "id": "page-123",
            "properties": {"title": {"title": [{"plain_text": "Test Page"}]}},
            "url": "https://notion.so/Test-Page-123",
        },
    ])


class TestSearchMinimalResponse:
    def test_search_returns_toon_format(self, client_with_pages):
        """Search should return TOON (Title | ID | URL) format."""
        set_client(client_with_pages)
        result = notion_search("test", limit=10)
        assert "Test Page | page-123 | https://notion.so/Test-Page-123" in result

    def test_search_respects_limit(self, client):
        for i in range(20):
            client._pages.append({
                "id": f"page-{i}",
                "properties": {"title": {"title": [{"plain_text": f"Page {i}"}]}},
                "url": f"https://notion.so/Page-{i}",
            })
        set_client(client)
        result = notion_search("page", limit=5)
        lines = result.strip("\n").split("\n")
        assert len(lines) == 5


class TestReadReturnsMarkdown:
    def test_read_returns_markdown_string(self, client):
        client._blocks["page-123"] = [
            {"id": "block-1", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello world"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert isinstance(result, str)
        assert "Hello world" in result

    def test_read_no_file_path_in_response(self, client):
        client._blocks["page-123"] = []
        set_client(client)
        result = notion_read("page-123")
        assert not result.startswith("/")
        assert not result.startswith(".")

    def test_read_handles_headings(self, client):
        client._blocks["page-123"] = [
            {"id": "block-1", "type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Main Title"}]}},
            {"id": "block-2", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Section"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "# Main Title" in result
        assert "## Section" in result

    def test_read_handles_bullets(self, client):
        client._blocks["page-123"] = [
            {"id": "block-1", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "Item 1"}]}},
            {"id": "block-2", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "Item 2"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "- Item 1" in result
        assert "- Item 2" in result


class TestWriteAppendsMarkdown:
    def test_write_returns_result(self, client):
        set_client(client)
        result = notion_write("page-123", "Hello world")
        assert result is not None

    def test_write_converts_markdown_to_blocks(self, client):
        set_client(client)
        notion_write("page-123", "# Title\n\n- item")
        assert len(client.appended) > 0

    def test_write_handles_paragraphs(self, client):
        set_client(client)
        notion_write("page-123", "Just a paragraph")
        assert len(client.appended) > 0


class TestNumberedLists:
    def test_read_handles_numbered_list(self, client):
        client._blocks["page-123"] = [
            {"id": "block-1", "type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "First"}]}},
            {"id": "block-2", "type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "Second"}]}},
            {"id": "block-3", "type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "Third"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "1. First" in result
        assert "2. Second" in result
        assert "3. Third" in result

    def test_read_resets_numbered_list_counter(self, client):
        client._blocks["page-123"] = [
            {"id": "block-1", "type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "First"}]}},
            {"id": "block-2", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Break"}]}},
            {"id": "block-3", "type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "Restart"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "1. First" in result
        assert "1. Restart" in result

    def test_write_handles_numbered_list(self, client):
        set_client(client)
        notion_write("page-123", "1. First\n2. Second")
        types = [b.get("type") for b in client.appended]
        assert types.count("numbered_list_item") == 2

    def test_write_numbered_list_content(self, client):
        set_client(client)
        notion_write("page-123", "1. Hello world")
        item = next(b for b in client.appended if b.get("type") == "numbered_list_item")
        text = item["numbered_list_item"]["rich_text"][0]["text"]["content"]
        assert text == "Hello world"


class TestSearchParentId:
    def test_search_includes_parent_id_when_present(self, client):
        client._pages = [{
            "id": "page-1",
            "properties": {"title": {"title": [{"plain_text": "Child Page"}]}},
            "url": "https://notion.so/Child-Page",
            "parent": {"type": "page_id", "page_id": "parent-abc"},
        }]
        set_client(client)
        result = notion_search("child")
        assert "parent:parent-abc" in result

    def test_search_omits_parent_for_workspace_pages(self, client):
        client._pages = [{
            "id": "page-1",
            "properties": {"title": {"title": [{"plain_text": "Root Page"}]}},
            "url": "https://notion.so/Root-Page",
            "parent": {"type": "workspace", "workspace": True},
        }]
        set_client(client)
        result = notion_search("root")
        assert "parent:" not in result


class TestStripMetadata:
    def test_search_strips_timestamps(self, client):
        client._pages = [{
            "id": "page-1",
            "properties": {"title": {"title": [{"plain_text": "Page 1"}]}},
            "url": "https://notion.so/Page-1",
            "created_time": "2024-01-01",
            "last_edited_time": "2024-01-02",
        }]
        set_client(client)
        result = notion_search("page")
        assert "created_time" not in result
        assert "last_edited_time" not in result
        assert "page-1" in result

    def test_search_strips_parent_info(self, client):
        client._pages = [{
            "id": "page-1",
            "properties": {"title": {"title": [{"plain_text": "Page 1"}]}},
            "url": "https://notion.so/Page-1",
            "parent": {"type": "workspace"},
            "cover": None,
            "icon": None,
        }]
        set_client(client)
        result = notion_search("page")
        assert "parent" not in result
        assert "cover" not in result
        assert "icon" not in result
        assert "page-1" in result


class TestReadRichText:
    def test_read_handles_bold(self, client):
        client._blocks["page-123"] = [
            {
                "id": "block-1",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "plain_text": "Hello world",
                        "annotations": {"bold": True, "italic": False, "code": False},
                    }]
                },
            },
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "**Hello world**" in result

    def test_read_handles_italic(self, client):
        client._blocks["page-123"] = [
            {
                "id": "block-1",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "plain_text": "Hello world",
                        "annotations": {"bold": False, "italic": True, "code": False},
                    }]
                },
            },
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "*Hello world*" in result

    def test_read_handles_link(self, client):
        client._blocks["page-123"] = [
            {
                "id": "block-1",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "plain_text": "click here",
                        "annotations": {"bold": False, "italic": False, "code": False},
                        "href": "https://example.com",
                    }]
                },
            },
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "[click here](https://example.com)" in result

    def test_read_handles_link_via_text_object(self, client):
        client._blocks["page-123"] = [
            {
                "id": "block-1",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "plain_text": "click here",
                        "annotations": {"bold": False, "italic": False, "code": False},
                        "text": {"content": "click here", "link": {"url": "https://example.com"}},
                    }]
                },
            },
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "[click here](https://example.com)" in result

    def test_read_handles_bold_and_italic(self, client):
        client._blocks["page-123"] = [
            {
                "id": "block-1",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "plain_text": "Hello world",
                        "annotations": {"bold": True, "italic": True, "code": False},
                    }]
                },
            },
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "***Hello world***" in result


class TestWriteRichText:
    def test_write_handles_bold(self, client):
        set_client(client)
        notion_write("page-123", "**Hello world**")
        assert any(
            b.get("paragraph", {}).get("rich_text", [{}])[0].get("annotations", {}).get("bold", False)
            for b in client.appended
        )

    def test_write_handles_italic(self, client):
        set_client(client)
        notion_write("page-123", "*Hello world*")
        assert any(
            b.get("paragraph", {}).get("rich_text", [{}])[0].get("annotations", {}).get("italic", False)
            for b in client.appended
        )

    def test_write_handles_link(self, client):
        set_client(client)
        notion_write("page-123", "[click here](https://example.com)")
        assert any(
            b.get("paragraph", {}).get("rich_text", [{}])[0].get("text", {}).get("link", {}).get("url") == "https://example.com"
            for b in client.appended if b.get("type") == "paragraph"
        )

    def test_write_handles_bold_and_italic(self, client):
        set_client(client)
        notion_write("page-123", "***Hello world***")
        rich_texts = [
            b.get("paragraph", {}).get("rich_text", [{}])[0].get("annotations", {})
            for b in client.appended
        ]
        assert any(rt.get("bold", False) and rt.get("italic", False) for rt in rich_texts if rt)


class TestReadTables:
    def test_read_handles_table(self, client):
        client._blocks["page-123"] = [
            {
                "id": "table-block",
                "type": "table",
                "table": {
                    "has_column_header": True,
                    "has_row_header": False,
                },
            },
        ]
        client._blocks["table-block"] = [
            {
                "id": "row-1",
                "type": "table_row",
                "table_row": {
                    "cells": [
                        [{"plain_text": "Name"}],
                        [{"plain_text": "Age"}],
                    ],
                },
            },
            {
                "id": "row-2",
                "type": "table_row",
                "table_row": {
                    "cells": [
                        [{"plain_text": "Alice"}],
                        [{"plain_text": "30"}],
                    ],
                },
            },
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "| Name | Age |" in result
        assert "| Alice | 30 |" in result


class TestWriteTables:
    def test_write_creates_table_block(self, client):
        set_client(client)
        notion_write("page-123", "| Name | Age |\n| --- | --- |\n| Alice | 30 |")
        table_block = next((b for b in client.appended if b.get("type") == "table"), None)
        assert table_block is not None
        assert table_block["table"]["table_width"] == 2

    def test_write_appends_rows_to_table(self, client):
        set_client(client)
        notion_write("page-123", "| Name | Age |\n| --- | --- |\n| Alice | 30 |")
        table_block = next(b for b in client.appended if b.get("type") == "table")
        rows = table_block["table"]["children"]
        assert len(rows) == 2
        assert rows[0]["table_row"]["cells"][0][0]["text"]["content"] == "Name"
        assert rows[1]["table_row"]["cells"][0][0]["text"]["content"] == "Alice"

    def test_write_table_header_row_is_bold(self, client):
        set_client(client)
        notion_write("page-123", "| Name | Age |\n| --- | --- |\n| Alice | 30 |")
        table_block = next(b for b in client.appended if b.get("type") == "table")
        rows = table_block["table"]["children"]
        assert rows[0]["table_row"]["cells"][0][0]["annotations"]["bold"] is True
        assert rows[1]["table_row"]["cells"][0][0]["annotations"]["bold"] is False

    def test_write_table_does_not_use_placeholder(self, client):
        set_client(client)
        notion_write("page-123", "| Name | Age |\n| --- | --- |\n| Alice | 30 |")
        assert not any(
            "[TABLE:" in b.get("paragraph", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
            for b in client.appended if b.get("type") == "paragraph"
        )


class TestReadChildPage:
    def test_child_page_renders_as_markdown_link(self, client):
        client._blocks["page-123"] = [
            {
                "id": "34fd0f2f-ad60-814c-9322-dffc7e4ef305",
                "type": "child_page",
                "child_page": {"title": "Tiny Notion MCP"},
            },
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "[Subpage: Tiny Notion MCP](34fd0f2f-ad60-814c-9322-dffc7e4ef305)" in result

    def test_child_page_mixed_with_other_blocks(self, client):
        client._blocks["page-123"] = [
            {"id": "block-1", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Intro"}]}},
            {"id": "child-id", "type": "child_page", "child_page": {"title": "Sub"}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "Intro" in result
        assert "[Subpage: Sub](child-id)" in result


class TestBlockSeparators:
    def test_heading_to_paragraph_no_blank_line(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Title"}]}},
            {"id": "b2", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Body"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "# Title\nBody" in result
        assert "# Title\n\nBody" not in result

    def test_paragraph_to_heading_no_blank_line(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Intro"}]}},
            {"id": "b2", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Section"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "Intro\n## Section" in result
        assert "Intro\n\n## Section" not in result

    def test_same_list_type_no_blank_line(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "A"}]}},
            {"id": "b2", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "B"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "- A\n- B" in result
        assert "- A\n\n- B" not in result

    def test_different_list_types_blank_line(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "Bullet"}]}},
            {"id": "b2", "type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "One"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "- Bullet\n\n1. One" in result

    def test_write_blank_line_between_heading_and_text_no_empty_block(self, client):
        set_client(client)
        notion_write("page-123", "# Title\n\nSome text")
        empty_paras = [
            b for b in client.appended
            if b.get("type") == "paragraph"
            and not any(
                rt.get("text", {}).get("content", "") or rt.get("plain_text", "")
                for rt in b.get("paragraph", {}).get("rich_text", [])
            )
        ]
        assert len(empty_paras) == 0

    def test_write_blank_line_before_heading_no_empty_block(self, client):
        set_client(client)
        notion_write("page-123", "Some text\n\n# Heading")
        empty_paras = [
            b for b in client.appended
            if b.get("type") == "paragraph"
            and not any(
                rt.get("text", {}).get("content", "") or rt.get("plain_text", "")
                for rt in b.get("paragraph", {}).get("rich_text", [])
            )
        ]
        assert len(empty_paras) == 0


class TestCreatePage:
    def test_create_page_returns_toon_format(self, client):
        set_client(client)
        result = notion_create_page("parent-123", "My New Page")
        parts = result.split(" | ")
        assert len(parts) == 3
        assert parts[0] == "My New Page"

    def test_create_page_calls_pages_create_with_correct_args(self, client):
        set_client(client)
        notion_create_page("parent-123", "My New Page")
        assert len(client.created_pages) == 1
        assert client.created_pages[0]["parent_id"] == "parent-123"
        assert client.created_pages[0]["title"] == "My New Page"

    def test_create_page_with_markdown_appends_blocks(self, client):
        set_client(client)
        notion_create_page("parent-123", "My New Page", markdown="# Hello")
        assert len(client.appended) > 0

    def test_create_page_without_markdown_does_not_append(self, client):
        set_client(client)
        notion_create_page("parent-123", "My New Page")
        assert len(client.appended) == 0


class TestDividers:
    def test_read_divider_renders_as_hr(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Before"}]}},
            {"id": "b2", "type": "divider", "divider": {}},
            {"id": "b3", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "After"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "---" in result
        assert "Before\n---\nAfter" in result

    def test_write_hr_creates_divider_block(self, client):
        set_client(client)
        notion_write("page-123", "Before\n---\nAfter")
        types = [b.get("type") for b in client.appended]
        assert "divider" in types

    def test_write_hr_divider_has_correct_structure(self, client):
        set_client(client)
        notion_write("page-123", "---")
        divider = next(b for b in client.appended if b.get("type") == "divider")
        assert divider == {"object": "block", "type": "divider", "divider": {}}

    def test_divider_no_blank_line_with_adjacent_blocks(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Section"}]}},
            {"id": "b2", "type": "divider", "divider": {}},
            {"id": "b3", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Text"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "## Section\n---\nText" in result


class TestTodoList:
    def test_read_unchecked_todo(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "to_do", "to_do": {"rich_text": [{"plain_text": "Buy milk"}], "checked": False}},
        ]
        set_client(client)
        assert "[ ] Buy milk" in notion_read("page-123")

    def test_read_checked_todo(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "to_do", "to_do": {"rich_text": [{"plain_text": "Done"}], "checked": True}},
        ]
        set_client(client)
        assert "[x] Done" in notion_read("page-123")

    def test_read_consecutive_todos_no_blank_line(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "to_do", "to_do": {"rich_text": [{"plain_text": "A"}], "checked": False}},
            {"id": "b2", "type": "to_do", "to_do": {"rich_text": [{"plain_text": "B"}], "checked": False}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "[ ] A\n[ ] B" in result
        assert "[ ] A\n\n[ ] B" not in result

    def test_write_unchecked_todo(self, client):
        set_client(client)
        notion_write("page-123", "[ ] Buy milk")
        todo = next(b for b in client.appended if b.get("type") == "to_do")
        assert todo["to_do"]["checked"] is False
        assert todo["to_do"]["rich_text"][0]["text"]["content"] == "Buy milk"

    def test_write_checked_todo(self, client):
        set_client(client)
        notion_write("page-123", "[x] Done")
        todo = next(b for b in client.appended if b.get("type") == "to_do")
        assert todo["to_do"]["checked"] is True

    def test_todo_to_bullet_gets_blank_line(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "to_do", "to_do": {"rich_text": [{"plain_text": "Task"}], "checked": False}},
            {"id": "b2", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "Bullet"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        assert "[ ] Task\n\n- Bullet" in result


class TestBlockQuote:
    def test_read_quote(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "quote", "quote": {"rich_text": [{"plain_text": "Wisdom"}]}},
        ]
        set_client(client)
        assert "> Wisdom" in notion_read("page-123")

    def test_write_quote(self, client):
        set_client(client)
        notion_write("page-123", "> A wise saying")
        quote = next(b for b in client.appended if b.get("type") == "quote")
        assert quote["quote"]["rich_text"][0]["text"]["content"] == "A wise saying"

    def test_quote_roundtrip(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "quote", "quote": {"rich_text": [{"plain_text": "Roundtrip"}]}},
        ]
        set_client(client)
        result = notion_read("page-123")
        notion_write("page-123", result)
        quote = next(b for b in client.appended if b.get("type") == "quote")
        assert quote["quote"]["rich_text"][0]["text"]["content"] == "Roundtrip"


class TestCallout:
    def test_read_callout_with_emoji(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "callout", "callout": {
                "rich_text": [{"plain_text": "Watch out"}],
                "icon": {"type": "emoji", "emoji": "⚠️"},
            }},
        ]
        set_client(client)
        assert "> [⚠️] Watch out" in notion_read("page-123")

    def test_read_callout_defaults_to_bulb(self, client):
        client._blocks["page-123"] = [
            {"id": "b1", "type": "callout", "callout": {
                "rich_text": [{"plain_text": "Info"}],
                "icon": {"type": "external", "external": {"url": "..."}},
            }},
        ]
        set_client(client)
        assert "> [💡] Info" in notion_read("page-123")

    def test_write_callout(self, client):
        set_client(client)
        notion_write("page-123", "> [⚠️] Watch out")
        callout = next(b for b in client.appended if b.get("type") == "callout")
        assert callout["callout"]["icon"]["emoji"] == "⚠️"
        assert callout["callout"]["rich_text"][0]["text"]["content"] == "Watch out"

    def test_callout_not_parsed_as_quote(self, client):
        set_client(client)
        notion_write("page-123", "> [💡] A tip")
        types = [b.get("type") for b in client.appended]
        assert "callout" in types
        assert "quote" not in types

    def test_plain_quote_not_parsed_as_callout(self, client):
        set_client(client)
        notion_write("page-123", "> Just a quote")
        types = [b.get("type") for b in client.appended]
        assert "quote" in types
        assert "callout" not in types


class TestDeletePage:
    def test_delete_page_calls_page_trash(self, client):
        set_client(client)
        notion_delete_page("page-abc")
        assert "page-abc" in client.trashed

    def test_delete_page_returns_confirmation(self, client):
        set_client(client)
        result = notion_delete_page("page-abc")
        assert "page-abc" in result
        assert "Trashed" in result