.. _map:

==========
Crawl maps
==========

.. currentmodule:: scrapy_crawl_maps

Crawl-map based spiders like :class:`CrawlMapSpider` expose a :ref:`spider
parameter <params>` that accepts a crawl map.

A **crawl map** is a JSON_ object that defines the crawling logic of the spider
as a `directed graph`_ with :ref:`nodes <nodes>` and :ref:`edges <edges>`.

.. _directed graph: https://en.wikipedia.org/wiki/Directed_graph
.. _JSON: https://www.json.org/json-en.html

You can write crawl maps by hand, but it is usually easier to use a
:ref:`builder <builders>`.

Continue reading to learn how to build crawl maps. For reference documentation,
see :ref:`crawl-map-spec`.

.. _node-args:
.. _node-type:
.. _node-types:
.. _nodes:

Nodes
=====

The :ref:`"nodes" <nodes-spec>` key in a crawl map defines the nodes that make
up the spider logic.

It is a JSON object where each key is an arbitrary node ID chosen by you, and
each value is a JSON object that defines the :ref:`"type" <node-type-key>` and
possibly :ref:`"args" <node-args-key>` of that node.

For example, to define the start URLs of your spider, you can define a node of
type :class:`UrlsNode` with the start URLs defined in its ``urls`` parameters:

.. code-block:: json

    {
        "nodes": {
            "start_urls": {
                "type": "urls",
                "args": {
                    "urls": [
                        "https://toscrape.com"
                    ]
                }
            }
        }
    }

When reading the reference documentation of :ref:`built-in node types
<builtin-node-types>` like :class:`UrlsNode`:

-   You can find their ``type`` ID in their :attr:`~UrlsNode.type` attribute.
    For :class:`UrlsNode`, it is ``"urls"``.

-   If a node type supports parameters, its list of base classes will include
    :class:`NodeArgs` with some other class between brackets, e.g.
    :class:`NodeArgs` [:class:`UrlsNodeParams`]. The class between brackets is
    a `pydantic model`_ that defines the node type parameters.

    .. _pydantic model: https://docs.pydantic.dev/latest/concepts/models/


.. _edges:
.. _port:

Edges
=====

The ``edges`` key in a crawl map defines connections between nodes.

Node types may define **input and output ports**.

Ports have a name and a type. The port name is a string, conventionally
``"main"`` when there is only 1 port. The port type is a string, conventionally
one of: ``"request"``, ``"response"``, ``"item"``, ``"string"``.

In a crawl map, you can connect an input port to an output port provided they
both have the same type.

For example, to download your start URLs, you can define a node of type
:class:`FetchNode` and connect the output of your start URLs node to the input
of your fetch node:

.. code-block:: python

    {
        "nodes": {
            "start_urls": {"type": "urls", "args": {"urls": ["https://toscrape.com"]}},
            "fetch": {"type": "fetch"},
        },
        "edges": [{"from": ["start_urls", "main"], "to": ["fetch", "main"]}],
    }

As you can see, the ``"from"`` and ``"to"`` values as JSON arrays of 2 strings,
a node ID and a port name.

If the source node has a single output port or the target node has a single
input port, as with both :class:`UrlsNode` and :class:`FetchNode`, you can
specify the node ID only as a string:

.. code-block:: python

    {"edges": [{"from": "start_urls", "to": "fetch"}]}


.. _builders:

Builders
========

**Crawl map builders** are tools, usually visual, that help you create and edit
crawl maps.

However, at the moment there is no known crawl map builder. If you find or
develop one, please `open an issue`_ to get it listed here.

.. _open an issue: https://github.com/scrapy-plugins/scrapy-crawl-maps/issues
