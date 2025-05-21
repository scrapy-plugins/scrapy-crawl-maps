.. _customize:

=============
Customization
=============

.. currentmodule:: scrapy_crawl_maps

scrapy-crawl-maps allows defining :ref:`custom node types <custom-node>` and
:ref:`custom spiders <custom-spider>`.

.. _custom-node:

Creating a custom node type
===========================

To create a custom node type:

#.  :ref:`Subclass an appropriate node base class <node-base-classes>`.

#.  Set in :attr:`~ProcessorNode.type` the ID of your node type in :ref:`crawl
    maps <map>`.

#.  Set in :attr:`~ProcessorNode.spec` your :ref:`input and output ports
    <port-types>` and :ref:`parameters <node-params>`.

#.  Implement the abstract methods of your base class.

For example, this node type has no inputs and outputs a request to
https://toscrape.com:

.. code-block:: python

    from scrapy import Request
    from scrapy_crawl_maps import ProcessorNode


    class MyNode(ProcessorNode):
        type = "my-node"
        spec = {
            "output": {
                "type": "request",
            },
        }

        async def process(self, *, inputs, outputs, response_data):
            await outputs["main"].put(Request("https://toscrape.com"))

To use your node, define a :class:`CrawlMap` subclass that includes it in
:attr:`~CrawlMap.node_types`, and use that subclass as type for the
crawl map parameter of your spider. For example:

.. code-block:: python

    from scrapy_crawl_maps import (
        CrawlMapSpider,
        CrawlMapSpiderCrawlMap,
    )
    from myproject.nodes import MyNode


    class MySpiderCrawlMap(CrawlMapSpiderCrawlMap):
        node_types = CrawlMapSpiderCrawlMap.node_types | {MyNode}


    class MySpiderParams(BaseModel):
        map: MySpiderCrawlMap = Field()


    class MySpider(CrawlMapSpider, Args[MySpiderParams]):
        pass


.. _node-base-classes:

Processor nodes and spider nodes
--------------------------------

To write a custom node type, first you need to determine if you need a
processor node or a spider node:

-   A **processor node** has a single :meth:`~ProcessorNode.process` method
    that can access inputs, write to outputs, and access the response data when
    called in the context of a spider callback (i.e. not as part of
    :meth:`Spider.start() <scrapy.Spider.start>`).

-   A **spider node** interfaces with the Scrapy spider, so it must implement
    two separate methods: :meth:`~SpiderNode.process_input` and
    :meth:`~SpiderNode.process_output`.

Generally, you should use a processor node if you can, or a spider node if you
must.

…


.. _inputs:

Iterating inputs
----------------

…


.. _outputs:

Enqueuing outputs
-----------------

…


.. _node-params:

Defining node parameters
------------------------

…


.. _custom-spider:

Creating a custom spider
========================

…
