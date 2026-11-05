from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, status

from a_domain.rules.market.breadth import MarketBreadth
from a_domain.types.enums import MarketIndex
from d_presentation.dependencies import ApiToken, RuntimeDependency
from d_presentation.web.schemas import (
    DailyBarResponse,
    IndexHistoryResponse,
    ListedStockResponse,
    StockHistoryResponse,
    StockTechnicalResponse,
)

router = APIRouter(prefix="/market", tags=["Market data"])

StockIdPath = Annotated[str, Path(pattern=r"^[0-9A-Za-z]{1,10}$")]
BarCount = Annotated[int, Query(ge=20, le=500)]

UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "The exchange listing could not be loaded."}
}
NOT_LISTED: dict[int | str, dict[str, Any]] = {status.HTTP_404_NOT_FOUND: {"description": "Not a listed stock."}}


@router.get("/stocks", responses=UNAVAILABLE)
async def search_stocks(
    runtime: RuntimeDependency, query: Annotated[str, Query(min_length=1, max_length=40)]
) -> list[ListedStockResponse]:
    """Listed and OTC stocks whose code or name matches, best first, each with its latest official close. Public."""
    return [ListedStockResponse.model_validate(stock) for stock in await runtime.pipeline.search_stocks(query)]


@router.get("/most-traded", responses=UNAVAILABLE)
async def get_most_traded(runtime: RuntimeDependency) -> list[ListedStockResponse]:
    """The latest session's most traded stocks in the TWSE and TPEX daily listings, with that session's bar. Public."""
    return [ListedStockResponse.model_validate(stock) for stock in await runtime.pipeline.load_most_traded()]


@router.get("/breadth", responses=UNAVAILABLE)
async def get_market_breadth(runtime: RuntimeDependency) -> MarketBreadth:
    """
    The latest session's advancers, decliners and unchanged stocks in the TWSE and TPEX daily listings, each with the
    exchange's own change, and the same per industry with the average change in percent. Public.
    """
    return await runtime.pipeline.load_market_breadth()


@router.get("/indexes/{index}")
async def get_index_history(index: MarketIndex, runtime: RuntimeDependency, bars: BarCount = 250) -> IndexHistoryResponse:
    """
    One market index's completed daily bars, oldest first, from the history cache the stock pages share. Public. Like
    a stock's history, it fetches no realtime quote.
    """
    history = await runtime.pipeline.load_index_history(index, bars)

    return IndexHistoryResponse(index=index, bars=[DailyBarResponse.model_validate(bar) for bar in history])


@router.get("/stocks/{stock_id}", responses=NOT_LISTED)
async def get_stock_history(stock_id: StockIdPath, runtime: RuntimeDependency, bars: BarCount = 250) -> StockHistoryResponse:
    """
    One stock's completed daily bars, oldest first, from the history cache the workflows share. Public. It fetches
    no realtime quote: the latest bar is the last settled session's close.
    """
    result = await runtime.pipeline.load_stock_history(stock_id, bars)

    if not result.manual_stocks:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{stock_id} is not a listed stock, or the exchange listing is unavailable.")

    stock = result.manual_stocks[0]

    return StockHistoryResponse(
        stock=ListedStockResponse.model_validate(stock),
        bars=[DailyBarResponse.model_validate(bar) for bar in stock.ohlcv],
        notes=[*result.stats.errors, *result.stats.execution_log],
    )


@router.get("/stocks/{stock_id}/technical", dependencies=[ApiToken], responses=NOT_LISTED)
async def get_stock_technical(stock_id: StockIdPath, runtime: RuntimeDependency) -> StockTechnicalResponse:
    """
    The owner's active strategy applied to the stock exactly as a run applies it, with each indicator's value at every
    bar it read. Private: it reads the owner's saved strategy.
    """
    strategy, result = await runtime.pipeline.evaluate_stock(stock_id)

    if not result.manual_stocks:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{stock_id} is not a listed stock, or the exchange listing is unavailable.")

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
