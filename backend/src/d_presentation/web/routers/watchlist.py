from fastapi import APIRouter
from fastapi.exceptions import RequestValidationError

from a_domain.types.enums import WatchlistType
from d_presentation.dependencies import RuntimeDependency, WritePermission
from d_presentation.web.schemas import StockIdsRequest, WatchlistAdditionResponse, WatchlistEntryResponse

router = APIRouter(prefix="/watchlist", tags=["Watchlist"])


@router.get("")
async def get_watchlist(runtime: RuntimeDependency) -> list[WatchlistEntryResponse]:
    """Every active entry: one per stock and watchlist type. A MANUAL entry never expires; TECHNICAL and BUZZ entries do."""
    entries = await runtime.watchlist_repository.get_active()
    return [
        WatchlistEntryResponse.model_validate(entry)
        for entry in sorted(entries, key=lambda entry: (entry.stock_id, entry.watchlist_type))
    ]


@router.post("/manual", dependencies=[WritePermission])
async def add_to_manual_watchlist(body: StockIdsRequest, runtime: RuntimeDependency) -> WatchlistAdditionResponse:
    """Adds listed stocks to the MANUAL watchlist, as menu 4 does after an analysis. An unlisted ID adds nothing at all."""
    stocks = [await runtime.stock_provider.get_by_id(stock_id) for stock_id in body.stock_ids]
    unlisted = [
        {"loc": ("body", "stock_ids", index), "msg": f"Not a listed stock: {stock_id}", "type": "unlisted_stock", "input": stock_id}
        for index, (stock_id, stock) in enumerate(zip(body.stock_ids, stocks, strict=True))
        if stock is None
    ]

    if unlisted:
        raise RequestValidationError(unlisted)

    addition = await runtime.watch_stocks.execute([stock for stock in stocks if stock is not None], WatchlistType.MANUAL)

    return WatchlistAdditionResponse.model_validate(addition)
