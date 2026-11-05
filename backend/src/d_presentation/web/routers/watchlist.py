from fastapi import APIRouter
from fastapi.exceptions import RequestValidationError

from d_presentation.dependencies import ApiToken, RuntimeDependency
from d_presentation.web.schemas import StockIdsRequest, WatchlistAdditionResponse, WatchlistEntryResponse, WatchlistRemovalResponse

router = APIRouter(prefix="/watchlist", tags=["Watchlist"], dependencies=[ApiToken])


@router.get("")
async def get_watchlist(runtime: RuntimeDependency) -> list[WatchlistEntryResponse]:
    """Every active entry: one per stock and watchlist type. A MANUAL entry never expires; TECHNICAL and BUZZ entries do."""
    entries = await runtime.watchlist_repository.get_active()
    names = {stock.stock_id: stock.name for stock in await runtime.stock_provider.get_all()}
    return [
        WatchlistEntryResponse(
            stock_id=entry.stock_id,
            name=names.get(entry.stock_id),
            watchlist_type=entry.watchlist_type,
            created_at=entry.created_at,
            expires_at=entry.expires_at,
        )
        for entry in sorted(entries, key=lambda entry: (entry.stock_id, entry.watchlist_type))
    ]


@router.post("/manual")
async def add_to_manual_watchlist(body: StockIdsRequest, runtime: RuntimeDependency) -> WatchlistAdditionResponse:
    """
    Adds listed stocks to the MANUAL watchlist, as menu 4 does after an analysis. An unlisted ID adds nothing at all and
    answers 422; an unavailable listing answers 503.
    """
    stocks, addition = await runtime.pipeline.watch_manually(body.stock_ids)

    if addition is None:
        listed = {stock.stock_id for stock in stocks}
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "stock_ids", index),
                    "msg": f"Not a listed stock: {stock_id}",
                    "type": "unlisted_stock",
                    "input": stock_id,
                }
                for index, stock_id in enumerate(body.stock_ids)
                if stock_id not in listed
            ]
        )

    return WatchlistAdditionResponse.model_validate(addition)


@router.post("/manual/remove")
async def remove_from_manual_watchlist(body: StockIdsRequest, runtime: RuntimeDependency) -> WatchlistRemovalResponse:
    """Takes stocks off the MANUAL watchlist only. A TECHNICAL or BUZZ entry of the same stock stays until it expires."""
    stock_ids = body.stock_ids
    removed = await runtime.pipeline.unwatch_manually(stock_ids)

    return WatchlistRemovalResponse(
        removed_stock_ids=removed, absent_stock_ids=[stock_id for stock_id in stock_ids if stock_id not in removed]
    )
