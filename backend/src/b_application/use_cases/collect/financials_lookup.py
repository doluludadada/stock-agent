from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.ports.market.daily_close_archive import IDailyCloseArchive


class FinancialsLookup:
    """One stock's financials as the open-data archive holds them: each archived quarter's figures and each month's revenue."""

    def __init__(self, archive: IDailyCloseArchive) -> None:
        self._archive = archive

    async def execute(self, stock_id: str) -> tuple[list[QuarterFinancials], list[MonthlyRevenue]]:
        return await self._archive.financials(stock_id)
