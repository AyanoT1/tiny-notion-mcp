import pytest
from tiny_notion_mcp.core import (
    notion_search,
    notion_read,
    notion_write,
    set_client,
    NotionClient,
)


class MockNotionClient(NotionClient):
    def __init__(self, pages=None):
        self._pages = pages or []
        self._blocks = {}
        self.appended = []

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
        return {"object": "block", "id": "new-block"}


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
    def test_write_handles_table(self, client):
        set_client(client)
        notion_write("page-123", "| Name | Age |\n| --- | --- |\n| Alice | 30 |")
        # Table write falls back to a placeholder paragraph (Notion API limitation)
        assert not any(b.get("type") == "table" for b in client.appended)
        placeholder = next(
            (b for b in client.appended
             if b.get("type") == "paragraph"
             and "[TABLE:" in b.get("paragraph", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")),
            None,
        )
        assert placeholder is not None