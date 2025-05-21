from __future__ import annotations

import html
import json
from collections.abc import (
    AsyncIterator,  # noqa: TC003 (needed for dependency injection)
)
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlparse

import attrs
import pytest
from pydantic import BaseModel
from pydantic.fields import Field
from pytest_twisted import ensureDeferred  # type: ignore[import-untyped]
from scrapy import signals
from scrapy_spider_metadata import Args, get_spider_metadata
from web_poet import ItemPage
from web_poet.fields import field
from web_poet.page_inputs.url import (
    RequestUrl,  # noqa: TC002 (needed for dependency injection)
)
from web_poet.rules import RulesRegistry

from scrapy_crawl_maps import (
    CrawlMapSpider,
    CrawlMapSpiderCrawlMap,
    ResponseData,
)
from scrapy_crawl_maps._nodes import (
    FetchNode,
    ItemsNode,
    ProcessorNode,
    SpiderNode,
)

from . import SETTINGS, assertEqualSpiderMetadata, get_crawler

if TYPE_CHECKING:
    import builtins
    from asyncio import Queue


def serialize_items(items: list[dict[Any, Any]]) -> set[str]:
    return {json.dumps(item, sort_keys=True) for item in items}


def assert_same_items(items1: list[dict[Any, Any]], items2: list[dict[Any, Any]]):
    assert serialize_items(items1) == serialize_items(items2)


