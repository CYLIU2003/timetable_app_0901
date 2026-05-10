from __future__ import annotations

import html
import logging

import feedparser

from .cache import TtlCache
from .config import NEWS_CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)
_news_cache = TtlCache()

NHK = "https://www3.nhk.or.jp/rss/news/cat0.xml"
GGL = "https://news.google.com/rss/search?q=東急&hl=ja&gl=JP&ceid=JP:ja"


def _load_news() -> dict[str, list[str]]:
    out: list[str] = []
    seen: set[str] = set()

    for url in (NHK, GGL):
        feed = feedparser.parse(url)
        entries = getattr(feed, "entries", []) or []
        for entry in entries[:5]:
            title = html.unescape(str(entry.get("title", "")).strip())
            if title and title not in seen:
                out.append(title)
                seen.add(title)
            if len(out) >= 10:
                break

    return {"news": out}


def get_news() -> dict[str, list[str]]:
    try:
        return _news_cache.get_or_set("news", NEWS_CACHE_TTL_SECONDS, _load_news)
    except Exception as exc:
        logger.warning("News error: %s", exc)
        return {"news": []}