import csv
import json
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from io import StringIO
from typing import Any, override
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.parsers import expat

import httpx
from bs4 import BeautifulSoup

from a_domain.model.market.article import Article
from a_domain.model.market.world_indicator import IndicatorReading
from a_domain.ports.market.world_feed import IWorldFeed
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import ContentType, InformationSource, MarketScope, TableFormat
from b_application.config.sources_config import WorldIndicatorFeed, WorldNewsFeed, WorldSources
from c_infrastructure.request_pace import HostPace


class WorldFeed(IWorldFeed):
    """
    The world news feeds and the world indicators' tables over HTTP, one request after another, `request_pause_seconds`
    apart on `pace`, which the wiring gives it. `news_feeds` and `indicator_feeds` are those this
    site may read: the wiring leaves out a feed of a source and a table of an indicator its audience may not
    (Audience.world_sources, Audience.world_indicators), so no request ever leaves for one. No redirect is followed:
    a request reaches only the address the settings name. A response's body is read as it arrives and no further than
    `max_bytes`. A feed that declares a document type is refused where the parser meets the declaration, in whatever
    encoding the feed is written, so its XML defines no entity and reaches for nothing. A response that is refused,
    redirected, too large or unreadable is logged by its source and its failure's kind, and the next one is read. A
    feed's items dated later than their read are counted in one debug line.
    """

    def __init__(
        self,
        sources: WorldSources,
        news_feeds: Sequence[WorldNewsFeed],
        indicator_feeds: Sequence[WorldIndicatorFeed],
        summary_length: int,
        market_clock: IMarketClock,
        logger: ILoggingProvider,
        pace: HostPace,
    ) -> None:
        self._sources = sources
        self._news_feeds = news_feeds
        self._indicator_feeds = indicator_feeds
        self._summary_length = summary_length
        self._market_clock = market_clock
        self._logger = logger
        self._pace = pace

    @override
    async def fetch_news(self) -> list[Article]:
        items: dict[str, Article] = {}

        async with world_client(self._sources) as client:
            for feed in self._news_feeds:
                await self._pace.wait(self._sources.request_pause_seconds)

                try:
                    page = await fetch_bytes(client, feed.url, self._sources.max_bytes)
                    read = list(feed_items(page, feed.source, self._summary_length, self._market_clock.now()))
                except (httpx.HTTPError, expat.ExpatError, ValueError) as error:
                    self._logger.warning(f"World feed of {feed.source.label} was not read: {type(error).__name__}: {error}")
                    continue

                ahead = sum(article.published_at > article.fetched_at for article in read)

                if ahead:
                    self._logger.debug(f"World feed of {feed.source.label}: {ahead} items are dated later than their read.")

                for article in read:
                    items.setdefault(article.key, article)

        return list(items.values())

    @override
    async def fetch_indicators(self) -> list[IndicatorReading]:
        today = self._market_clock.today()
        since = today - timedelta(days=self._sources.table_days)
        readings: list[IndicatorReading] = []

        async with world_client(self._sources) as client:
            for feed in self._indicator_feeds:
                await self._pace.wait(self._sources.request_pause_seconds)

                try:
                    page = await fetch_bytes(client, feed.url.format(year=today.year), self._sources.max_bytes)
                    readings.extend(reading for reading in table_readings(page, feed) if since <= reading.day <= today)
                except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
                    names = ", ".join(indicator.value for indicator in feed.fields.values())
                    self._logger.warning(f"World indicators {names} were not read: {type(error).__name__}: {error}")

        return readings


def world_client(sources: WorldSources) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=sources.timeout_seconds, headers={"User-Agent": sources.user_agent})


async def fetch_bytes(client: httpx.AsyncClient, url: str, max_bytes: int) -> bytes:
    """
    The response's body, read as it arrives. httpx.HTTPError when the host refuses, redirects or cannot be reached,
    ValueError as soon as the body, decompressed, passes `max_bytes`: the rest is not read.
    """
    body = bytearray()

    async with client.stream("GET", url) as response:
        response.raise_for_status()

        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > max_bytes:
                raise ValueError(f"the response has more than {max_bytes} bytes")

            body.extend(chunk)

    return bytes(body)


def plain_text(markup: str | None) -> str:
    """A feed's text as plain text on one line: its tags removed and its entities read."""
    return " ".join(BeautifulSoup(markup or "", "html.parser").get_text(" ").split())


def child_text(item: ElementTree.Element, name: str) -> str | None:
    found = item.find(name)
    return found.text if found is not None else None


def published(stamp: str | None, fetched_at: datetime) -> datetime:
    """An item's pubDate as an instant, read as UTC where it names no zone; `fetched_at` where the item has none that reads."""
    try:
        read = parsedate_to_datetime((stamp or "").strip())
    except ValueError:
        return fetched_at

    return read if read.tzinfo is not None else read.replace(tzinfo=UTC)


def refuse_document_type(*declaration: object) -> None:
    raise ValueError("the feed declares a document type")


def feed_root(page: bytes) -> ElementTree.Element:
    """
    The root of the XML `page`, in the encoding it declares. The parser itself refuses a document type where the
    declaration starts, before anything inside it is read, so no entity is ever defined. expat.ExpatError for what is
    no XML, ValueError for a document type.
    """
    tree = ElementTree.TreeBuilder()
    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = refuse_document_type
    parser.StartElementHandler = tree.start
    parser.EndElementHandler = tree.end
    parser.CharacterDataHandler = tree.data
    parser.Parse(page, True)

    return tree.close()


def feed_items(page: bytes, source: InformationSource, summary_length: int, fetched_at: datetime) -> Iterator[Article]:
    """
    The items of an RSS 2.0 feed that have a title and an http or https address, in the feed's order: the title and
    the feed's own description as plain text, the description cut at `summary_length` and left out where it only
    repeats the title. expat.ExpatError for what is no XML, ValueError for a feed that declares a document type.
    """
    for item in feed_root(page).iter("item"):
        title = plain_text(child_text(item, "title"))
        url = (child_text(item, "link") or "").strip()
        summary = plain_text(child_text(item, "description"))[:summary_length]

        if not title or urlsplit(url).scheme not in {"http", "https"}:
            continue

        yield Article(
            stock_id=MarketScope.WORLD.value,
            source=source,
            title=title,
            content="" if summary == title else summary,
            url=url,
            content_type=ContentType.NEWS,
            published_at=published(child_text(item, "pubDate"), fetched_at),
            fetched_at=fetched_at,
        )


def table_rows(page: bytes, table_format: TableFormat) -> list[dict[str, Any]]:
    text = page.decode("utf-8-sig")

    match table_format:
        case TableFormat.JSON:
            rows = json.loads(text)
            return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        case TableFormat.CSV:
            return list(csv.DictReader(StringIO(text)))


def table_readings(page: bytes, feed: WorldIndicatorFeed) -> Iterator[IndicatorReading]:
    """Each row's reading of each indicator the feed names, where the row holds a number for it. ValueError for an unreadable day."""
    for row in table_rows(page, feed.format):
        day = read_day(str(row[feed.date_field]), feed.date_format)

        for field, indicator in feed.fields.items():
            try:
                yield IndicatorReading(indicator=indicator, day=day, value=float(str(row.get(field, "")).replace(",", "")))
            except ValueError:
                continue


def read_day(written: str, date_format: str) -> date:
    return datetime.strptime(written.strip(), date_format).date()
