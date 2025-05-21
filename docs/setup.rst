.. _setup:

=====
Setup
=====

..
    TODO: The following is currently fictional, assuming a future where this
    code is split offf into a separate library.

Install from PyPI_:

.. _PyPI: https://pypi.org/project/scrapy-crawl-maps/

.. code-block:: shell

    pip install scrapy-crawl-maps

And update :setting:`ADDONS`:

.. code-block:: python
    :caption: settings.py

    ADDONS = {
        "scrapy_crawl_maps.Addon": 800,
    }
