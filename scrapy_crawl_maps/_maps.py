from __future__ import annotations

import json
from asyncio import FIRST_COMPLETED, Queue, Task, create_task, gather, wait
from collections import defaultdict, deque
from copy import copy
from logging import getLogger
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    NamedTuple,
    cast,
)

from pydantic_core import CoreSchema
from pydantic_core import core_schema as cs
from scrapy import Request
from scrapy.signals import spider_closed
from scrapy.utils.python import global_object_name

from ._nodes import NodeArgs, ProcessorNode, SpiderNode, _Node

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Collection

    from pydantic import GetCoreSchemaHandler
    from pydantic.annotated_handlers import GetJsonSchemaHandler
    from pydantic.json_schema import JsonSchemaValue
    from scrapy.crawler import Crawler

    from .spiders import ResponseData

logger = getLogger(__name__)

# To be replaced with Queue.shutdown() when requiring Python 3.13+.
_QUEUE_SHUTDOWN = object()


async def _await_next(iterator: _OutputIterator | _SpiderInputIterator) -> Any:
    return await iterator.__anext__()


def _next_task(iterator: _OutputIterator | _SpiderInputIterator) -> Task[Any]:
    return create_task(_await_next(iterator), name=str(iterator))


async def _merge_iterators(
    iterators: Collection[_OutputIterator | _SpiderInputIterator],
) -> AsyncIterator[Any]:
    next_tasks = {iterator: _next_task(iterator) for iterator in iterators}
    while next_tasks:
        done, _ = await wait(next_tasks.values(), return_when=FIRST_COMPLETED)
        for task in done:
            iterator = next(it for it, t in next_tasks.items() if t == task)
            try:
                yield task.result(), iterator
            except StopAsyncIteration:
                del next_tasks[iterator]
            except Exception as exception:
                del next_tasks[iterator]
                logger.error(
                    f"Error while processing a node: {exception}", exc_info=True
                )
            else:
                next_tasks[iterator] = _next_task(iterator)


class GraphLoc(NamedTuple):
    node: ProcessorNode | SpiderNode
    port: str


class _SpiderInputIterator:
    def __init__(self, node: SpiderNode, inputs: dict[str, AsyncIterator]) -> None:
        self.node = node
        self._iterator = node.process_input(inputs=inputs)

    async def __anext__(self):
        return await self._iterator.__anext__()

    def __str__(self) -> str:
        return f"{self.node} → spider"


class _OutputIterator:
    def __init__(
        self,
        initial: list[Any],
        queue: Queue[Any],
        source: ProcessorNode | SpiderNode,
        target: ProcessorNode | SpiderNode | None,
    ):
        self._initial = deque(initial)
        self._queue = queue
        self._source = source
        self._target = target

    def __str__(self) -> str:
        return f"{self._source} → {self._target}"

    async def __anext__(self) -> Any:
        if self._initial:
            return self._initial.popleft()
        next = await self._queue.get()
        self._queue.task_done()
        if next is _QUEUE_SHUTDOWN:
            raise StopAsyncIteration
        return next

    def __aiter__(self):
        return self


class _OutputReader:
    def __init__(
        self,
        queue: Queue | None = None,
        log_output: Callable[[], None] | None = None,
        *,
        node: ProcessorNode | SpiderNode,
    ):
        self._input_queue = queue
        self._output_queues: list[Queue] = []
        self._read: list[Any] = []
        self._log_output = log_output
        self._read_finished = queue is None
        self.node = node

    async def read(self):
        if self._input_queue is not None:
            tasks: list[Task] = []
            assert self._log_output is not None
            while True:
                item = await self._input_queue.get()
                self._input_queue.task_done()
                if item is _QUEUE_SHUTDOWN:
                    self._read_finished = True
                    break
                self._log_output()
                self._read.append(item)
                tasks.extend(
                    create_task(queue.put(item)) for queue in self._output_queues
                )
            await gather(*tasks)
        tasks = []
        for queue in self._output_queues:
            tasks.append(create_task(queue.put(_QUEUE_SHUTDOWN)))
        await gather(*tasks)

    def get_iterator(
        self, node: ProcessorNode | SpiderNode | None = None
    ) -> _OutputIterator:
        queue: Queue = Queue()
        if self._read_finished:
            queue.put_nowait(_QUEUE_SHUTDOWN)
        else:
            self._output_queues.append(queue)
        return _OutputIterator(copy(self._read), queue, source=self.node, target=node)


async def _iterate_with_node(
    iterator: AsyncIterator[Any], node: SpiderNode | None = None
) -> AsyncIterator[Any]:
    async for item in iterator:
        yield item, node


