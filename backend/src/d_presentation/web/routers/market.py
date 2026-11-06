from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, status

from a_domain.rules.market.breadth import MarketBreadth
from a_domain.types.enums import MarketIndex
from b_application.config.sources_config import OpenDataAttribution
from d_presentation.web.schemas import (
    ArchiveStatusResponse,
    AudienceResponse,
    DailyBarResponse,
    IndexHistoryResponse,
    ListedStockResponse,
    StockFinancialsResponse,
    StockHistoryResponse,
    StockTechnicalResponse,
)
from d_presentation.web.session import NotFound, PrivateAccess, RuntimeDependency, SignedOutPipeline, UserPipeline

router = APIRouter(prefix="/market", tags=["Market data"])

StockIdPath = Annotated[str, Path(pattern=r"^[0-9A-Za-z]{1,10}$")]
BarCount = Annotated[int, Query(ge=20, le=500)]

UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "The exchange listing could not be loaded."}
}
NOT_LISTED: dict[int | str, dict[str, Any]] = {status.HTTP_404_NOT_FOUND: {"description": "Not a listed stock."}}


@router.get("/stocks", responses=UNAVAILABLE)
async def search_stocks(
    pipeline: SignedOutPipeline, query: Annotated[str, Query(min_length=1, max_length=40)]
) -> list[ListedStockResponse]:
    """Listed and OTC stocks whose code or name matches, best first, each with its latest official close. Public."""
    return [ListedStockResponse.model_validate(stock) for stock in await pipeline.search_stocks(query)]


@router.get("/most-traded", responses=UNAVAILABLE)
async def get_most_traded(pipeline: SignedOutPipeline) -> list[ListedStockResponse]:
    """The latest session's most traded stocks in the TWSE and TPEX daily listings, with that session's bar. Public."""
    return [ListedStockResponse.model_validate(stock) for stock in await pipeline.load_most_traded()]


@router.get("/breadth", responses=UNAVAILABLE)
async def get_market_breadth(pipeline: SignedOutPipeline) -> MarketBreadth:
    """
    The latest session's advancers, decliners and unchanged stocks in the TWSE and TPEX daily listings, each with the
    exchange's own change, and the same per industry with the average change in percent. Public.
    """
    return await pipeline.load_market_breadth()


@router.get("/indexes/{index}")
async def get_index_history(index: MarketIndex, pipeline: SignedOutPipeline, bars: BarCount = 250) -> IndexHistoryResponse:
    """
    One market index's completed daily bars, oldest first, from the daily history the stock pages share: the Yahoo
    cache, or the open-data archive on a public site. Public. Like a stock's history, it fetches no realtime quote.
    """
    history = await pipeline.load_index_history(index, bars)

    return IndexHistoryResponse(index=index, bars=[DailyBarResponse.model_validate(bar) for bar in history])


@router.get("/archive-status")
async def get_archive_status(pipeline: SignedOutPipeline) -> ArchiveStatusResponse:
    """
    How many sessions of TWSE and TPEX closes the server's open-data archive holds, and how many the built-in strategies
    need. A public site's runs read their daily history from it, so they find no candidate until it holds enough. Public.
    """
    sessions, needed = await pipeline.load_archive_warm_up()

    return ArchiveStatusResponse(sessions=sessions, needed=needed)


@router.get("/audience")
async def get_audience(runtime: RuntimeDependency) -> AudienceResponse:
    """
    Whom the site serves, personal or public, and what that allows, from the one table of each audience's capabilities.
    The web app shows only what the site can do by it; the server still refuses the rest. Public.
    """
    audience = runtime.config.audience

    return AudienceResponse(
        audience=audience,
        open_data_only=audience.open_data_only,
        realtime_quotes=audience.realtime_quotes,
        news_articles=audience.news_articles,
        mops=audience.mops,
    )


@router.get("/attribution")
async def get_attribution(runtime: RuntimeDependency) -> OpenDataAttribution:
    """
    The credit the Open Government Data License v1 requires wherever the site shows the TWSE and TPEX open data or what
    it computes from it: each providing agency with the datasets the site reads, the license's notice, and the
    license's name and address. Public.
    """
    return runtime.config.sources.attribution


@router.get("/stocks/{stock_id}", responses=NOT_LISTED)
async def get_stock_history(stock_id: StockIdPath, pipeline: SignedOutPipeline, bars: BarCount = 250) -> StockHistoryResponse:
    """
    One stock's completed daily bars, oldest first, from the history cache the workflows share. Public. It fetches
    no realtime quote: the latest bar is the last settled session's close.
    """
    result = await pipeline.load_stock_history(stock_id, bars)

    if not result.manual_stocks:
        raise NotFound(f"{stock_id} is not a listed stock, or the exchange listing is unavailable.")

    stock = result.manual_stocks[0]

    return StockHistoryResponse(
        stock=ListedStockResponse.model_validate(stock),
        bars=[DailyBarResponse.model_validate(bar) for bar in stock.ohlcv],
        notes=[*result.stats.errors, *result.stats.execution_log],
    )


@router.get("/stocks/{stock_id}/financials")
async def get_stock_financials(stock_id: StockIdPath, pipeline: SignedOutPipeline) -> StockFinancialsResponse:
    """
    One stock's financials from the server's open-data archive: each archived quarter's revenue, gross profit,
    operating income, net income and EPS of the year to the quarter's end, its total assets, liabilities and equity at
    the quarter's end and its book value per share, and each archived month's revenue with its changes. Amounts are in
    thousands of TWD, per-share figures in TWD and changes in percent; a figure the company's industry format does not
    report is null. Both lists are empty for a stock the archive holds nothing of. Public.
    """
    quarters, monthly_revenues = await pipeline.load_financials(stock_id)

    return StockFinancialsResponse(stock_id=stock_id, quarters=quarters, monthly_revenues=monthly_revenues)


@router.get("/stocks/{stock_id}/technical", responses=NOT_LISTED, dependencies=[PrivateAccess])
async def get_stock_technical(stock_id: StockIdPath, pipeline: UserPipeline) -> StockTechnicalResponse:
    """
    The owner's active strategy applied to the stock exactly as a run applies it, with each indicator's value at every
    bar it read. Private: it reads the owner's saved strategy.
    """
    strategy, result = await pipeline.evaluate_stock(stock_id)

    if not result.manual_stocks:
        raise NotFound(f"{stock_id} is not a listed stock, or the exchange listing is unavailable.")

    stock = result.manual_stocks[0]

    return StockTechnicalResponse(
        stock_id=stock.stock_id,
        strategy=strategy,
        required_bars=strategy.required_bars,
        bar_times=[bar.ts for bar in stock.ohlcv],
        latest_price=stock.current_price,
        report=stock.technical_report,
        readings=result.indicator_readings,
        notes=[*result.stats.errors, *result.stats.execution_log],
    )