@pytest.mark.parametrize(
    ("map", "expected"),
    (
        # Shortest.
        (
            {
                "nodes": {
                    "items": {
                        "type": "items",
                        "args": {"items": [{"foo": "bar"}]},
                    },
                },
            },
            {
                "items": [{"foo": "bar"}],
                "crawl_map_stats": {
                    "items/outputs/main": 1,
                },
            },
        ),
        # Basic.
        (
            {
                "nodes": {
                    "input": {
                        "type": "urls",
                        "args": {"urls": ["data:text/html,<h1>Foo</h1>"]},
                    },
                    "fetch": {"type": "fetch"},
                    "item-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"title": {"type": "css", "value": "h1::text"}}
                        },
                    },
                },
                "edges": [
                    {"from": "input", "to": "fetch"},
                    {"from": "fetch", "to": "item-parser"},
                ],
            },
            {
                "items": [{"title": "Foo"}],
                "crawl_map_stats": {
                    "fetch/inputs/main": 1,
                    "fetch/outputs/main": 1,
                    "input/outputs/main": 1,
                    "item-parser/inputs/main": 1,
                    "item-parser/outputs/main": 1,
                },
            },
        ),
        # You can link multiple inputs to a single output.
        (
            {
                "nodes": {
                    "input-1": {
                        "type": "urls",
                        "args": {"urls": ["data:text/html,<h1>Foo</h1>"]},
                    },
                    "input-2": {
                        "type": "urls",
                        "args": {"urls": ["data:text/html,<h1>Bar</h1>"]},
                    },
                    "fetch": {"type": "fetch"},
                    "item-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"title": {"type": "css", "value": "h1::text"}}
                        },
                    },
                },
                "edges": [
                    {"from": "input-1", "to": "fetch"},
                    {"from": "input-2", "to": "fetch"},
                    {"from": "fetch", "to": "item-parser"},
                ],
            },
            {
                "items": [{"title": "Foo"}, {"title": "Bar"}],
                "crawl_map_stats": {
                    "fetch/inputs/main": 2,
                    "fetch/outputs/main": 2,
                    "input-1/outputs/main": 1,
                    "input-2/outputs/main": 1,
                    "item-parser/inputs/main": 2,
                    "item-parser/outputs/main": 2,
                },
            },
        ),
        # You can define a map that performs no download and yields no items,
        # however pointless.
        (
            {
                "nodes": {
                    "urls": {"type": "urls", "args": {"urls": ["data:,"]}},
                },
                "edges": [],
            },
            {
                "items": [],
                "crawl_map_stats": {
                    "urls/outputs/main": 1,
                },
            },
        ),
        # You can use item-follow.
        (
            {
                "nodes": {
                    "items": {
                        "type": "items",
                        "args": {
                            "items": [
                                {
                                    "items": ["data:text/html,<h1>Bar</h1>"],
                                    "nextPage": "data:text/html,<h1>Foo</h1>",
                                }
                            ]
                        },
                    },
                    "follow-items": {
                        "type": "item-follow",
                        "args": {"url_jmes": "items"},
                    },
                    "follow-next": {
                        "type": "item-follow",
                        "args": {"url_jmes": "nextPage"},
                    },
                    "fetch": {"type": "fetch"},
                    "item-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"title": {"type": "css", "value": "h1::text"}}
                        },
                    },
                },
                "edges": [
                    {"from": "items", "to": "follow-items"},
                    {"from": "items", "to": "follow-next"},
                    {"from": "follow-items", "to": "fetch"},
                    {"from": "follow-next", "to": "fetch"},
                    {"from": "fetch", "to": "item-parser"},
                ],
            },
            {
                "items": [{"title": "Foo"}, {"title": "Bar"}],
                "crawl_map_stats": {
                    "items/outputs/main": 1,
                    "follow-items/inputs/main": 1,
                    "follow-items/outputs/main": 1,
                    "follow-next/inputs/main": 1,
                    "follow-next/outputs/main": 1,
                    "fetch/inputs/main": 2,
                    "fetch/outputs/main": 2,
                    "item-parser/inputs/main": 2,
                    "item-parser/outputs/main": 2,
                },
            },
        ),
        # Defining links between incompatible components causes a ValueError
        # and for the spider to close.
        (
            {
                "nodes": {
                    "input": {"type": "urls", "args": {"urls": ["data:,"]}},
                    "item-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"title": {"type": "css", "value": "h1::text"}}
                        },
                    },
                },
                "edges": [{"from": "input", "to": "item-parser"}],
            },
            {
                "finish_reason": "bad_crawl_map",
                "items": [],
                "crawl_map_stats": {},
            },
        ),
        # Support recursivity.
        (
            {
                "nodes": {
                    "input": {
                        "type": "urls",
                        "args": {"urls": ['data:,<a href="data:,">']},
                    },
                    "fetch": {"type": "fetch"},
                    "follow": {
                        "type": "selector-follow",
                        "args": {
                            "selectors": [{"type": "css", "value": "a::attr(href)"}]
                        },
                    },
                },
                "edges": [
                    {"from": "input", "to": "fetch"},
                    {"from": "fetch", "to": "follow"},
                    {"from": "follow", "to": "fetch"},
                ],
            },
            {
                "items": [],
                "crawl_map_stats": {
                    "input/outputs/main": 1,
                    "fetch/inputs/main": 2,
                    "fetch/outputs/main": 2,
                    "follow/inputs/main": 2,
                    "follow/outputs/main": 1,
                },
            },
        ),
        # item-follow accepts a recursion limit, implemented with
        # ProcessorNode.process_request().
        #
        # Without recursion limit:
        (
            {
                "nodes": {
                    "items": {
                        "type": "items",
                        "args": {
                            "items": [
                                {
                                    "next": 'data:text/html,<h1>Foo</h1><a href="{data}"></a>'.format(
                                        data=html.escape("data:text/html,<h1>Bar</h1>")
                                    ),
                                }
                            ]
                        },
                    },
                    "follow-next": {
                        "type": "item-follow",
                        "args": {"url_jmes": "next"},
                    },
                    "fetch": {"type": "fetch"},
                    "item-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"title": {"type": "css", "value": "h1::text"}}
                        },
                    },
                    "next-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"next": {"type": "css", "value": "a::attr(href)"}}
                        },
                    },
                },
                "edges": [
                    {"from": "items", "to": "follow-next"},
                    {"from": "follow-next", "to": "fetch"},
                    {"from": "fetch", "to": "item-parser"},
                    {"from": "fetch", "to": "next-parser"},
                    {"from": "next-parser", "to": "follow-next"},
                ],
            },
            {
                "items": [{"title": "Foo"}, {"title": "Bar"}],
                "crawl_map_stats": {
                    "items/outputs/main": 1,
                    "follow-next/inputs/main": 3,
                    "follow-next/outputs/main": 2,
                    "fetch/inputs/main": 2,
                    "fetch/outputs/main": 2,
                    "item-parser/inputs/main": 2,
                    "item-parser/outputs/main": 2,
                    "next-parser/inputs/main": 2,
                    "next-parser/outputs/main": 2,
                },
            },
        ),
        # With recursion limit:
        (
            {
                "nodes": {
                    "items": {
                        "type": "items",
                        "args": {
                            "items": [
                                {
                                    "next": 'data:text/html,<h1>Foo</h1><a href="{data}"></a>'.format(
                                        data=html.escape("data:text/html,<h1>Bar</h1>")
                                    ),
                                }
                            ]
                        },
                    },
                    "follow-next": {
                        "type": "item-follow",
                        "args": {"url_jmes": "next", "max_recursion": 0},
                    },
                    "fetch": {"type": "fetch"},
                    "item-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"title": {"type": "css", "value": "h1::text"}}
                        },
                    },
                    "next-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"next": {"type": "css", "value": "a::attr(href)"}}
                        },
                    },
                },
                "edges": [
                    {"from": "items", "to": "follow-next"},
                    {"from": "follow-next", "to": "fetch"},
                    {"from": "fetch", "to": "item-parser"},
                    {"from": "fetch", "to": "next-parser"},
                    {"from": "next-parser", "to": "follow-next"},
                ],
            },
            {
                "items": [{"title": "Foo"}],
                "crawl_map_stats": {
                    "items/outputs/main": 1,
                    "follow-next/inputs/main": 2,
                    "follow-next/outputs/main": 1,
                    "fetch/inputs/main": 1,
                    "fetch/outputs/main": 1,
                    "item-parser/inputs/main": 1,
                    "item-parser/outputs/main": 1,
                    "next-parser/inputs/main": 1,
                    "next-parser/outputs/main": 1,
                },
            },
        ),
        # With a high-enough recursion limit:
        (
            {
                "nodes": {
                    "items": {
                        "type": "items",
                        "args": {
                            "items": [
                                {
                                    "next": 'data:text/html,<h1>Foo</h1><a href="{data}"></a>'.format(
                                        data=html.escape("data:text/html,<h1>Bar</h1>")
                                    ),
                                }
                            ]
                        },
                    },
                    "follow-next": {
                        "type": "item-follow",
                        "args": {"url_jmes": "next", "max_recursion": 1},
                    },
                    "fetch": {"type": "fetch"},
                    "item-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"title": {"type": "css", "value": "h1::text"}}
                        },
                    },
                    "next-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"next": {"type": "css", "value": "a::attr(href)"}}
                        },
                    },
                },
                "edges": [
                    {"from": "items", "to": "follow-next"},
                    {"from": "follow-next", "to": "fetch"},
                    {"from": "fetch", "to": "item-parser"},
                    {"from": "fetch", "to": "next-parser"},
                    {"from": "next-parser", "to": "follow-next"},
                ],
            },
            {
                "items": [{"title": "Foo"}, {"title": "Bar"}],
                "crawl_map_stats": {
                    "items/outputs/main": 1,
                    "follow-next/inputs/main": 3,
                    "follow-next/outputs/main": 2,
                    "fetch/inputs/main": 2,
                    "fetch/outputs/main": 2,
                    "item-parser/inputs/main": 2,
                    "item-parser/outputs/main": 2,
                    "next-parser/inputs/main": 2,
                    "next-parser/outputs/main": 2,
                },
            },
        ),
    ),
)
@ensureDeferred
async def test_main(map, expected):
    crawler = get_crawler()
    items = []

    def track_item(item, response, spider):
        items.append(item)

    crawler.signals.connect(track_item, signal=signals.item_scraped)
    await crawler.crawl(map=json.dumps(map))

    assert_same_items(items, expected["items"])
    stat_prefix = "crawl_maps/nodes/"
    assert crawler.stats is not None
    stats = crawler.stats.get_stats()
    crawl_map_stats = {
        k[len(stat_prefix) :]: v for k, v in stats.items() if k.startswith(stat_prefix)
    }
    assert crawl_map_stats == expected["crawl_map_stats"]

    expected_finish_reason = expected.get("finish_reason", "finished")
    assert stats["finish_reason"] == expected_finish_reason
    assert "log_count/WARNING" not in stats
    if expected_finish_reason == "finished":
        assert "log_count/ERROR" not in stats
    else:
        assert stats["log_count/ERROR"] == 1