class CrawlMap:
    """:ref:`Crawl map <map>` handler.

    A subclass should be used as type for the crawl map parameter of a
    crawl-map spider (e.g. :attr:`CrawlMapSpiderParams.map`).

    It defines a supported :ref:`crawl map schema <crawl-map-schema>` through
    its :attr:`node_types` and :attr:`node_groups` attributes, allows loading a
    compatible crawl map from a JSON object, a Python dict or a file path, and
    provides methods (:meth:`load`, :meth:`start`, :meth:`parse`) for
    crawl-map spiders like :class:`CrawlMapSpider` to follow the loaded crawl
    map.
    """

    #: Groups for :attr:`node_types` defined according to the :ref:`node group
    #: spec <node-group-spec>`.
    #:
    #: :ref:`Crawl map builders <builders>` can use groups, for example, to
    #: organize a “node palette”.
    node_groups: ClassVar[dict[str, Any]]

    #: Declares supported :ref:`node types <node-types>`.
    #:
    #: See :ref:`custom-node` for an example on how to create a new spider that
    #: declares support for additional node types.
    node_types: ClassVar[set[type[ProcessorNode | SpiderNode]]]

    # This makes CrawlMap a valid Pydantic type that can take a JSON object in
    # 3 different forms: as a Python dict, as a Python string or as a file
    # path.
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        def validate_crawl_map(value: Any, info: cs.ValidationInfo) -> dict[str, Any]:
            if isinstance(value, dict):
                return value
            if not isinstance(value, str):
                raise ValueError(
                    f"Expected a JSON object as a string, as a dictionary or "
                    f"as a file path, got {value!r}."
                )
            if value.lstrip().startswith("{"):
                return json.loads(value)
            file_path = Path(value)
            if file_path.is_file():
                try:
                    with file_path.open() as f:
                        return json.load(f)
                except (FileNotFoundError, json.JSONDecodeError) as e:
                    raise ValueError(
                        f"Could not load or parse JSON from path {value!r}: {e}"
                    ) from e
            else:
                raise ValueError(f"{value!r} is not a valid file path.")

        try:
            validator_fn = cs.with_info_plain_validator_function
        except AttributeError:
            validator_fn = cs.general_plain_validator_function

        return cs.no_info_after_validator_function(
            cls, validator_fn(validate_crawl_map)
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: cs.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {
            "type": "object",
            "properties": {
                "nodes": {
                    "type": "object",
                    "properties": {
                        # TODO: Improve this typing based on node_types.
                        "type": {"type": "string"},
                        "args": {"type": "object"},
                    },
                    "required": ["type"],
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {
                                "oneOf": [
                                    {"type": "string"},
                                    {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                ]
                            },
                            "to": {
                                "oneOf": [
                                    {"type": "string"},
                                    {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                ],
                            },
                            "required": ["from", "to"],
                        },
                    },
                },
                "required": ["nodes"],
            },
            "node_groups": cls.node_groups,
            "node_types": cls._get_node_type_metadata(),
        }

    @classmethod
    def _get_node_type_metadata(cls) -> dict[str, Any]:
        result = {}
        for node_type in cls.node_types:
            node_data = node_type.spec.copy()
            for k in ("group", "title", "description"):
                if hasattr(node_type, k):
                    node_data[k] = getattr(node_type, k)
            if "group" in node_data and node_data["group"] not in getattr(
                cls, "node_groups", {}
            ):
                node_type_ref = f"{node_type.type!r} ({global_object_name(node_type)})"
                logger.warning(
                    f"Node type {node_type_ref} is in an unknown group: {node_data['group']}"
                )
            if issubclass(node_type, NodeArgs):
                node_data["param_schema"] = node_type.get_param_schema(normalize=True)
            result[node_type.type] = node_data
        return result

    def __init__(self, data: dict[str, Any], /):
        self._data = data
        self._dep_ids: defaultdict[str, set[str]] = defaultdict(set)
        self._sources: defaultdict[str, defaultdict[str, set[GraphLoc]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self._targets: defaultdict[str, defaultdict[str, set[GraphLoc]]] = defaultdict(
            lambda: defaultdict(set)
        )
        # Tasks to be canceled once the spider is closing.
        self._tasks: list[Task] = []
        self._nodes: dict[str, ProcessorNode | SpiderNode] = {}

    def _resolve_ref(self, link: dict[str, Any], direction: str) -> GraphLoc:
        ref: str | tuple[str, str] = link[direction]
        if isinstance(ref, str):
            node_id = ref
            node = self._nodes[node_id]
            io = "inputs" if direction == "to" else "outputs"
            port = next(iter(node.spec.get(io, {})))
        else:
            node_id, port = ref
            node = self._nodes[node_id]
        return GraphLoc(node, port)

    def _load_edges(self):
        for edge in self._data.get("edges", []):
            source = self._resolve_ref(edge, "from")
            target = self._resolve_ref(edge, "to")

            source_type = source.node.spec["outputs"][source.port]["type"]
            target_type = target.node.spec["inputs"][target.port]["type"]
            if source_type != target_type:
                raise ValueError(
                    f"Type mismatch in link {edge!r}: cannot link {source_type!r} output to {target_type!r} input."
                )

            self._dep_ids[target.node.id].add(source.node.id)
            self._sources[target.node.id][target.port].add(source)
            self._targets[source.node.id][source.port].add(target)

    def _get_inputless_nodes(self) -> list[ProcessorNode | SpiderNode]:
        return [
            node for node in self._nodes.values() if not node.spec.get("inputs", {})
        ]

    def _get_spiderless_node_ids(self) -> set[str]:
        node_ids = set(self._nodes)
        spider_nodes = [
            node for node in self._nodes.values() if isinstance(node, SpiderNode)
        ]
        seen_node_ids = {node.id for node in spider_nodes}
        pending_nodes: deque[ProcessorNode | SpiderNode] = deque(spider_nodes)

        # Discard all spider nodes, as well as any node that is connected to
        # their output.
        while pending_nodes:
            node = pending_nodes.popleft()
            node_ids.discard(node.id)
            for port in node.spec["outputs"]:
                for target in self._targets[node.id][port]:
                    if target.node.id not in seen_node_ids:
                        seen_node_ids.add(target.node.id)
                        pending_nodes.append(target.node)

        return node_ids

    async def _input_iterator(
        self, node, port, spiderfull_output_readers, allow_spiderless=True
    ):
        iterators = []
        for source in self._sources[node.id][port]:
            if allow_spiderless and source.node.id in self._spiderless_node_ids:
                reader = self._spiderless_output_readers[source.node.id][source.port]
            else:
                try:
                    reader = spiderfull_output_readers[source.node.id][source.port]
                except KeyError:
                    # Empty reader for circular dependency or disallowed spiderless.
                    reader = _OutputReader(node=source.node)
            iterators.append(reader.get_iterator(node))
        async for item, _ in _merge_iterators(iterators):
            self._track_input(node, port)
            yield item

    def _prepare_outputs(
        self,
        node: ProcessorNode | SpiderNode,
        output_readers: defaultdict[str, dict[str, _OutputReader]],
    ):
        tasks = []
        outputs: dict[str, Queue] = {port: Queue() for port in node.spec["outputs"]}
        for port, queue in outputs.items():

            def log_output(node=node, port=port):
                self._track_output(node, port)

            reader = _OutputReader(queue, log_output, node=node)
            output_readers[node.id][port] = reader
            tasks.append(create_task(reader.read()))
        return outputs, tasks

    def _is_circular_dep(self, node_id: str, dep_id: str) -> bool:
        pending_dep_ids = deque([dep_id])
        seen_dep_ids = set()
        while pending_dep_ids:
            current_dep_id = pending_dep_ids.popleft()
            if current_dep_id == node_id:
                return True
            if current_dep_id not in seen_dep_ids:
                seen_dep_ids.add(current_dep_id)
                pending_dep_ids.extend(self._dep_ids[current_dep_id])
        return False

    def _resolve_deps(self, start_nodes: list[SpiderNode | ProcessorNode]):
        pending_nodes: deque[ProcessorNode | SpiderNode] = deque(start_nodes)
        start_node_ids = {node.id for node in start_nodes}
        seen_node_ids = start_node_ids.copy()
        previous_pending_nodes = None

        while pending_nodes:
            if pending_nodes == previous_pending_nodes:
                start = ", ".join(sorted(start_node_ids))
                pending = ", ".join(sorted(node.id for node in pending_nodes))
                raise ValueError(
                    f"While resolving the downstream nodes from ({start}), it "
                    f"was not possible to resolve the following nodes: "
                    f"{pending}. Is it possible that you have an unsupported "
                    f"circular flow?"
                )
            previous_pending_nodes = pending_nodes.copy()

            node = pending_nodes.popleft()
            if node.id not in start_node_ids:
                deps_fullfilled = True
                for dep_id in self._dep_ids[node.id]:
                    if (
                        dep_id in seen_node_ids
                        or dep_id in self._spiderless_node_ids
                        or self._is_circular_dep(node.id, dep_id)
                    ):
                        continue
                    pending_nodes.append(node)
                    deps_fullfilled = False
                    break
                if not deps_fullfilled:
                    continue
            for targets in self._targets[node.id].values():
                for target in targets:
                    if target.node.id not in seen_node_ids:
                        seen_node_ids.add(target.node.id)
                        pending_nodes.append(target.node)
            yield node

    async def _iter_output(  # noqa: PLR0912, PLR0915
        self, response_data: ResponseData | None = None
    ) -> AsyncIterator[Any]:
        if response_data is not None:
            node_id = response_data.meta["_crawl_map_node"]
            source_node: SpiderNode | None = cast("SpiderNode", self._nodes[node_id])
            assert source_node is not None
            start_nodes: list[ProcessorNode | SpiderNode] = [source_node]
        else:
            source_node = None
            start_nodes = self._get_inputless_nodes()
        source_node_is_also_target = False

        tasks = []
        iterators: list[_OutputIterator | _SpiderInputIterator] = []
        spiderful_output_readers: defaultdict[str, dict[str, _OutputReader]] = (
            defaultdict(dict)
        )
        pending_nodes: deque[ProcessorNode | SpiderNode] = deque(start_nodes)
        seen_node_ids = {node.id for node in pending_nodes}
        previous_pending_nodes = None

        while pending_nodes:
            if pending_nodes == previous_pending_nodes:
                pending = ", ".join(sorted(node.id for node in pending_nodes))
                raise ValueError(
                    f"Cannot resolve the following crawl map dependencies: "
                    f"{pending}. Is it possible that you have a circular "
                    f"dependency?"
                )
            previous_pending_nodes = pending_nodes.copy()

            node = pending_nodes.popleft()
            if node is not source_node:
                deps_fullfilled = True
                for dep_id in self._dep_ids[node.id]:
                    if (
                        dep_id in seen_node_ids
                        or dep_id in self._spiderless_node_ids
                        or self._is_circular_dep(node.id, dep_id)
                    ):
                        continue
                    pending_nodes.append(node)
                    deps_fullfilled = False
                    break
                if not deps_fullfilled:
                    continue
            if isinstance(node, SpiderNode) and node is not source_node:
                inputs: dict[str, AsyncIterator] = {
                    port: self._input_iterator(
                        node,
                        port,
                        spiderful_output_readers,
                        allow_spiderless=source_node is None,
                    )
                    for port in node.spec["inputs"]
                }
                iterator = _SpiderInputIterator(node, inputs)
                iterators.append(iterator)
                continue
            if node.id in self._spiderless_node_ids:
                if node.id not in self._spiderless_outputs:
                    self._spiderless_outputs[node.id], subtasks = self._prepare_outputs(
                        node, self._spiderless_output_readers
                    )
                    self._tasks.extend(subtasks)
                outputs = self._spiderless_outputs[node.id]
                output_readers = self._spiderless_output_readers
            else:
                outputs, subtasks = self._prepare_outputs(
                    node, spiderful_output_readers
                )
                tasks.extend(subtasks)
                output_readers = spiderful_output_readers
            for port in outputs:
                if self._targets[node.id][port]:
                    for target in self._targets[node.id][port]:
                        if target.node.id not in seen_node_ids:
                            seen_node_ids.add(target.node.id)
                            pending_nodes.append(target.node)
                        elif (
                            source_node is not None and target.node.id == source_node.id
                        ):
                            source_node_is_also_target = True
                elif node.spec["outputs"][port]["type"] == "item":
                    reader = output_readers[node.id][port]
                    iterators.append(reader.get_iterator())
            if node is source_node:
                assert isinstance(node, SpiderNode)
                assert response_data is not None
                node_processor = node.process_output(
                    response_data=response_data, outputs=outputs
                )
            else:
                # TODO: Most likely, we need to allow spiderless nodes
                # regardless of response_data for inputs from nodes that are
                # not processed during the start requests, but only as part of
                # non-None response processing.
                inputs = {
                    port: self._input_iterator(
                        node,
                        port,
                        spiderful_output_readers,
                        allow_spiderless=response_data is None,
                    )
                    for port in node.spec.get("inputs", {})
                }
                assert isinstance(node, ProcessorNode)
                node_processor = node.process(
                    inputs=inputs, outputs=outputs, response_data=response_data
                )

            async def process(node_processor, outputs):
                try:
                    await node_processor
                except Exception as exception:
                    logger.error(
                        f"Error while processing a node: {exception}", exc_info=True
                    )
                await gather(
                    *(
                        create_task(queue.put(_QUEUE_SHUTDOWN))
                        for queue in outputs.values()
                    )
                )

            tasks.append(create_task(process(node_processor, outputs)))

        if source_node_is_also_target:
            assert source_node is not None
            inputs = {
                port: self._input_iterator(
                    source_node, port, spiderful_output_readers, allow_spiderless=False
                )
                for port in source_node.spec["inputs"]
            }
            iterator = _SpiderInputIterator(source_node, inputs)
            iterators.append(iterator)

        async for item_or_request, iterator in _merge_iterators(iterators):
            if isinstance(item_or_request, Request):
                if response_data:
                    for k, v in response_data.meta.items():
                        if k.startswith(_Node._persistent_meta_prefix):
                            item_or_request.meta[k] = v
                assert isinstance(iterator, _SpiderInputIterator)
                item_or_request.meta["_crawl_map_node"] = iterator.node.id
                for dep in self._resolve_deps([iterator.node]):
                    if not isinstance(dep, SpiderNode):
                        item_or_request = dep.process_request(  # noqa: PLW2901
                            item_or_request, response_data=response_data
                        )
            yield item_or_request

        await gather(*tasks)

    def prepare(self, /, *, crawler: Crawler):
        """Prepare the crawl map.

        This method must be called before any call to :meth:`start` or
        :meth:`parse`.

        *crawler* is the running crawler. A spider using this crawl map can
        read it from :attr:`Spider.crawler <scrapy.Spider.crawler>` and pass it
        to this method.
        """
        node_type_map = {cls.type: cls for cls in self.node_types}
        for id, data in self._data["nodes"].items():
            node_type = data["type"]
            try:
                node_cls = node_type_map[node_type]
            except KeyError:
                raise ValueError(
                    f"Unknown node type: {node_type!r}. Supported node types: "
                    f"{', '.join(sorted(node_type_map))}. See the reference "
                    f"docs of CrawlMap.node_types for more information."
                ) from None
            self._nodes[id] = node_cls(
                id=id,
                map=self,
                crawler=crawler,
                args=data.get("args", {}),
            )

        self._load_edges()

        # Nodes that are neither spider nodes nor nodes that have spider nodes
        # as input, directly or indirectly, i.e. nodes that run independent of
        # spider interaction, not conditioned by responses.
        self._spiderless_node_ids = self._get_spiderless_node_ids()
        self._spiderless_outputs: dict[str, dict[str, Queue]] = {}
        self._spiderless_output_readers: defaultdict[str, dict[str, _OutputReader]] = (
            defaultdict(dict)
        )

        crawler.signals.connect(self._close, signal=spider_closed)
        self._crawler = crawler

    async def start(self) -> AsyncIterator[Any]:
        """Yield :ref:`items <topics-items>` and :class:`~scrapy.Request`
        objects that should be yielded by :meth:`Spider.start()
        <scrapy.Spider.start>`."""
        if not self._nodes:
            raise ValueError("Crawl map not prepared. Call prepare() before start().")
        async for item_or_request in self._iter_output():
            yield item_or_request

    async def parse(self, *, response_data: ResponseData) -> AsyncIterator[Any]:
        """Yield :ref:`items <topics-items>` and :class:`~scrapy.Request`
        objects that should be yielded by a :attr:`~scrapy.Request.callback`.

        *response_data* usually contains the callback response. For example:

        .. code-block:: python

            async def callback(self, response):
                response_data = ResponseData.from_objects(response)
                async for item_or_request in self.map.parse(response_data=response_data):
                    yield item_or_request

        But it can contain additional data. For example, when using
        :doc:`scrapy-poet <scrapy-poet:index>`:

        .. code-block:: python

            async def callback(self, response: Response, deps: DynamicDeps):
                deps[response.__class__] = response
                response_data = ResponseData.from_objects(*deps.values())
                async for item_or_request in self.map.parse(response_data=response_data):
                    yield item_or_request
        """
        if not self._nodes:
            raise ValueError("Crawl map not prepared. Call prepare() before parse().")
        async for item_or_request in self._iter_output(response_data):
            yield item_or_request

    def _track_io(
        self, node: ProcessorNode | SpiderNode, type: str, port: str, count: int = 1
    ) -> None:
        assert self._crawler.stats is not None
        self._crawler.stats.inc_value(
            f"crawl_maps/nodes/{node.id}/{type}/{port}", count
        )

    def _track_input(
        self, node: ProcessorNode | SpiderNode, port: str, count: int = 1
    ) -> None:
        self._track_io(node, "inputs", port, count)

    def _track_output(
        self, node: ProcessorNode | SpiderNode, port: str, count: int = 1
    ) -> None:
        self._track_io(node, "outputs", port, count)

    async def _close(self):
        for task in self._tasks:
            task.cancel("spider_closed")
