import re
from collections import Counter

import httpx
from bs4 import BeautifulSoup

from a_domain.model.market.stock import Stock
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import CandidateSource


class PttProvider(ISocialMediaProvider):
    """
    Scrapes PTT Stock board to find trending stock tickers using BeautifulSoup4.
    """

    # TODO:I believe there's a better way to write it better, also i might need another one.
    """
    PTT_STOCK = "PTT_STOCK"
    PTT_GOSSIPING = "PTT_GOSSIPING"
    There're two values in enums. In my original plan it should search stock and gossiping.
    however, i think gossiping one is full of unuseful info
    which we should avoid.
    Also i think it should be saved as an artichle?
    """
    PTT_STOCK_URL = "https://www.ptt.cc/bbs/Stock/index.html"

    def __init__(self, logger: ILoggingProvider):
        self._logger = logger
        # Bypass the "Over 18" age restriction page on PTT
        self._cookies = {"over18": "1"}

    async def get_trending_stocks(self, limit: int = 5) -> list[Stock]:
        self._logger.info("Scanning PTT Stock board for trending tickers ...")

        async with httpx.AsyncClient(timeout=10.0, cookies=self._cookies) as client:
            try:
                resp = await client.get(self.PTT_STOCK_URL)
                resp.raise_for_status()

                # TODO: Better way to write? there's a hard-code here.
                # Parse the HTML safely using BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")

                # Find all div elements with the class 'title'
                title_divs = soup.find_all("div", class_="title")

                mentions = []
                for div in title_divs:
                    a_tag = div.find("a")
                    if not a_tag:
                        # Skip posts that have been deleted by moderators
                        continue

                    title_text = a_tag.get_text(strip=True)

                    # TODO: Is it a good logic? to fetch all of useful data?
                    # Extract 4-digit stock tickers (e.g., "2330", "2603") from the clean title text
                    tickers = re.findall(r"\b[1-9]\d{3}\b", title_text)
                    mentions.extend(tickers)

                if not mentions:
                    self._logger.debug("No stock tickers found on the first page of PTT.")
                    return []

                # Count frequencies of each ticker
                counter = Counter(mentions)
                #? what's counter using for? count?
                top_tickers = counter.most_common(limit)

                stocks: list[Stock] = []
                for stock_id, count in top_tickers:
                    stock = Stock(
                        stock_id=stock_id,
                        source=CandidateSource.SOCIAL_BUZZ,
                        trigger_reason=f"PTT Trending: mentioned {count} times",
                    )
                    stocks.append(stock)
                    self._logger.debug(f"Found trending stock: {stock_id} ({count} mentions)")

                return stocks

            except httpx.RequestError as e:
                self._logger.error(f"HTTP request failed while fetching PTT: {e}")
                return []
            except Exception as e:
                self._logger.error(f"Unexpected error parsing PTT: {e}")
                return []
