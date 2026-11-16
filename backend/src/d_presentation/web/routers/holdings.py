from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from fastapi.exceptions import RequestValidationError

from a_domain.types.enums import Feature, HoldingSource
from d_presentation.web.schemas import ErrorResponse, HeldPositionResponse, HoldingRemovalRequest, HoldingRequest, HoldingsResponse
from d_presentation.web.session import (
    CurrentUser,
    HoldingSources,
    NotFound,
    PrivateAccess,
    RuntimeDependency,
    UserPipeline,
    shown_features,
    shows,
)

router = APIRouter(prefix="/holdings", tags=["Holdings"], dependencies=[PrivateAccess, shows(Feature.HOLDINGS)])

RANKING_UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "ranking_unavailable: the site's daily history holds no decision session yet. invalid_request: a bad source.",
    }
}


@router.get("", responses=RANKING_UNAVAILABLE)
async def get_holdings(
    pipeline: UserPipeline,
    runtime: RuntimeDependency,
    user: CurrentUser,
    allowed: HoldingSources,
    sources: Annotated[list[HoldingSource] | None, Query()] = None,
) -> HoldingsResponse:
    """
    The user's holdings as one portfolio, from held data alone: the SinoPac account's positions as the broker lists
    them now (where the site shows the user features.sinopac_account, the user is an administrator and the login is
    up), the mock account's (features.mock_account) and the holdings entered by hand. `sources` narrows them; a source
    the site does not show the user is never read. Each holding stays under its source and counts once: the same stock
    at the broker and entered by hand is two holdings. Each is valued at its stock's last close the site holds, or at
    today's realtime quote where the board of GET /v1/market/quotes holds a newer one (`live_stock_ids`), net of the
    SELL fee and tax, and carries its standing in the monthly ranking as /v1/market/stocks/{id}/ranking answers it,
    or why the ranking leaves it out, and its latest month of revenue with the ranking's acceleration. The portfolio
    says its concentration in the holdings.concentration_positions largest stocks, the share of its value the ranking
    holds now, and the value-weighted score over the scored holdings with their share. The score figures are None for a
    viewer the site does not show the ranking. It is analysis, not advice: nothing here says to buy or sell.
    """
    asked = allowed if sources is None else allowed & frozenset(sources)
    analysis = await pipeline.load_holdings(asked)
    read = {name: getattr(analysis, name) for name in HoldingsResponse.model_fields if name != "asked"}
    response = HoldingsResponse.model_validate({**read, "asked": sorted(asked)})

    if Feature.RANKING in shown_features(runtime, user):
        return response

    unscored = [holding.model_copy(update={"standing": None}) for holding in response.holdings]
    hidden = {"top_share": None, "scored_share": None, "weighted_score": None, "lowest": None, "highest": None}
    return response.model_copy(update={"holdings": unscored, **hidden})


@router.post("/manual")
async def enter_holding(body: HoldingRequest, pipeline: UserPipeline) -> HeldPositionResponse:
    """
    Keeps a holding the user enters by hand, replacing the user's earlier entry of the same stock: one entry per stock.
    It is a note of shares held elsewhere: it orders nothing and touches no account. 422 for a stock the listing does
    not hold; 503 while the listing is unavailable.
    """
    position = await pipeline.enter_holding(body.stock_id, body.quantity, body.average_cost, body.opened_on)

    if position is None:
        raise RequestValidationError(
            [{"loc": ("body", "stock_id"), "msg": f"Not a listed stock: {body.stock_id}", "type": "unlisted_stock"}]
        )

    return HeldPositionResponse.model_validate(position)


REMOVAL: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "The user entered no holding of this stock."}
}


@router.post("/manual/remove", status_code=status.HTTP_204_NO_CONTENT, responses=REMOVAL)
async def remove_holding(body: HoldingRemovalRequest, pipeline: UserPipeline) -> None:
    """Takes the user's hand-entered holding of the stock off the list. A holding of an account is never touched."""
    if not await pipeline.remove_holding(body.stock_id):
        raise NotFound(f"You entered no holding of {body.stock_id}.")
