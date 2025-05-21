from __future__ import annotations

import re
from abc import abstractmethod
from logging import getLogger
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    TypeVar,
    cast,
)

import jmespath
from itemadapter import ItemAdapter
from pydantic import BaseModel, Field, ValidationError, field_validator
from scrapy import Request
from scrapy.http.response import Response
from scrapy.utils.defer import deferred_to_future
from scrapy.utils.python import global_object_name

# TODO: If we are OK with this approach, make an upstream release publishing
# these methods.
from scrapy_spider_metadata._utils import get_generic_param, normalize_param_schema

if TYPE_CHECKING:
    import builtins
    from asyncio import Queue
    from collections.abc import AsyncIterator

    from scrapy.crawler import Crawler

    from ._maps import CrawlMap
    from .spiders import ResponseData

logger = getLogger(__name__)

# Validation #----------------------------------------------------------------#

URL_PATTERN = r"^(?:https?://[^:/\s]+(:\d{1,5})?(/[^\s]*)*(#[^\s]*)?|data:.*?)$"


def validate_url_list(value: list[str] | str) -> list[str]:
    """Validate a list of URLs.

    If a string is received as input, it is split into multiple strings
    on new lines.

    List items that do not match a URL pattern trigger a warning and are
    removed from the list. If all URLs are invalid, validation fails.
    """
    if isinstance(value, str):
        value = value.split("\n")
    if not value:
        return value
    result = []
    for v in value:
        v = v.strip()  # noqa: PLW2901
        if not v:
            continue
        if not re.search(URL_PATTERN, v):
            logger.warning(
                f"{v!r}, from the 'urls' spider argument, is not a "
                f"valid URL and will be ignored."
            )
            continue
        result.append(v)
    if not result:
        raise ValueError(f"No valid URL found in {value!r}")
    return result


# Base classes #--------------------------------------------------------------#


class _Node:
    #: :ref:`Node type <node-type>` used in :ref:`crawl maps <map>` to
    #: instantiate nodes of this type.
    type: ClassVar[str]

    #: Supported :ref:`input and output ports <port>`.
    spec: ClassVar[dict[str, Any]]

    _persistent_meta_prefix = "_crawl_map_presistent_"

    def __init__(self, *, id: str, map: CrawlMap, crawler: Crawler, args: Any):
        #: ID of this instance of the node type, as :ref:`defined <node-id>` in
        #: the :ref:`crawl map <map>`.
        self.id: str = id

        #: :ref:`Crawl map <map>` that this node belongs to.
        self.map: CrawlMap = map

        #: Running :class:`~scrapy.crawler.Crawler`.
        #:
        #: Can be useful to access :ref:`settings <topics-settings>`.
        self.crawler = crawler

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id!r})"

    @property
    def meta_key(self) -> str:
        """Key that can be set in :attr:`Request.meta
        <scrapy.Request.meta>` to store sticky, node-specific metadata.

        The key is guaranteed to be unique for this node instance. It is also
        copied from responses to follow-up requests, even in subsets of the
        crawl map where this node is not present.

        It can be useful, for example, to limit how many times a request and
        its follow-up requests can go through this node:

        .. code-block:: python

            class FollowNextNode(Node):
                def process_request(self, request, /, *, response_data=None):
                    request = super().process_request(request, response_data=response_data)
                    meta = request.meta.get(self.meta_key, {})
                    meta["depth"] = meta.get("depth", -1) + 1
                    request.meta[self.meta_key] = meta

                async def process(self, inputs, outputs):
                    async for response_data in inputs["main"]:
                        meta = response_data.meta.get(self.meta_key, {})
                        if meta["depth"] > 0:
                            continue
                        request = Request(response_data.response.css("next::attr(href)").get())
                        await outputs["main"].put(request)
        """
        return f"{self._persistent_meta_prefix}_{self.id}"


class ProcessorNode(_Node):
    """Base class for most crawl map nodes.

    Subclasses must define :attr:`type` and :attr:`spec` and implement the
    :meth:`process` method. They can also optionally implement the
    process_request() method to process requests whose response will affect
    them.
    """

    deps: ClassVar[set[type]] = set()

    @abstractmethod
    async def process(
        self,
        *,
        inputs: dict[str, AsyncIterator[Any]],
        outputs: dict[str, Queue[Any]],
        response_data: ResponseData | None,
    ) -> None:
        """Process *inputs* into *outputs*.

        *inputs* is a dictionary of input port iterators, where keys are input
        port IDs and values are asynchronous iterators that yield input data.

        *outputs* is a dictionary of output port queues, where keys are output
        port IDs and values are queues where you should put any output data.

        This method may be called multiple times.
        """
        raise NotImplementedError(
            f"{global_object_name(self.__class__)} does not implement a "
            f"process() method"
        )

    def process_request(
        self, request: Request, /, *, response_data: ResponseData | None = None
    ) -> Request:
        """Process a request whose response will affect this node.

        This method is called for each request yielded by the closest earlier
        :class:`SpiderNode` connected to this node. It can be used, for
        example, to set metadata on the request. See :meth:`meta_key`.

        *response_data* is the response data that triggered this request, not
        the response to *request* itself. It is ``None`` for start requests.

        It must return the original request (e.g. with in-place modifications)
        or a new one (e.g. created with :meth:`~scrapy.Request.replace`).
        """
        if not self.deps:
            return request
        deps = request.meta.setdefault("inject", [])
        for dep in self.deps:
            if dep not in deps:
                deps.append(dep)
        return request


