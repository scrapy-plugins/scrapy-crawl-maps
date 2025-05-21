from scrapy.settings import BaseSettings


class Addon:
    @classmethod
    def update_pre_crawler_settings(cls, settings: BaseSettings) -> None:
        settings.add_to_list("SPIDER_MODULES", "scrapy_crawl_maps.spiders")
