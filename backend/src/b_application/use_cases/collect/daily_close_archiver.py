from a_domain.ports.market.daily_close_archive import (
    ArchivedMonth,
    ArchivedQuarter,
    ArchivedSession,
    IDailyCloseArchive,
    OpenDataDownload,
)
from a_domain.ports.market.taiwan_stock_provider import ITaiwanStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.errors import ListingUnavailableError


class DailyCloseArchiver:
    """
    Saves what the TWSE and TPEX OpenAPI serve now into the archive: each listed stock's latest official daily bar, as
    the listings are cached, each exchange's own index closes, the material information, the latest quarter's EPS
    statistics, the valuation ratios, the latest quarter's balance sheets and income statements, the latest month's
    revenue and TWSE's own news, each under the date or period its own row names. Saving the same data again changes
    nothing. It answers every date, quarter and month the archive holds.
    """

    def __init__(self, stock_provider: ITaiwanStockProvider, archive: IDailyCloseArchive, logger: ILoggingProvider) -> None:
        self._stock_provider = stock_provider
        self._archive = archive
        self._logger = logger

    async def execute(self) -> tuple[list[ArchivedSession], list[ArchivedQuarter], list[ArchivedMonth]]:
        closes = await self._stock_provider.get_latest_closes()
        stocks = [stock for stock in await self._stock_provider.get_all() if stock.stock_id in closes]

        for stock in stocks:
            stock.load_history([closes[stock.stock_id]])

        download = OpenDataDownload(
            stocks=stocks,
            indexes=await self._stock_provider.fetch_index_closes(),
            material_information=await self._stock_provider.fetch_material_information(),
            quarter_eps=await self._stock_provider.fetch_quarter_eps(),
            valuation_ratios=await self._stock_provider.fetch_valuation_ratios(),
            financial_reports=await self._stock_provider.fetch_financial_reports(),
            monthly_revenues=await self._stock_provider.fetch_monthly_revenues(),
            exchange_news=await self._stock_provider.fetch_exchange_news(),
        )

        if download.is_empty:
            raise ListingUnavailableError("The TWSE and TPEX listings and reports could not be loaded.")

        await self._archive.save(download)
        self._logger.info(
            f"Archived {len(download.stocks)} stock closes, {sum(map(len, download.indexes.values()))} index closes, "
            f"{len(download.material_information)} announcements, {len(download.quarter_eps)} companies' EPS, "
            f"{len(download.valuation_ratios)} stocks' valuation ratios, {len(download.financial_reports)} financial reports, "
            f"{len(download.monthly_revenues)} monthly revenues and {len(download.exchange_news)} TWSE news items."
        )

        return await self._archive.sessions(), await self._archive.quarters(), await self._archive.months()