class SpiderNode(_Node):
    """Base class for crawl map nodes that can yield items and requests and
    process the response to requests that it yields.

    Subclasses must define :attr:`type` and :attr:`spec` and implement the
    :meth:`process_input` and :meth:`process_output` methods.
    """

    @abstractmethod
    async def process_input(
        self,
        *,
        inputs: dict[str, AsyncIterator[Any]],
    ) -> AsyncIterator[Any]:
        """Process *inputs* and yield :ref:`items <items>` and :ref:`requests
        <topics-request-response>`.

        ..
            TODO: Switch the reference to "requests" after the release of
            Scrapy #6715.

        *inputs* is a dictionary of input port iterators, where keys are input
        port IDs and values are asynchronous iterators that yield input data.

        This method may be called multiple times.
        """
        raise NotImplementedError(
            f"{global_object_name(self.__class__)} does not implement a "
            f"process_input() method"
        )
        yield

    @abstractmethod
    async def process_output(
        self,
        *,
        response_data: ResponseData,
        outputs: dict[str, Queue[Any]],
    ) -> None:
        """Process the *response_data* input *outputs*.

        *response_data* is response data received for a request yielded from
        :meth:`process_input`.

        *outputs* is a dictionary of output port queues, where keys are output
        port IDs and values are queues where you should put any output data.

        This method is called once per *response_data*. That is usually once per request
        yielded from :meth:`process_input`, but it may be fewer times if a
        request is dropped (e.g. duplicate requests).
        """
        raise NotImplementedError(
            f"{global_object_name(self.__class__)} does not implement a "
            f"process_output() method"
        )


ParamSpecT = TypeVar("ParamSpecT", bound=BaseModel)


class NodeArgs(Generic[ParamSpecT]):
    """Validates and type-converts :ref:`node arguments <node-args>` into the
    :attr:`args` instance attribute according to the :ref:`parameter
    specification <node-params>`."""

    def __init__(self, *pargs: Any, args, **kwargs: Any):
        param_model = get_generic_param(self.__class__, NodeArgs)
        assert param_model is not None
        try:
            #: Node arguments, as :ref:`defined <node-args>` in the :ref:`crawl
            #: map <map>`.
            self.args: ParamSpecT = param_model(**args)
        except ValidationError as e:
            logger.error(f"Node parameter validation failed: {e}")
            raise
        kwargs["args"] = args
        super().__init__(*pargs, **kwargs)

    @classmethod
    def get_param_schema(cls, normalize: bool = False) -> dict[Any, Any]:
        """Return a :class:`dict` with the :ref:`parameter definition
        <define-params>` as `JSON Schema`_.

        .. _JSON Schema: https://json-schema.org/

        If *normalize* is ``True``, the returned schema will be the same
        regardless of whether you are using Pydantic 1.x or Pydantic 2.x. The
        normalized schema may not match the output of any Pydantic version, but
        it will be functionally equivalent where possible.
        """
        param_model = get_generic_param(cls, NodeArgs)
        assert param_model is not None
        assert issubclass(param_model, BaseModel)
        try:
            param_schema = param_model.model_json_schema()
        except AttributeError:  # pydantic 1.x
            param_schema = param_model.schema()
        if normalize:
            normalize_param_schema(param_schema)
        return param_schema


# Input nodes #---------------------------------------------------------------#
#
# Nodes without input ports.


class ItemsNodeParams(BaseModel):
    items: list[dict[str, Any]] = Field(
        title="Items",
        description=(
            "JSON array of JSON objects to output as items.\n"
            "\n"
            "For example:\n"
            "\n"
            ".. code-block:: json\n"
            "\n"
            '    [{"foo": "bar"}]\n'
        ),
        json_schema_extra={
            # Trigger consistent output when using older Pydantic versions.
            "items": {"additionalProperties": True, "type": "object"},
        },
    )


