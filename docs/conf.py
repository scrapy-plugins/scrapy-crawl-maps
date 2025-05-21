import sys
from pathlib import Path

project = "scrapy-crawl-maps"
copyright = "2025, Zyte Group Ltd"
author = "Zyte Group Ltd"
release = "0.0.0"

sys.path.insert(0, str(Path(__file__).parent.absolute()))  # _ext
extensions = [
    "_ext",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx_design",
    "sphinxcontrib.autodoc_pydantic",
]

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"

intersphinx_mapping = {
    "python": (
        "https://docs.python.org/3",
        None,
    ),
    "scrapy": (
        "https://docs.scrapy.org/en/latest",
        None,
    ),
    "scrapy-poet": (
        "https://scrapy-poet.readthedocs.io/en/stable",
        None,
    ),
    "scrapy-spider-metadata": (
        "https://scrapy-spider-metadata.readthedocs.io/en/latest",
        None,
    ),
    "web-poet": (
        "https://web-poet.readthedocs.io/en/stable",
        None,
    ),
    "zyte": (
        "https://docs.zyte.com",
        None,
    ),
}

autodoc_default_options = {
    "member-order": "bysource",
}

autodoc_pydantic_model_member_order = "bysource"
autodoc_pydantic_model_show_config_summary = False
autodoc_pydantic_model_show_field_summary = False
autodoc_pydantic_model_show_json = False
autodoc_pydantic_model_show_validator_members = False
autodoc_pydantic_model_show_validator_summary = False
autodoc_pydantic_field_list_validators = False
autodoc_pydantic_field_show_constraints = False