@pytest.mark.parametrize(
    ("map", "expected"),
    (
        # Unknown node type.
        (
            {
                "nodes": {
                    "items": {
                        "type": "unknown",
                    },
                },
            },
            {
                "error": "Unknown node type: 'unknown'",
            },
        ),
    ),
)
@ensureDeferred
async def test_bad_maps(map, expected, caplog):
    crawler = get_crawler()
    caplog.clear()
    await crawler.crawl(map=json.dumps(map))
    assert expected["error"] in caplog.text
    assert crawler.stats is not None
    stats = crawler.stats.get_stats()
    assert stats["finish_reason"] == "bad_crawl_map"


EXCEPTION = ValueError("foo")


class BadItemsNode(ItemsNode):
    type = "bad-items"

    async def process(
        self,
        *,
        inputs: dict[str, AsyncIterator[Any]],
        outputs: dict[str, Queue[Any]],
        response_data: ResponseData | None,
    ) -> None:
        raise EXCEPTION


class BadInputFetchNode(FetchNode):
    type = "bad-input-fetch"

    async def process_input(
        self, *, inputs: dict[str, AsyncIterator[Any]]
    ) -> AsyncIterator[Any]:
        raise EXCEPTION
        yield


class BadOutputFetchNode(FetchNode):
    type = "bad-output-fetch"

    async def process_output(
        self, *, response_data: ResponseData, outputs: dict[str, Queue[Any]]
    ) -> None:
        raise EXCEPTION