class ItemsNode(NodeArgs[ItemsNodeParams], ProcessorNode):
    """Items to output."""

    type = "items"
    spec: ClassVar[dict[str, Any]] = {
        "outputs": {
            "main": {
                "type": "item",
            },
        },
    }

    async def process(
        self,
        *,
        inputs: dict[str, AsyncIterator[Any]],
        outputs: dict[str, Queue[Any]],
        response_data: ResponseData | None,
    ) -> None:
        for item in self.args.items:
            await outputs["main"].put(item)


class UrlsNodeUrlsParam(BaseModel):
    urls: list[str] = Field(
        title="URLs",
        description=(
            "Input URLs.\n"
            "\n"
            "Define 1 absolute URL (e.g. including the http(s) prefix) per "
            "line.\n"
            "\n"
            "Example: https://toscrape.com/"
        ),
    )

    @field_validator("urls", mode="before")
    @classmethod
    def validate_url_list(cls, value: list[str] | str) -> list[str]:
        return validate_url_list(value)


class UrlsNodeParams(
    UrlsNodeUrlsParam,
):
    pass


class UrlsNode(NodeArgs[UrlsNodeParams], ProcessorNode):
    """URLs to output as requests."""

    type = "urls"
    spec: ClassVar[dict[str, Any]] = {
        "outputs": {
            "main": {
                "type": "request",
            },
        },
    }

    async def process(
        self,
        *,
        inputs: dict[str, AsyncIterator[Any]],
        outputs: dict[str, Queue[Any]],
        response_data: ResponseData | None,
    ) -> None:
        for url in cast("list[str]", self.args.urls):
            await outputs["main"].put(Request(url))


class UrlsFileNodeUrlsFileParam(BaseModel):
    urls_file: str = Field(
        title="URLs file",
        description=(
            "URL that point to a plain-text file with a list of URLs to "
            "crawl, e.g. https://example.com/url-list.txt. The linked file "
            "must contain 1 URL per line."
        ),
        pattern=URL_PATTERN,
    )


class UrlsFileNodeParams(
    UrlsFileNodeUrlsFileParam,
):
    pass


class UrlsFileNode(NodeArgs[UrlsFileNodeParams], ProcessorNode):
    """URL to a file with URLs to output as requests."""

    type = "urls_file"
    spec: ClassVar[dict[str, Any]] = {
        "outputs": {
            "main": {
                "type": "request",
            },
        },
    }

    async def process(
        self,
        *,
        inputs: dict[str, AsyncIterator[Any]],
        outputs: dict[str, Queue[Any]],
        response_data: ResponseData | None,
    ) -> None:
        request = Request(self.args.urls_file)
        assert self.crawler.engine is not None
        response = await deferred_to_future(self.crawler.engine.download(request))
        for url in response.text.splitlines():
            if not (url := url.strip()):
                continue
            if not re.search(URL_PATTERN, url):
                logger.error(
                    f"Ignoring bad URL {url!r} from URLs file "
                    f"{self.args.urls_file!r} loaded by node {self!r}"
                )
                continue
            try:
                request = Request(url)
            except ValueError:
                logger.error(
                    f"Ignoring bad URL {url!r} from URLs file "
                    f"{self.args.urls_file!r} loaded by node {self!r}",
                    exc_info=True,
                )
                continue
            await outputs["main"].put(request)


# Spider nodes #--------------------------------------------------------------#
#
# Nodes that subclass SpiderNode. They usually send requests and process their
# responses.


class FetchNode(SpiderNode):
    """Fetch requests and outputs their responses."""

    type = "fetch"
    spec: ClassVar[dict[str, Any]] = {
        "inputs": {
            "main": {
                "type": "request",
            },
        },
        "outputs": {
            "main": {
                "type": "response",
            },
        },
    }

    async def process_input(
        self,
        *,
        inputs: dict[str, AsyncIterator[Any]],
    ) -> AsyncIterator[Any]:
        async for request in inputs["main"]:
            yield request

    async def process_output(
        self,
        *,
        response_data: ResponseData,
        outputs: dict[str, Queue[Any]],
    ) -> None:
        await outputs["main"].put(response_data)


# Parser nodes #--------------------------------------------------------------#
#
# Nodes that yield items from responses.


class SelectorParserNodeParams(BaseModel):
    map: dict[str, dict[str, str]] = Field(
        title="Selector map",
        description=(
            "JSON object mapping field names to JSON objects that define a "
            'selector type and value. For example: {"name": {"type": "css", '
            '"value": ".name::text"}.\n'
            "\n"
            'Each field query can also define a "getter" key, which is the '
            'name of the selector method to use: "get" (default) or "getall".'
        ),
    )


