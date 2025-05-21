.. _reference:

==========
Python API
==========

Nodes
=====

.. _builtin-node-types:

Built-in node types
-------------------

.. autoclass:: scrapy_crawl_maps.FetchNode()
    :show-inheritance:
    :members: type, spec

.. autoclass:: scrapy_crawl_maps.ItemFollowNode()
    :show-inheritance:
    :members: type, spec

.. autopydantic_model:: scrapy_crawl_maps.ItemFollowNodeParams
    :inherited-members: BaseModel

.. autoclass:: scrapy_crawl_maps.ItemsNode()
    :show-inheritance:
    :members: type, spec

.. autopydantic_model:: scrapy_crawl_maps.ItemsNodeParams
    :inherited-members: BaseModel

.. autoclass:: scrapy_crawl_maps.SelectorParserNode()
    :show-inheritance:
    :members: type, spec

.. autopydantic_model:: scrapy_crawl_maps.SelectorParserNodeParams
    :inherited-members: BaseModel

.. autoclass:: scrapy_crawl_maps.UrlsNode()
    :show-inheritance:
    :members: type, spec

.. autopydantic_model:: scrapy_crawl_maps.UrlsNodeParams
    :inherited-members: BaseModel

.. autoclass:: scrapy_crawl_maps.UrlsFileNode()
    :show-inheritance:
    :members: type, spec

.. autopydantic_model:: scrapy_crawl_maps.UrlsFileNodeParams
    :inherited-members: BaseModel


Node base classes
-----------------

.. autoclass:: scrapy_crawl_maps.ProcessorNode
    :members: type, spec, process, process_request

.. autoclass:: scrapy_crawl_maps.SpiderNode
    :members: type, spec, process_input, process_output

.. autoclass:: scrapy_crawl_maps.NodeArgs()
    :members: args

.. _port-types:

Port types
==========

…


.. _spiders:

Spiders
=======

Crawl map spider
----------------

.. autoclass:: scrapy_crawl_maps.CrawlMapSpider()
    :show-inheritance:

.. autopydantic_model:: scrapy_crawl_maps.CrawlMapSpiderParams
    :inherited-members: BaseModel

.. autoclass:: scrapy_crawl_maps.CrawlMapSpiderCrawlMap
    :show-inheritance:


Base spider
-----------

.. autoclass:: scrapy_crawl_maps.CrawlMapBaseSpider()


Crawl map
=========

.. autoclass:: scrapy_crawl_maps.CrawlMap()
    :members:

.. autoclass:: scrapy_crawl_maps.ResponseData
    :members:
