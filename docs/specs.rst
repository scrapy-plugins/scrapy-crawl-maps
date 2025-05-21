========
JSON API
========

.. _crawl-map-spec:

Crawl map specification
=======================

A crawl map is a JSON object that supports the following keys:

-   .. _nodes-spec:

    ``"nodes"`` (``object``, required), where:

    -   .. _node-id:

        Keys (``string``) are node IDs.

        They can be arbitrary strings, provided they are unique within a crawl
        map, i.e. no 2 nodes can have the same ID.

    -   Values (``object``) support the following keys:

        -   .. _node-type-key:

            ``"type"`` (``string``, required) indicates the node type, e.g.
            ``"urls"`` or ``"fetch"``.

        -   .. _node-args-key:

            ``"args"`` (``object``, optional) indicates node arguments, where
            keys are parameter names (``string``) and values are parameter
            values (any valid JSON structure).

-   ``"edges"`` (``array``, optional), with items (``object``) that support the
    following keys:

    -   .. _edge-from:

        ``"from"`` (``string`` or ``array`` of ``string``, required) is one of
        the following:

        -   A node ID (see ``"nodes"``), e.g. ``"fetch-1"``.

            The node type of that node must define 1 (and only 1) :ref:`output
            port <node-type-outputs>` matching the type of the :ref:`input port
            <node-type-inputs>` defined in :ref:`"to" <edge-to>`.

        -   An array of node ID and port ID, e.g. ``["parser-1",
            "subcategories"]``.

            The node type of that node must define an :ref:`output port
            <node-type-outputs>` with the specified ID (e.g.
            ``"subcategories"``) matching the type of the :ref:`input port
            <node-type-inputs>` defined in :ref:`"to" <edge-to>`.

    -   .. _edge-to:

        ``"to"`` (``string`` or ``array`` of ``string``, required) indicates
        the target node and port, with the same syntax as :ref:`"from"
        <edge-from>`.

Any node output of ``item`` type not linked to anything is implicitly linked to
the default output.

Crawl map example
-----------------

Spider that extracts the book title out of book detail pages from
https://books.toscrape.com:

.. code-block:: json

    {
        "nodes": {
            "input": {
                "type": "urls",
                "args": {
                    "urls": [
                        "https://books.toscrape.com/catalogue/soumission_998/index.html"
                    ]
                }
            },
            "fetch": {
                "type": "fetch"
            },
            "item-parser": {
                "type": "selector-parser",
                "args": {
                    "map": {
                        "title": {
                            "type": "css",
                            "value": "h1::text"
                        }
                    }
                }
            }
        },
        "edges": [
            {"from": "input", "to": "fetch"},
            {"from": "fetch", "to": "item-parser"}
        ]
    }


.. _crawl-map-schema:
.. _crawl-map-schema-spec:

Crawl map schema specification
==============================

Crawl-map spiders expose the supported crawl map schema (i.e. the crawl map
node types that can be used and their supported inputs, outputs and parameters)
through spider metadata, specifically through additional keys in the metadata
JSON object of their crawl map parameter.

Those additional keys are as follows:

-   .. _node-group-spec:

    ``"node_groups"`` (``object``, optional), where:

    -   Keys are node type group IDs (see ``"node_types"."group"`` below).

        Note that node type group IDs may match node type IDs, e.g. the
        ``"downloader"`` node type group may contain the ``"downloader"``,
        ``"http_downloader"`` and ``"browser_downloader"`` node types.

    -   Values (``object``) support the following keys:

        -   ``"title"`` (``string``, optional) is the group title.

            If the UI offers a palette of node types containing all node types, it
            may optionally allow grouping node types by their group, and use the
            title as the group name to be shown in the UI.

            Node types in no group or in an untitled group could be all grouped in
            some special “Misc” group.

        -   ``"order"`` (``integer``, optional) enables sorting titled groups
            in the UI. Lower values come first.

            For example, the ``request-input`` group could be ``1``, the
            ``downloader`` group could be ``2``, and the ``parser`` group could
            be ``3``.

            Groups without a value are sorted second to last. Untitled groups
            are sorted last, even if they have a value.

            2 or more groups can have the same value, in which case their
            relative sorting is unspecified, i.e. up to the UI to decide,
            although alphabetically may be a good choice. The UI is also free
            to group same-value groups further, but these “groups of groups”
            will have no title or any other metadata.

-   ``"node_types"`` (``object``, required), where:

    -   Keys are node types (e.g. ``urls`` or ``fetch``).

    -   .. _node-spec:

        Values (``object``) are node spec, which support the following keys:

        -   ``"group"`` (``string``, optional) is the ID of a node type group.

            It can be an arbitrary string. Metadata about a given group may be
            defined in the ``"node_groups"`` object (see above).

        -   ``"title"`` (``string``, optional) is the node type title. If
            missing, the node type ID should be used as title.

        -   ``"description"`` (``string``, optional) is the node type
            description, in plain text.

            ..
                TODO: Clarify if we support e.g. new lines, and if we also
                support some subset of reStructuredText, indicate so as well.

        -   .. _node-type-inputs:

            ``"inputs"`` (``object``, optional) defines supported inputs with
            the same syntax as ``"outputs"`` below.

        -   .. _node-type-outputs:

            ``"outputs"`` (``object``, optional) defines supported outputs,
            where:

            -   Keys are output port IDs (see ``"edges"."from"``), which can be
                arbitrary strings.

            -   Values (``object``) support the following keys:

                -   ``"type"`` (``string``, required). See ``"input"``.

                -   ``"title"`` (``string``, optional). The name of the
                    output to show in the UI. If not defined, the UI should
                    not label the output.

        -   ``"param_schema"`` (``object``, optional) is a parameter
            specification defined the same way as scrapy-spider-metadata
            parameters.

Crawl map schema example
------------------------

.. code-block:: json

    {
      "node_groups": {
        "inputs": {
          "title": "Inputs",
          "order": 0,
        },
        "steps": {
          "title": "Steps",
          "order": 1,
        },
        "links": {
          "title": "Links",
          "order": 2,
        },
        "data": {
          "title": "Data to Return",
          "order": 3,
        }
      },
      "node_types": {
        "urls": {
          "group": "inputs",
          "title": "Start URLs",
          "outputs": {
            "main": {
              "type": "request"
            }
          },
          "param_schema": {
            "properties": {
              "urls": {
                "anyOf": [
                  {
                    "items": {
                      "type": "string"
                    },
                    "type": "array"
                  },
                  {
                    "type": "null"
                  }
                ],
                "default": null,
                "description": "Initial URLs for the crawl, separated by new lines. Enter the full URL including http(s), you can copy and paste it from your browser. Example: https://toscrape.com/",
                "title": "URLs",
                "widget": "textarea"
              }
            },
            "title": "UrlsNodeParams",
            "type": "object"
          }
        },
        "fetch": {
          "group": "steps",
          "title": "Fetch Pages",
          "inputs": {
            "main": {
              "type": "request"
            }
          },
          "outputs": {
            "main": {
              "type": "response"
            }
          }
        },
        "search": {
          "group": "steps",
          "title": "Search Form Input",
          "inputs": {
            "request": {
              "type": "request"
            },
            "query": {
              "type": "string"
            }
          },
          "outputs": {
            "main": {
              "type": "request"
            }
          }
        },
        "product-links": {
          "group": "links",
          "title": "Product Links",
          "inputs": {
            "main": {
              "type": "response"
            }
          },
          "outputs": {
            "main": {
              "type": "request"
            }
          }
        },
        "subcategory-links": {
          "group": "links",
          "title": "Subcategory Links",
          "inputs": {
            "main": {
              "type": "response"
            }
          },
          "outputs": {
            "main": {
              "type": "request"
            }
          }
        },
        "next-page-links": {
          "group": "links",
          "title": "Next Page Links",
          "inputs": {
            "main": {
              "type": "response"
            }
          },
          "outputs": {
            "main": {
              "type": "request"
            }
          }
        },
        "product": {
          "group": "data",
          "title": "Product",
          "inputs": {
            "main": {
              "type": "response"
            }
          },
          "outputs": {
            "main": {
              "type": "item"
            }
          }
        },
        "product-list": {
          "group": "data",
          "title": "Product List",
          "inputs": {
            "main": {
              "type": "response"
            }
          },
          "outputs": {
            "main": {
              "type": "item"
            }
          }
        },
        "product-navigation": {
          "group": "data",
          "title": "Product Navigation",
          "inputs": {
            "main": {
              "type": "response"
            }
          },
          "outputs": {
            "main": {
              "type": "item"
            }
          }
        }
      }
    }


Configuration page specification
================================

Spiders that define a :ref:`crawl map schema <crawl-map-schema-spec>` may also
define additional configuration pages in which to split spider parameters
other than the ``map`` parameter in :ref:`builders <builders>`.

Configuration pages are defined with the ``config_pages`` metadata key of a
spider. It is a JSON array where each item is a JSON object supporting the
following keys:

-   ``"id"`` (``string``, required) is an arbitrary string representing the ID
    of the configuration page.

    Certain tools may support special behaviors for pages with a given ID. For
    example, Scrapy Cloud supports a ``job`` config page where it includes
    settings that users might want to customize for specific job runs of a
    given (virtual) spider, such as the number of Scrapy Cloud units to use.

-   ``"title"`` (``string``, optional) is the display name of the config page.
    If not defined, the ``"id"`` is used instead for display purposes.

-   ``"order"`` (``integer``, optional) enables sorting pages in the UI. Lower
    values come first.

    Pages without a value are sorted second to last. Untitled pages
    are sorted last, even if they have a value.

    2 or more pages can have the same value, in which case their relative
    sorting is unspecified, i.e. up to the UI to decide, although
    alphabetically may be a good choice.

-   ``"params"`` (``array`` of ``string``, optional) contains the names of
    spider parameters that should be featured on the page.

    If a parameter in the value does not match any declared parameter of the
    spider, the UI should ignore it, and possibly warn the user about it as a
    programming error (e.g. a typo could be preventing the intended parameter
    to show up in the right configuration page).

By default, spiders with a crawl map schema have a default configuration page
that is the first page and contains any spider parameter, besides ``map``, that
is not listed in the ``"params"`` array of any other configuration page. The ID
of this configuration page is ``"main"``, and UI tools may give it a default
title, e.g. ``"Configuration"``. You may define a configuration page with ID
``"main"`` to override the position of that configuration page or override its
title.

UI tools may hide configuration pages without parameters. In cases where 2 or
more pages with the same ID are defined, only the first definition should be
taken into account, and an error may be reported to users about this
programming error.
