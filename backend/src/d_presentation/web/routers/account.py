from datetime import date

from fastapi import APIRouter

from d_presentation.dependencies import ApiToken, RuntimeDependency
from d_presentation.web.schemas import AccountAsOfResponse, AccountHistoryResponse, AccountValueResponse

router = APIRouter(prefix="/account", tags=["Account"])


@router.get("/history", dependencies=[ApiToken])
async def get_account_history(runtime: RuntimeDependency, as_of: date | None = None) -> AccountHistoryResponse:
    """Menu 7: the account now, its equity curve, and the account at the end of `as_of`. It never orders and records no run."""
    status = await runtime.pipeline.load_account_history(as_of)
    snapshot = status.account_as_of

    return AccountHistoryResponse(
        current=AccountValueResponse.model_validate(status.account),
        live_stock_ids=sorted(status.live_stock_ids),
        equity_curve={day: AccountValueResponse.model_validate(account) for day, account in status.equity_curve.items()},
        as_of=None
        if snapshot is None
        else AccountAsOfResponse(last_fill_at=snapshot.taken_at, value=AccountValueResponse.model_validate(snapshot.account)),
        execution_provider=runtime.config.trading.execution_provider,
        order_mode=runtime.config.trading.order_mode,
    )