class SelectorParserNode(NodeArgs[SelectorParserNodeParams], ProcessorNode):
    type = "selector-parser"
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
    deps: ClassVar[set[builtins.type]] = {Response}

    async def process(
        self,
        *,
        inputs: dict[str, AsyncIterator[Any]],
        outputs: dict[str, Queue[Any]],
        response_data: ResponseData | None,
    ) -> None:
        async for data in inputs["main"]:
            assert data is not None
            try:
                response = data.response
            except Exception:  # noqa: S112
                continue
            item = {}
            for field, query in self.args.map.items():
                select_fn = getattr(response, query["type"])
                selector = select_fn(query["value"])
                value = getattr(selector, query.get("getter", "get"))()
                item[field] = value
            await outputs["main"].put(item)


# Follow nodes #--------------------------------------------------------------#
#
# Nodes that yield requests from responses or items.


class SelectorFollowNodeParams(BaseModel):
    selectors: list[dict[str, str]] = Field(
        title="Selector list",
        description=(
            "JSON array of JSON objects that each define a selector type and "
            'value. For example: [{"type": "css", '
            '"value": "a::attr(href)"}].\n'
            "\n"
            'Each field query can also define a "getter" key, which is the '
            'name of the selector method to use: "getall" (default) or "get".'
        ),
    )


class SelectorFollowNode(NodeArgs[SelectorFollowNodeParams], ProcessorNode):
    type = "selector-follow"
    spec: ClassVar[dict[str, Any]] = {
        "inputs": {
            "main": {
                "type": "response",
            },
        },
        "outputs": {
            "main": {
                "type": "request",
            },
        },
    }
    deps: ClassVar[set[builtins.type]] = {Response}

    async def process(
        self,
        *,
        inputs: dict[str, AsyncIterator[Any]],
        outputs: dict[str, Queue[Any]],
        response_data: ResponseData | None,
    ) -> None:
        async for data in inputs["main"]:
            assert data is not None
            try:
                response = data.response
            except Exception:  # noqa: S112
                continue
            assert response is not None
            for query in self.args.selectors:
                select_fn = getattr(response, query["type"])
                selector = select_fn(query["value"])
                urls = getattr(selector, query.get("getter", "getall"))()
                if not urls:
                    continue
                if isinstance(urls, str):
                    urls = [urls]
                for url in urls:
                    request = response.follow(url)
                    await outputs["main"].put(request)


class ItemFollowNodeParams(BaseModel):
    url_jmes: str = Field(
        title="URL JMESPath query",
        description=(
            "Determines which URLs to follow.\n"
            "\n"
            "It is a JMESPath_ query that matches a URL or a list of URLs.\n"
            "\n"
            ".. _JMESPath: https://jmespath.org/"
        ),
    )
    max_recursion: int = Field(
        title="Maximum recursion",
        description=(
            "Limits how many times a given chain of requests can go through "
            "this node.\n"
            "\n"
            "-1 means no limit.\n"
            "\n"
            "It is useful, for example, to limit pagination to the first few "
            "pages."
        ),
        default=-1,
    )


class ItemFollowNode(NodeArgs[ItemFollowNodeParams], ProcessorNode):
    """Parse URLs from items and yield requests."""

    type = "item-follow"
    spec: ClassVar[dict[str, Any]] = {
        "inputs": {
            "main": {
                "type": "item",
            },
        },
        "outputs": {
            "main": {
                "type": "request",
            },
        },
    }
    deps: ClassVar[set[builtins.type]] = {Response}

    def process_request(
        self, request: Request, /, *, response_data: ResponseData | None = None
    ) -> Request:
        request = super().process_request(request, response_data=response_data)
        if self.args.max_recursion == -1:
            return request
        meta = request.meta.get(self.meta_key, {})
        meta["recursion"] = meta.get("recursion", 0) + 1
        request.meta[self.meta_key] = meta
        return request

    async def process(
        self,
        *,
        inputs: dict[str, AsyncIterator[Any]],
        outputs: dict[str, Queue[Any]],
        response_data: ResponseData | None,
    ) -> None:
        recursion = (
            response_data.meta.get(self.meta_key, {}).get("recursion", 0)
            if response_data
            else 0
        )
        async for item in inputs["main"]:
            adapter = ItemAdapter(item)
            if self.args.max_recursion != -1 and recursion > self.args.max_recursion:
                continue
            urls = jmespath.search(self.args.url_jmes, adapter)
            if urls is None:
                continue
            if isinstance(urls, str):
                urls = [urls]
            for url in urls:
                if response_data is not None:
                    assert response_data.response is not None
                    request = response_data.response.follow(url)
                else:
                    request = Request(url)
                await outputs["main"].put(request)