@pytest.mark.parametrize(
    ("extra_node_types", "map", "expected"),
    (
        # Node.process()
        (
            {BadItemsNode},
            {
                "nodes": {
                    "items": {
                        "type": "bad-items",
                        "args": {"items": [{"foo": "bar"}]},
                    },
                },
            },
            {
                "exception": EXCEPTION,
            },
        ),
        # SpiderNode.process_input()
        (
            {BadInputFetchNode},
            {
                "nodes": {
                    "input": {
                        "type": "urls",
                        "args": {"urls": ["data:text/html,<h1>Foo</h1>"]},
                    },
                    "fetch": {"type": "bad-input-fetch"},
                    "item-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"title": {"type": "css", "value": "h1::text"}}
                        },
                    },
                },
                "edges": [
                    {"from": "input", "to": "fetch"},
                    {"from": "fetch", "to": "item-parser"},
                ],
            },
            {
                "exception": EXCEPTION,
            },
        ),
        # SpiderNode.process_output()
        (
            {BadOutputFetchNode},
            {
                "nodes": {
                    "input": {
                        "type": "urls",
                        "args": {"urls": ["data:text/html,<h1>Foo</h1>"]},
                    },
                    "fetch": {"type": "bad-output-fetch"},
                    "item-parser": {
                        "type": "selector-parser",
                        "args": {
                            "map": {"title": {"type": "css", "value": "h1::text"}}
                        },
                    },
                },
                "edges": [
                    {"from": "input", "to": "fetch"},
                    {"from": "fetch", "to": "item-parser"},
                ],
            },
            {
                "exception": EXCEPTION,
            },
        ),
    ),
)
@ensureDeferred
async def test_node_exceptions(
    extra_node_types: set[type[ProcessorNode | SpiderNode]], map, expected, caplog
):
    """Unhandled exceptions in node methods must not make the crawler hang, and
    must be reported with a traceback in an error log message."""

    class TestSpiderCrawlMap(CrawlMapSpiderCrawlMap):
        node_types = CrawlMapSpiderCrawlMap.node_types | extra_node_types

    class TestSpiderParams(BaseModel):
        map: TestSpiderCrawlMap = Field()

    class TestSpider(CrawlMapSpider, Args[TestSpiderParams]):
        pass

    crawler = get_crawler(spider_cls=TestSpider)
    caplog.clear()
    await crawler.crawl(map=json.dumps(map))
    exception = expected["exception"]
    assert f"Error while processing a node: {exception}" in caplog.text  # message
    assert f"{exception.__class__.__name__}: {exception}" in caplog.text  # traceback


