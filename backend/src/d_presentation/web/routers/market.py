from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, status

from a_domain.rules.market.breadth import MarketBreadth
from a_domain.types.enums import MarketIndex
from d_presentation.web.schemas import (
    DailyBarResponse,
    IndexHistoryResponse,
    ListedStockResponse,
    StockHistoryResponse,
    StockTechnicalResponse,
)
from d_presentation.web.session import NotFound, PrivateAccess, SignedOutPipeline, UserPipeline

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
    One market index's completed daily bars, oldest first, from the history cache the stock pages share. Public. Like
    a stock's history, it fetches no realtime quote.
    """
    history = await pipeline.load_index_history(index, bars)

    return IndexHistoryResponse(index=index, bars=[DailyBarResponse.model_validate(bar) for bar in history])


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
