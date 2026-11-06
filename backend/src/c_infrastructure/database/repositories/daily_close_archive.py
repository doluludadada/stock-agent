import re
from collections import Counter
from datetime import datetime, timedelta
from typing import override

from sqlalchemy import func
from sqlalchemy.exc import DBAPIError
from sqlmodel import col, select

from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.daily_close_archive import (
    ArchivedMonth,
    ArchivedQuarter,
    ArchivedSession,
    IDailyCloseArchive,
    OpenDataDownload,
)
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import FinancialStatement, MarketIndex
from a_domain.types.errors import RealtimeQuotesUnavailable
from a_domain.types.values import FiscalQuarter
from b_application.config.sources_config import ExchangeSources
from c_infrastructure.database.db_connector import UPSERT, DatabaseConnector
from c_infrastructure.database.models.daily_close_archive_dto import (
    DailyCloseDTO,
    ExchangeNewsDTO,
    FinancialReportDTO,
    IndexCloseDTO,
    MaterialInformationDTO,
    MonthlyRevenueDTO,
    ValuationRatiosDTO,
    YearToDateEpsDTO,
)


class SqlDailyCloseArchive(IDailyCloseArchive):
    """
    The archive in daily_close_archive, index_close_archive, material_information_archive, quarter_eps_archive,
    valuation_ratio_archive, financial_report_archive, monthly_revenue_archive and exchange_news_archive, shared by every
    owner. A save is one upsert per table, so the Web API's timer and `just archive-closes` saving the same data at once
    never collide, and each table commits on its own: a table the database refuses is logged by its name, and the others
    are still saved, since the source serves the rest only until its next period. A read of history takes the sessions
    of its window's two dates, as the market clock dates them; a read of news takes the announcements and the TWSE news
    of the last `material_information_days`, a news item dated by its day and stamped at that day's session close.
    """

    def __init__(
        self,
        db: DatabaseConnector,
        market_clock: IMarketClock,
        exchange: ExchangeSources,
        material_information_days: int,
        logger: ILoggingProvider,
    ) -> None:
        self._db = db
        self._logger = logger
        self._market_clock = market_clock
        self._summary = exchange.financial_reports.summary
        self._stock_codes = re.compile(exchange.exchange_news.stock_code_pattern)
        self._material_information_window = timedelta(days=material_information_days)

    @override
    async def save(self, download: OpenDataDownload) -> None:
        session_of = self._market_clock.to_trading_date
        rows = {
            DailyCloseDTO: [
                DailyCloseDTO.from_domain(stock, bar, session_of(bar.ts)) for stock in download.stocks for bar in stock.ohlcv
            ],
            IndexCloseDTO: [
                IndexCloseDTO.from_domain(market, bar, session_of(bar.ts)) for market, bars in download.indexes.items() for bar in bars
            ],
            MaterialInformationDTO: [MaterialInformationDTO.from_domain(article) for article in download.material_information],
            YearToDateEpsDTO: [YearToDateEpsDTO.from_domain(stock_id, eps) for stock_id, eps in download.quarter_eps.items()],
            ValuationRatiosDTO: [ValuationRatiosDTO.from_domain(ratios) for ratios in download.valuation_ratios],
            FinancialReportDTO: [FinancialReportDTO.from_domain(report) for report in download.financial_reports],
            MonthlyRevenueDTO: [MonthlyRevenueDTO.from_domain(revenue) for revenue in download.monthly_revenues],
            ExchangeNewsDTO: [ExchangeNewsDTO.from_domain(news) for news in download.exchange_news],
        }

        for table, dtos in rows.items():
            if saved := [dto.model_dump() for dto in dtos]:
                try:
                    async with self._db.get_session() as session:
                        statement = UPSERT[session.get_bind().dialect.name](table)
                        keys = [column.name for column in statement.table.primary_key]
                        replaced = {name: statement.excluded[name] for name in saved[0] if name not in keys}
                        await session.execute(statement.on_conflict_do_update(index_elements=keys, set_=replaced), saved)
                        await session.commit()
                except DBAPIError as error:
                    self._logger.error(f"Could not save {table.__tablename__}; the other tables are saved on their own: {error.orig}")

    @override
    async def sessions(self) -> list[ArchivedSession]:
        async with self._db.get_session() as session:
            counts = [
                {day: count for day, count in (await session.execute(select(day_column, func.count()).group_by(day_column))).all()}
                for day_column in (
                    col(DailyCloseDTO.session_date),
                    col(IndexCloseDTO.session_date),
                    col(ValuationRatiosDTO.session_date),
                    col(ExchangeNewsDTO.published_on),
                )
            ]
            announced = (await session.execute(select(col(MaterialInformationDTO.announced_at)))).scalars().all()

        stocks, indexes, ratios, news = counts
        announcements = Counter(self._market_clock.to_market_datetime(moment).date() for moment in announced)
        return [
            ArchivedSession(
                session_date=day,
                stocks=stocks.get(day, 0),
                indexes=indexes.get(day, 0),
                valuation_ratios=ratios.get(day, 0),
                material_information=announcements.get(day, 0),
                exchange_news=news.get(day, 0),
            )
            for day in sorted(stocks.keys() | indexes.keys() | ratios.keys() | announcements.keys() | news.keys())
        ]

    @override
    async def quarters(self) -> list[ArchivedQuarter]:
        eps_period = (col(YearToDateEpsDTO.year), col(YearToDateEpsDTO.quarter))
        report_period = (col(FinancialReportDTO.year), col(FinancialReportDTO.quarter), col(FinancialReportDTO.statement))

        async with self._db.get_session() as session:
            eps_rows = (await session.execute(select(*eps_period, func.count()).group_by(*eps_period))).all()
            report_rows = (await session.execute(select(*report_period, func.count()).group_by(*report_period))).all()

        eps = {FiscalQuarter(year, quarter): count for year, quarter, count in eps_rows}
        reports = {
            (FiscalQuarter(year, quarter), FinancialStatement(statement)): count for year, quarter, statement, count in report_rows
        }
        return [
            ArchivedQuarter(
                quarter=quarter,
                eps=eps.get(quarter, 0),
                balance_sheets=reports.get((quarter, FinancialStatement.BALANCE_SHEET), 0),
                income_statements=reports.get((quarter, FinancialStatement.INCOME_STATEMENT), 0),
            )
            for quarter in sorted(eps.keys() | {quarter for quarter, _ in reports})
        ]

    @override
    async def months(self) -> list[ArchivedMonth]:
        period = (col(MonthlyRevenueDTO.year), col(MonthlyRevenueDTO.month))

        async with self._db.get_session() as session:
            rows = (await session.execute(select(*period, func.count()).group_by(*period).order_by(*period))).all()

        return [ArchivedMonth(year=year, month=month, companies=count) for year, month, count in rows]

    @override
    async def financials(self, stock_id: str) -> tuple[list[QuarterFinancials], list[MonthlyRevenue]]:
        reports = select(FinancialReportDTO).where(col(FinancialReportDTO.stock_id) == stock_id)
        eps_rows = select(YearToDateEpsDTO).where(col(YearToDateEpsDTO.stock_id) == stock_id)
        months = (col(MonthlyRevenueDTO.year), col(MonthlyRevenueDTO.month))
        revenues = select(MonthlyRevenueDTO).where(col(MonthlyRevenueDTO.stock_id) == stock_id).order_by(*months)

        async with self._db.get_session() as session:
            filed_reports = (await session.execute(reports)).scalars().all()
            filed_eps = (await session.execute(eps_rows)).scalars().all()
            revenue_rows = (await session.execute(revenues)).scalars().all()

        filed: dict[FiscalQuarter, list[FinancialReportDTO]] = {}

        for report in filed_reports:
            filed.setdefault(FiscalQuarter(report.year, report.quarter), []).append(report)

        eps = {FiscalQuarter(row.year, row.quarter): row.eps for row in filed_eps}
        quarters = [
            FinancialReportDTO.summarize(quarter, filed.get(quarter, []), eps.get(quarter), self._summary)
            for quarter in sorted(filed.keys() | eps.keys())
        ]
        return quarters, [revenue.to_domain() for revenue in revenue_rows]

    @override
    async def session_count(self) -> int:
        async with self._db.get_session() as session:
            return (await session.execute(select(func.count(func.distinct(col(DailyCloseDTO.session_date)))))).scalar_one()

    @override
    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        first, last = self._market_clock.to_trading_date(start_date), self._market_clock.to_trading_date(end_date)
        statement = (
            select(DailyCloseDTO)
            .where(col(DailyCloseDTO.stock_id).in_([stock.stock_id for stock in stocks]))
            .where(col(DailyCloseDTO.session_date).between(first, last))
            .order_by(col(DailyCloseDTO.stock_id), col(DailyCloseDTO.session_date))
        )

        async with self._db.get_session() as session:
            rows = (await session.execute(statement)).scalars().all()

        bars: dict[str, list[Ohlcv]] = {}

        for row in rows:
            bars.setdefault(row.stock_id, []).append(row.to_domain(self._market_clock.session_close(row.session_date)))

        return bars

    @override
    async def fetch_index_history(self, index: MarketIndex, start_date: datetime, end_date: datetime) -> list[Ohlcv]:
        first, last = self._market_clock.to_trading_date(start_date), self._market_clock.to_trading_date(end_date)
        statement = (
            select(IndexCloseDTO)
            .where(col(IndexCloseDTO.market) == index.market.value)
            .where(col(IndexCloseDTO.session_date).between(first, last))
            .order_by(col(IndexCloseDTO.session_date))
        )

        async with self._db.get_session() as session:
            rows = (await session.execute(statement)).scalars().all()

        return [row.to_domain(self._market_clock.session_close(row.session_date)) for row in rows]

    @override
    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        raise RealtimeQuotesUnavailable("The open-data archive holds settled daily closes only, never a realtime quote.")

    @override
    async def fetch_news(self, stock_id: str, limit: int = 10) -> list[Article]:
        now = self._market_clock.now()
        since = now - self._material_information_window
        announcements = (
            select(MaterialInformationDTO)
            .where(col(MaterialInformationDTO.stock_id) == stock_id)
            .where(col(MaterialInformationDTO.announced_at) >= since)
            .order_by(col(MaterialInformationDTO.announced_at).desc())
            .limit(limit)
        )
        news = select(ExchangeNewsDTO).where(col(ExchangeNewsDTO.published_on) >= self._market_clock.to_market_datetime(since).date())

        async with self._db.get_session() as session:
            filed = [row.to_domain(now) for row in (await session.execute(announcements)).scalars()]
            naming = [
                item.to_domain(stock_id, self._market_clock.session_close(item.published_on), now)
                for item in (await session.execute(news)).scalars()
                if stock_id in self._stock_codes.findall(item.title)
            ]

        return sorted(filed + naming, key=lambda article: article.published_at, reverse=True)[:limit]

    @override
    def save_as_md_file(self, stock_id: str, articles: list[Article]) -> None:
        """The archive holds every announcement it serves, so it writes no other copy."""