@ensureDeferred
async def test_poet():
    """Test a crawl map that uses a page object and does not require a response
    (i.e. uses DummyResponse)."""

    url = "https://toscrape.com"
    registry = RulesRegistry()

    @attrs.define
    class Object:
        url: str

    @registry.handle_urls(urlparse(url).netloc)
    @attrs.define
    class ObjectPage(ItemPage[Object]):
        request_url: RequestUrl

        @field
        def url(self) -> str:
            return str(self.request_url)

    class ObjectNode(ProcessorNode):
        type = "object"
        spec: ClassVar[dict[str, Any]] = {
            "inputs": {
                "main": {
                    "type": "response",
                },
            },
            "outputs": {
                "main": {
                    "type": "item",
                },
            },
        }
        deps: ClassVar[set[builtins.type]] = {Object}

        async def process(
            self,
            *,
            inputs: dict[str, AsyncIterator[Any]],
            outputs: dict[str, Queue[Any]],
            response_data: ResponseData | None,
        ) -> None:
            async for data in inputs["main"]:
                assert data is not None
                await outputs["main"].put(data[Object])

    class TestSpiderCrawlMap(CrawlMapSpiderCrawlMap):
        node_types: ClassVar[set[type[ProcessorNode | SpiderNode]]] = (
            CrawlMapSpiderCrawlMap.node_types | {ObjectNode}
        )

    class TestSpiderParams(BaseModel):
        map: TestSpiderCrawlMap = Field()

    class TestSpider(CrawlMapSpider, Args[TestSpiderParams]):
        pass

    settings = {
        **SETTINGS,
        "SCRAPY_POET_RULES": registry.get_rules(),
    }
    map = {
        "nodes": {
            "input": {
                "type": "urls",
                "args": {"urls": [url]},
            },
            "fetch": {"type": "fetch"},
            "object": {
                "type": "object",
            },
        },
        "edges": [
            {"from": "input", "to": "fetch"},
            {"from": "fetch", "to": "object"},
        ],
    }
    crawler = get_crawler(spider_cls=TestSpider, settings=settings)
    items = []

    def track_item(item, response, spider):
        items.append(item)

    crawler.signals.connect(track_item, signal=signals.item_scraped)
    await crawler.crawl(map=json.dumps(map))

    assert len(items) == 1
    assert items[0] == Object(url=url)

    assert crawler.stats is not None
    stats = crawler.stats.get_stats()
    assert "log_count/ERROR" not in stats
    assert "downloader/request_count" not in stats


