import os
import sys

sys.path.insert(0, os.path.abspath("../../src"))

project = "kai-exman"
copyright = "2026, Lai"
author = "Lai"
release = "0.1.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns = []

language = "en"

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
