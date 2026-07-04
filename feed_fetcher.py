import asyncio
import logging
import feedparser
import aiohttp
from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)

USER_AGENT = "DailyIntelligence/1.0"
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=20)

# Feed definitions, fallbacks, and scrape-only sources all come from config.
FEEDS: dict[str, list[str]] = config.FEEDS
FALLBACK_PAGES: dict[str, str] = getattr(config, "FALLBACK_PAGES", {})
EXTRA_SCRAPE_URLS: list = getattr(config, "EXTRA_SCRAPE_URLS", [])
LOOKBACK_HOURS = getattr(config, "FEED_LOOKBACK_HOURS", 72)


@dataclass
class FeedItem:
    title: str
    url: str
    summary: str
    source: str
    category: str
    published: str = ""

    def __repr__(self) -> str:
        return f"FeedItem({self.title[:50]})"


async def _fetch_feed(session: aiohttp.ClientSession, url: str, category: str) -> list[FeedItem]:
    """Fetch a single RSS/Atom feed and return parsed items within the lookback window."""
    try:
        async with session.get(url, timeout=FETCH_TIMEOUT) as resp:
            if resp.status != 200:
                logger.warning(f"Feed {url} returned {resp.status}")
                return await _try_fallback(session, url, category)
            text = await resp.text()
    except Exception as e:
        logger.warning(f"Feed {url} failed: {e}")
        return await _try_fallback(session, url, category)

    feed = feedparser.parse(text)
    if not feed.entries:
        logger.warning(f"Feed {url} returned 0 entries")
        return await _try_fallback(session, url, category)

    cutoff = datetime.utcnow() - timedelta(hours=LOOKBACK_HOURS)
    items = []
    for entry in feed.entries[:20]:  # cap per feed
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue

        summary = entry.get("summary", entry.get("description", ""))[:500]
        published = ""
        # Try published_parsed first, then updated_parsed (used by Atom/GitHub)
        parsed_time = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            parsed_time = entry.published_parsed
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            parsed_time = entry.updated_parsed

        if parsed_time:
            try:
                pub_dt = datetime(*parsed_time[:6])
                if pub_dt < cutoff:
                    continue
                published = pub_dt.strftime("%Y-%m-%d")
            except Exception as e:
                logger.warning(f"Date parse failed for {link}: {e}")
                continue
        else:
            # No date at all — skip to avoid stale content
            continue

        items.append(FeedItem(
            title=title,
            url=link,
            summary=summary,
            source=_source_name(url),
            category=category,
            published=published,
        ))

    logger.info(f"  {_source_name(url)}: {len(items)} items")
    return items


async def _try_fallback(session: aiohttp.ClientSession, feed_url: str, category: str) -> list[FeedItem]:
    """If a feed fails, try scraping the configured fallback HTML page."""
    fallback_url = FALLBACK_PAGES.get(feed_url)
    if not fallback_url:
        return []

    logger.info(f"  Trying fallback: {fallback_url}")
    try:
        async with session.get(fallback_url, timeout=FETCH_TIMEOUT) as resp:
            if resp.status != 200:
                return []
            html = await resp.text()
    except Exception as e:
        logger.warning(f"  Fallback {fallback_url} failed: {e}")
        return []

    return _parse_html_headlines(html, fallback_url, category)


def _parse_html_headlines(html: str, base_url: str, category: str) -> list[FeedItem]:
    """Extract headlines from an HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for tag in soup.find_all(["h2", "h3", "h4"], limit=15):
        a = tag.find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or not href:
            continue
        if href.startswith("/"):
            from urllib.parse import urljoin
            href = urljoin(base_url, href)
        items.append(FeedItem(
            title=title,
            url=href,
            summary="",
            source=_source_name(base_url),
            category=category,
        ))
    logger.info(f"  Fallback {base_url}: {len(items)} headlines")
    return items


def _source_name(url: str) -> str:
    """Extract a human-readable source name from a URL."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname or url
    host = host.replace("www.", "")
    # Special cases
    if "hnrss" in host:
        return "Hacker News"
    if "github.com" in host:
        parts = url.split("/")
        if len(parts) >= 5:
            return f"GitHub: {parts[3]}/{parts[4]}"
    if "reddit.com" in host:
        parts = url.split("/")
        for i, p in enumerate(parts):
            if p == "r" and i + 1 < len(parts):
                return f"r/{parts[i+1]}"
    return host


async def fetch_all_feeds() -> list[FeedItem]:
    """Fetch all feeds in parallel and return combined items."""
    logger.info("PASS 1: Fetching RSS/Atom feeds...")
    all_items: list[FeedItem] = []

    headers = {"User-Agent": USER_AGENT}
    connector = aiohttp.TCPConnector(limit=20)
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        tasks = []
        for category, urls in FEEDS.items():
            for url in urls:
                tasks.append(_fetch_feed(session, url, category))

        # Scrape-only sources (no feed at all)
        for url, category in EXTRA_SCRAPE_URLS:
            tasks.append(_try_fallback(session, url, category))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Feed task failed: {result}")
                continue
            all_items.extend(result)

    logger.info(f"PASS 1 complete: {len(all_items)} total items from feeds")
    return all_items