@pytest.mark.parametrize(
    ("spider_cls", "metadata"),
    (
        (
            CrawlMapSpider,
            {
                "description": "Template for spiders that follow a crawl map.",
                "param_schema": {
                    "properties": {
                        "map": {
                            "description": "Definition of the steps that the spider must follow.",
                            "node_groups": {
                                "input": {"order": 0, "title": "Input"},
                                "fetch": {"order": 1, "title": "Fetch"},
                                "parse": {"order": 2, "title": "Parse"},
                                "follow": {"order": 3, "title": "Follow"},
                            },
                            "node_types": {
                                "fetch": {
                                    "inputs": {"main": {"type": "request"}},
                                    "outputs": {"main": {"type": "response"}},
                                },
                                "item-follow": {
                                    "inputs": {"main": {"type": "item"}},
                                    "outputs": {"main": {"type": "request"}},
                                    "param_schema": {
                                        "properties": {
                                            "max_recursion": {
                                                "default": -1,
                                                "description": (
                                                    "Limits how many times a given chain of "
                                                    "requests can go through this node.\n"
                                                    "\n"
                                                    "-1 means no limit.\n"
                                                    "\n"
                                                    "It is useful, for example, to limit "
                                                    "pagination to the first few pages."
                                                ),
                                                "title": "Maximum recursion",
                                                "type": "integer",
                                            },
                                            "url_jmes": {
                                                "description": (
                                                    "Determines which URLs to follow.\n"
                                                    "\n"
                                                    "It is a JMESPath_ query that matches a "
                                                    "URL or a list of URLs.\n"
                                                    "\n"
                                                    ".. _JMESPath: https://jmespath.org/"
                                                ),
                                                "title": "URL JMESPath query",
                                                "type": "string",
                                            },
                                        },
                                        "required": [
                                            "url_jmes",
                                        ],
                                        "title": "ItemFollowNodeParams",
                                        "type": "object",
                                    },
                                },
                                "items": {
                                    "outputs": {"main": {"type": "item"}},
                                    "param_schema": {
                                        "properties": {
                                            "items": {
                                                "description": (
                                                    "JSON array of JSON objects to output as items.\n"
                                                    "\n"
                                                    "For example:\n"
                                                    "\n"
                                                    ".. code-block:: json\n"
                                                    "\n"
                                                    '    [{"foo": "bar"}]\n'
                                                ),
                                                "items": {
                                                    "additionalProperties": True,
                                                    "type": "object",
                                                },
                                                "title": "Items",
                                                "type": "array",
                                            }
                                        },
                                        "required": ["items"],
                                        "title": "ItemsNodeParams",
                                        "type": "object",
                                    },
                                },
                                "selector-follow": {
                                    "inputs": {"main": {"type": "response"}},
                                    "outputs": {"main": {"type": "request"}},
                                    "param_schema": {
                                        "properties": {
                                            "selectors": {
                                                "description": (
                                                    "JSON array of JSON "
                                                    "objects that each define "
                                                    "a selector type and "
                                                    "value. For example: "
                                                    '[{"type": "css", '
                                                    '"value": '
                                                    '"a::attr(href)"}].\n'
                                                    "\n"
                                                    "Each field query can "
                                                    'also define a "getter" '
                                                    "key, which is the name "
                                                    "of the selector method "
                                                    'to use: "getall" '
                                                    '(default) or "get".'
                                                ),
                                                "items": {
                                                    "additionalProperties": {
                                                        "type": "string"
                                                    },
                                                    "type": "object",
                                                },
                                                "title": "Selector list",
                                                "type": "array",
                                            }
                                        },
                                        "required": ["selectors"],
                                        "title": "SelectorFollowNodeParams",
                                        "type": "object",
                                    },
                                },
                                "selector-parser": {
                                    "inputs": {"main": {"type": "response"}},
                                    "outputs": {"main": {"type": "item"}},
                                    "param_schema": {
                                        "properties": {
                                            "map": {
                                                "additionalProperties": {
                                                    "additionalProperties": {
                                                        "type": "string"
                                                    },
                                                    "type": "object",
                                                },
                                                "description": (
                                                    "JSON object "
                                                    "mapping field "
                                                    "names to JSON "
                                                    "objects that "
                                                    "define a selector "
                                                    "type and value. "
                                                    "For example: "
                                                    '{"name": {"type": "css", '
                                                    '"value": '
                                                    '".name::text"}.\n'
                                                    "\n"
                                                    "Each field query "
                                                    "can also define a "
                                                    '"getter" key, '
                                                    "which is the name "
                                                    "of the selector "
                                                    "method to use: "
                                                    '"get" (default) '
                                                    'or "getall".'
                                                ),
                                                "title": "Selector map",
                                                "type": "object",
                                            }
                                        },
                                        "required": ["map"],
                                        "title": "SelectorParserNodeParams",
                                        "type": "object",
                                    },
                                },
                                "urls": {
                                    "outputs": {"main": {"type": "request"}},
                                    "param_schema": {
                                        "properties": {
                                            "urls": {
                                                "description": (
                                                    "Input URLs.\n"
                                                    "\n"
                                                    "Define 1 absolute URL "
                                                    "(e.g. including the "
                                                    "http(s) prefix) per "
                                                    "line.\n"
                                                    "\n"
                                                    "Example: "
                                                    "https://toscrape.com/"
                                                ),
                                                "items": {
                                                    "type": "string",
                                                },
                                                "title": "URLs",
                                                "type": "array",
                                            },
                                        },
                                        "required": ["urls"],
                                        "title": "UrlsNodeParams",
                                        "type": "object",
                                    },
                                },
                            },
                            "properties": {
                                "edges": {
                                    "items": {
                                        "properties": {
                                            "from": {
                                                "oneOf": [
                                                    {"type": "string"},
                                                    {
                                                        "items": {"type": "string"},
                                                        "maxItems": 2,
                                                        "minItems": 2,
                                                        "type": "array",
                                                    },
                                                ]
                                            },
                                            "required": ["from", "to"],
                                            "to": {
                                                "oneOf": [
                                                    {"type": "string"},
                                                    {
                                                        "items": {"type": "string"},
                                                        "maxItems": 2,
                                                        "minItems": 2,
                                                        "type": "array",
                                                    },
                                                ]
                                            },
                                        },
                                        "type": "object",
                                    },
                                    "type": "array",
                                },
                                "nodes": {
                                    "properties": {
                                        "args": {"type": "object"},
                                        "type": {"type": "string"},
                                    },
                                    "required": ["type"],
                                    "type": "object",
                                },
                                "required": ["nodes"],
                            },
                            "title": "Crawl map",
                            "type": "object",
                        }
                    },
                    "required": ["map"],
                    "title": "CrawlMapSpiderParams",
                    "type": "object",
                },
                "template": True,
                "title": "Crawl Map Spider",
            },
        ),
    ),
)
@ensureDeferred
async def test_metadata(spider_cls, metadata):
    assertEqualSpiderMetadata(get_spider_metadata(spider_cls, normalize=True), metadata)
