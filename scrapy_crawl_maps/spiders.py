from __future__ import annotations

from collections.abc import (
    AsyncIterator,  # noqa: TC003 (needed for dependency injection)
)
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field
from scrapy import Request, Spider
from scrapy.exceptions import CloseSpider
from scrapy.http.response import Response
from scrapy.utils.python import global_object_name
from scrapy_poet import (  # type: ignore[import-untyped]
    DummyResponse,  # noqa: TC002 (needed for dependency injection)
    DynamicDeps,  # noqa: TC002 (needed for dependency injection)
)
from scrapy_spider_metadata import Args
from twisted.python.failure import Failure

from ._maps import CrawlMap
from ._nodes import (
    FetchNode,
    ItemFollowNode,
    ItemsNode,
    ProcessorNode,
    SelectorFollowNode,
    SelectorParserNode,
    SpiderNode,
    UrlsNode,
)

if TYPE_CHECKING:
    from typing_extensions import Self  # Python 3.11+


class ResponseData(dict):
    """Dictionary of response data where keys are data types (e.g.
    :class:`HtmlResponse`) and values are the corresponding objects."""

    @classmethod
    def from_objects(cls, *objects) -> Self:
        """Build a :class:`ResponseData` instance from *objects*.

        See :meth:`CrawlMap.parse` for examples.
        """
        response_data = cls()
        for object in objects:
            response_data[object.__class__] = object
        return response_data

    @property
    def response(self) -> Response | None:
        """:class:`Response` object, if any.

        Raises an exception if no :class:`Response` class or subclass is found
        but a :exc:`~twisted.python.failure.Failure` class or subclass is found
        instead, which may happen e.g. if an unhandled exception is raised
        during request processing (see :attr:`~scrapy.Request.errback`).
        """
        for type, value in self.items():
            if issubclass(type, Response):
                return value
        for type, value in self.items():
            if issubclass(type, Failure):
                raise value.value
        return None

    @property
    def meta(self) -> dict[str, Any]:
        """:attr:`~scrapy.Request.meta` from the source request."""
        for type, value in self.items():
            if issubclass(type, (Failure, Response)):
                return value.request.meta
        raise AssertionError("There should always be a meta attribute")


class CrawlMapSpiderCrawlMap(CrawlMap):  # noqa: D101
    node_groups: ClassVar[dict[str, Any]] = {
        "input": {"title": "Input", "order": 0},
        "fetch": {"title": "Fetch", "order": 1},
        "parse": {"title": "Parse", "order": 2},
        "follow": {"title": "Follow", "order": 3},
    }
    node_types: ClassVar[set[type[ProcessorNode | SpiderNode]]] = {
        FetchNode,
        ItemFollowNode,
        ItemsNode,
        SelectorFollowNode,
        SelectorParserNode,
        UrlsNode,
    }


class CrawlMapSpiderMapParam(BaseModel):  # noqa: D101
    map: CrawlMapSpiderCrawlMap = Field(
        title="Crawl map",
        description="Definition of the steps that the spider must follow.",
    )


class CrawlMapSpiderParams(  # noqa: D101
    CrawlMapSpiderMapParam,
):
    pass


class CrawlMapBaseSpider(Spider):
    """Base class for spiders that follow a :ref:`crawl map <map>`.

    Subclasses must :ref:`define a spider parameter <define-params>` with
    :class:`CrawlMap` or a subclass of it as type.
    """

    def _load_crawl_map(self) -> None:
        if not isinstance(self, Args):
            raise TypeError(
                f"{global_object_name(self.__class__)} is a subclass of "
                f"{global_object_name(CrawlMapBaseSpider)}, so it must also "
                f"subclass scrapy_spider_metadata.Args to specify its spider "
                f"parameters, including one with CrawlMap or a subclass as "
                f"type."
            )
        for v in self.args.model_dump().values():
            if isinstance(v, CrawlMap):
                try:
                    v.prepare(crawler=self.crawler)
                except Exception as exception:
                    self.logger.error(
                        f"Error while loading the crawl map: {exception}", exc_info=True
                    )
                    raise CloseSpider("bad_crawl_map") from exception
                self._crawl_map = v
                break
        else:
            self.logger.error(
                f"No crawl-map parameter found in {global_object_name(self.__class__)}"
            )
            raise CloseSpider("no_crawl_map_param")

    def _process_item_or_request(self, item_or_request):
        if isinstance(item_or_request, Request):
            deps = item_or_request.meta.get("inject", [])
            for dep in list(deps):
                if issubclass(dep, Response):
                    deps.remove(dep)
                    callback = self.callback
                    break
            else:
                callback = self.callback_for_dummy_response
            item_or_request = item_or_request.replace(
                callback=callback,
                errback=self.errback,
            )
        return item_or_request

    async def start(self) -> AsyncIterator[Any]:  # noqa: D102
        try:
            self._load_crawl_map()
        except CloseSpider:
            assert self.crawler.engine is not None
            self.crawler.engine.close_spider(self, reason="bad_crawl_map")
            return
        async for item_or_request in self._crawl_map.start():
            yield self._process_item_or_request(item_or_request)

    async def callback(  # noqa: D102
        self, response: Response, /, *, deps: DynamicDeps
    ) -> AsyncIterator[Any]:
        deps[response.__class__] = response
        response_data = ResponseData.from_objects(*deps.values())
        async for item_or_request in self._crawl_map.parse(response_data=response_data):
            yield self._process_item_or_request(item_or_request)

    async def callback_for_dummy_response(  # noqa: D102
        self, response: DummyResponse, /, *, deps: DynamicDeps
    ) -> AsyncIterator[Any]:
        async for item_or_request in self.callback(response, deps=deps):
            yield item_or_request

    async def errback(self, failure: Failure, /) -> AsyncIterator[Any]:  # noqa: D102
        response_data = ResponseData.from_objects(failure)
        async for item_or_request in self._crawl_map.parse(response_data=response_data):
            yield self._process_item_or_request(item_or_request)


class CrawlMapSpider(Args[CrawlMapSpiderParams], CrawlMapBaseSpider):
    """Template spider for spiders that follow a :ref:`crawl map <map>`.

    Supports all :ref:`built-in node types <builtin-node-types>`.
    """

    name: str = "map"
    metadata: ClassVar[dict[str, Any]] = {
        "title": "Crawl Map Spider",
        "description": "Template for spiders that follow a crawl map.",
        "template": True,
    }
