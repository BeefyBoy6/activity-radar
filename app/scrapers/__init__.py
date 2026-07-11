"""Import all platform scrapers so the registry is populated."""
from . import arux, custom, dash, eleyo, rec1, revtrak, vscloud, ymca  # noqa: F401
from .base import get_scraper  # noqa: F401
