from datetime import date

from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.fundamentals.trailing_eps import filing_candidates
from a_domain.types.values import FiscalQuarter


class EpsHistoryBackfill:
    """
    Reads every market's MOPS page of year-to-date EPS for each quarter from the one `first` falls in to the latest
    that may be filed, into the pages the site holds (IFundamentalsProvider.fetch_cumulative_eps), which the stock
    page's earnings trend reads. A page already held as final is not fetched again, so a rerun reads only what is
    missing. It answers how many quarters it holds of how many were due. `mops` is None on a site that reads no MOPS
    (public), which reads nothing and answers None.
    """

    def __init__(self, mops: IFundamentalsProvider | None, market_clock: IMarketClock, logger: ILoggingProvider) -> None:
        self._mops = mops
        self._market_clock = market_clock
        self._logger = logger

    async def execute(self, first: date) -> tuple[int, int] | None:
        if self._mops is None:
            return None

        oldest = FiscalQuarter(first.year, (first.month - 1) // 3 + 1)
        due = [filing_candidates(self._market_clock.today())[0]]

        while due[-1] > oldest:
            due.append(due[-1].previous())

        filings = await self._mops.fetch_cumulative_eps([quarter for quarter in due if quarter >= oldest])
        read = sum(filing is not None for filing in filings.values())
        self._logger.info(f"EPS backfill from {oldest}: {read}/{len(filings)} quarters held")

        return read, len(filings)
