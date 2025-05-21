.. _tutorial:

========
Tutorial
========

.. currentmodule:: scrapy_crawl_maps

Once you have :ref:`installed and configured scrapy-crawl-maps <setup>`, follow
this tutorial to learn how to use it.

Hello world!
============

scrapy-crawl-maps provides a spider, :class:`CrawlMapSpider`, that can follow
a :ref:`crawl map <map>`.

Write a ``hello.json`` file with the following crawl map, which is the shortest
possible crawl map you can define, where you use a single :class:`ItemsNode` to
hardcode an output item:

.. code-block:: json
    :caption: hello.json

    {
        "nodes": {
            "items": {
                "type": "items",
                "args": {"items": [{"hello": "world"}]}
            }
        }
    }

It yields the following :ref:`item <topics-items>`:

.. code-block:: json

    {"hello": "world"}

Run the following command:

.. code-block:: bash

    scrapy crawl map -a map=hello.json -o items.jsonl

The command will create an ``items.jsonl`` file with that item.

Congratulations! You have just run your first crawl map!


Parsing
=======

While simple, the previous crawl map is not very useful. You will now create a
more useful crawl map.

Write a ``parse.json`` file with the following crawl map, which uses
:class:`UrlsNode` to define input URLs, :class:`FetchNode` to fetch them, and
:class:`SelectorParserNode` to output items based on the response data using a
CSS selector:

.. code-block:: json
    :caption: parse.json

    {
        "nodes": {
            "input": {
                "type": "urls",
                "args": {"urls": ["https://toscrape.com"]}
            },
            "fetch": {"type": "fetch"},
            "item-parser": {
                "type": "selector-parser",
                "args": {
                    "map": {"title": {"type": "css", "value": "h1::text"}}
                }
            }
        },
        "edges": [
            {"from": "input", "to": "fetch"},
            {"from": "fetch", "to": "item-parser"}
        ]
    }

Notice how, in addition to the nodes, you now define ``"edges"`` that connect
those nodes.

To run this crawl map, run the following command:

.. code-block:: bash

    scrapy crawl map -a map=parse.json -o items.jsonl

``items.jsonl`` will now contain a new item:

.. code-block:: json

    {"title": "Web Scraping Sandbox"}


Crawling
========

The previous crawl map handles parsing. Now you will create a crawl map that
also handles crawling, i.e. following parsed URLs.

Write a ``crawl.json`` file with the following crawl map, which crawls books
from all pages of a category of http://books.toscrape.com/:

.. code-block:: json
    :caption: crawl.json

    {
        "nodes": {
            "input": {
                "type": "urls",
                "args": {"urls": ["http://books.toscrape.com/catalogue/category/books/mystery_3/index.html"]},
            },
            "fetch-navigation": {"type": "fetch"},
            "navigation-parser": {
                "type": "selector-parser",
                "args": {
                    "map": {
                        "book_urls": {"type": "css", "value": "section h3 a::attr(href)", "getter": "getall"},
                        "next_url": {"type": "css", "value": ".next a::attr(href)"},
                    }
                },
            },
            "follow-next": {
                "type": "item-follow",
                "args": {
                    "url_jmes": "next_url",
                },
            },
            "follow-book": {
                "type": "item-follow",
                "args": {
                    "url_jmes": "book_urls",
                },
            },
            "fetch-book": {"type": "fetch"},
            "book-parser": {
                "type": "selector-parser",
                "args": {
                    "map": {
                        "name": {"type": "css", "value": "h1::text"},
                    }
                },
            },
        },
        "edges": [
            {"from": "input", "to": "fetch-navigation"},
            {"from": "fetch-navigation", "to": "navigation-parser"},
            {"from": "navigation-parser", "to": "follow-next"},
            {"from": "navigation-parser", "to": "follow-book"},
            {"from": "follow-next", "to": "fetch-navigation"},
            {"from": "follow-book", "to": "fetch-book"},
            {"from": "fetch-book", "to": "book-parser"},
        ],
    }

To run this crawl map, run the following command:

.. code-block:: bash

    scrapy crawl map -a map=crawl.json -o items.jsonl

``items.jsonl`` will now contain new items with book titles, e.g.:

.. code-block:: json

    {"title": "A Light in the Attic"}


Next steps
==========

You are now familiar with the basics of crawl maps. To practice and learn more,
you can:

-   Take an existing spider, and try to convert it into a crawl map and run it
    with :class:`CrawlMapSpider`.

-   Learn more about :ref:`writing crawl maps <map>`.

-   Learn to :ref:`write your own node types <custom-node>`.
