from datetime import date

from fastapi import APIRouter

from d_presentation.dependencies import RuntimeDependency
from d_presentation.web.schemas import AccountAsOfResponse, AccountHistoryResponse, AccountValuationResponse, EquityPointResponse

router = APIRouter(prefix="/account", tags=["Account"])


@router.get("/history")
async def get_account_history(runtime: RuntimeDependency, as_of: date | None = None) -> AccountHistoryResponse:
    """Menu 7: the account now, its equity curve, and the account at the end of `as_of`. It never orders and records no run."""
    report = await runtime.account_history.execute(as_of=as_of)

    return AccountHistoryResponse(
        current=AccountValuationResponse.model_validate(report.current),
        live_stock_ids=sorted(report.live_stock_ids),
        equity_curve=[EquityPointResponse.model_validate(point) for point in report.equity_curve],
        as_of=None
        if report.as_of is None
        else AccountAsOfResponse(
            last_fill_at=report.as_of[0].taken_at, valuation=AccountValuationResponse.model_validate(report.as_of[1])
        ),
    )
