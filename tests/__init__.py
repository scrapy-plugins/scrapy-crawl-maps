from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from scrapy_crawl_maps.spiders import CrawlMapSpider

if TYPE_CHECKING:
    from scrapy import Spider

SETTINGS = {"ADDONS": {"scrapy_poet.Addon": 300}}


# scrapy.utils.test.get_crawler alternative that does not freeze settings.
def get_crawler(
    *,
    settings: dict[str, Any] | None = None,
    spider_cls: type[Spider] = CrawlMapSpider,
):
    from scrapy.crawler import CrawlerRunner

    settings = settings or SETTINGS
    runner = CrawlerRunner(settings)
    return runner.create_crawler(spider_cls)


def assertEqualsParamOrder(actual, expected):
    for k in actual:
        if k not in expected:
            continue
        if k == "param_schema":
            assert tuple(actual[k]["properties"]) == tuple(expected[k]["properties"])
            continue
        if not isinstance(actual[k], dict) or not isinstance(expected[k], dict):
            continue
        assertEqualsParamOrder(actual[k], expected[k])


def assertEqualSpiderMetadata(actual, expected):
    """Compare 2 JSON schemas of spider metadata.

    The parameter order in the parameter schema is taken into account, given
    how it affects the UI, while the order of other object keys may be
    different.

    It also generates a better diff in pytest output when enums are involved,
    e.g. geolocation values.
    """
    assertEqualsParamOrder(actual, expected)
    actual_json = json.dumps(actual, indent=2, sort_keys=True)
    expected_json = json.dumps(expected, indent=2, sort_keys=True)
    assert actual_json == expected_json
