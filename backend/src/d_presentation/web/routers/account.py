from datetime import date
from typing import Any

from fastapi import APIRouter, status

from a_domain.model.trading.account import AccountOpening
from a_domain.types.enums import ExecutionProvider, Feature
from d_presentation.web.schemas import (
    AccountAsOfResponse,
    AccountHistoryResponse,
    AccountValueResponse,
    BrokerageAccountResponse,
    BrokerageStatementResponse,
    BrokerResponse,
    ErrorResponse,
    PageLimit,
    PageOffset,
    ResetRequest,
    RunReference,
    TradeResponse,
)
from d_presentation.web.session import (
    AccountShown,
    BrokerPipeline,
    CurrentUser,
    PrivateAccess,
    RealBrokerHolder,
    RuntimeDependency,
    UserPipeline,
    WorkflowRunsDependency,
    shown_features,
    shows,
)
from d_presentation.web.workflow_runs import RunInProgress

router = APIRouter(prefix="/account", tags=["Account"], dependencies=[PrivateAccess])


SINOPAC_READ: dict[int | str, dict[str, Any]] = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "broker_not_answering: SinoPac did not answer a read of the account in time, or answered an error. Ask again.",
    }
}

BROKER_READ: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": (
            "real_broker_refused: a real broker's account, asked by a user who is not an administrator. "
            "broker_unavailable: the real broker has no login up on this site now."
        ),
    },
    **SINOPAC_READ,
}


@router.get("/brokers")
async def get_brokers(runtime: RuntimeDependency, user: CurrentUser) -> list[BrokerResponse]:
    """
    The brokers the site lets the user order on (features.*) and the user may choose for Buzz, Intraday or a manual
    BUY now, the mock account first, each with what a run's confirmation names: a real broker's server and its BUY
    limits. SinoPac is listed only while features.sinopac_ordering shows the user ordering there: it is off by default.
    """
    config = runtime.config
    return [
        BrokerResponse(
            broker=broker,
            server=config.shioaji.server if broker.real else None,
            max_order_equity_pct=config.trading.max_order_equity_pct if broker.real else None,
            max_daily_buy_equity_pct=config.trading.max_daily_buy_equity_pct if broker.real else None,
        )
        for broker in runtime.brokers_for(user)
        if broker.ordering_feature in shown_features(runtime, user)
    ]


@router.get("/brokerage", responses=SINOPAC_READ, dependencies=[shows(Feature.SINOPAC_ACCOUNT), RealBrokerHolder])
async def get_brokerage_account(runtime: RuntimeDependency, user: CurrentUser, pipeline: UserPipeline) -> BrokerageAccountResponse:
    """
    The SinoPac account as the broker reports it now, for an administrator the site shows features.sinopac_account:
    the bank balance (the site's figure on the simulation server: `statement.simulation`), the settlements due, the
    positions with the broker's last prices and its own unrealized PnL, today's deals and the sales of the last
    holdings.realized_days days with the PnL the broker says each realized.
    `server` says which server the site logs in to and `switch_refusal` why the switch to the other server would be
    refused (names of unset variables only), `login_up` whether the login is up (`statement` is None while it is
    not), `login_down` whether the site logs in again, `ordering` whether the site lets the user order there
    (features.sinopac_ordering, off by default), and `simulation_initial_cash` the simulation account's starting cash.
    The page switches them through the settings save, PUT /v1/admin/settings. It only reads: it sends no order, whatever
    `ordering` says, and it answers no account number and no credential's value.
    """
    config = runtime.config
    account = await pipeline.load_brokerage_statement()

    return BrokerageAccountResponse(
        server=config.shioaji.server,
        switch_refusal=account.switch_refusal,
        login_up=account.statement is not None,
        login_down=runtime.login_down,
        ordering=ExecutionProvider.SHIOAJI.ordering_feature in shown_features(runtime, user),
        simulation_initial_cash=config.shioaji.simulation_initial_cash if config.shioaji.server.simulation else None,
        statement=None if account.statement is None else BrokerageStatementResponse.model_validate(account.statement),
    )


@router.get("/history", responses=BROKER_READ, dependencies=[AccountShown])
async def get_account_history(
    pipeline: BrokerPipeline, broker: ExecutionProvider = ExecutionProvider.MOCK, as_of: date | None = None, since: date | None = None
) -> AccountHistoryResponse:
    """
    Menu 7 on the `broker` account, the mock account by default: the account now, its equity curve, and the account at
    the end of `as_of`. A held stock is priced at today's realtime quote where the board of GET /v1/market/quotes holds
    one (`live_stock_ids`), which then ends the equity curve too, else at its last daily close. With `since` the
    equity curve holds the days from it on only: a page that holds the curve asks for today alone when a quote moved,
    since the whole curve of an old account is large and slow to value. It asks the broker for no quote, never orders
    and records no run.
    """
    status = await pipeline.load_account_history(as_of, since)
    snapshot = status.account_as_of

    return AccountHistoryResponse(
        current=AccountValueResponse.model_validate(status.account),
        live_stock_ids=sorted(status.live_stock_ids),
        equity_curve={day: AccountValueResponse.model_validate(account) for day, account in status.equity_curve.items()},
        as_of=None
        if snapshot is None
        else AccountAsOfResponse(last_fill_at=snapshot.taken_at, value=AccountValueResponse.model_validate(snapshot.account)),
        execution_provider=broker,
        opening=status.account.opening,
        profit=status.account.profit,
    )


@router.get("/trades", responses=BROKER_READ, dependencies=[AccountShown])
async def get_trades(pipeline: BrokerPipeline, limit: PageLimit = 20, offset: PageOffset = 0) -> list[TradeResponse]:
    """
    Every order of a run on the `broker` account (the mock account by default) that filled at least one share, since
    the mock account opened or every one at a real broker, newest first, each with the run whose decision it carried
    out: a follow's with the run it followed. Ask for limit + 1 to know of a next page.
    """
    trades = await pipeline.load_trades(limit, offset)
    return [TradeResponse(order=order, run=RunReference.model_validate(run)) for order, run in trades]


RESET: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "run_in_progress: a run of the user is still running."}
}


@router.post("/reset", responses=RESET, dependencies=[shows(Feature.MOCK_ACCOUNT)])
async def reset_mock_account(
    body: ResetRequest, pipeline: UserPipeline, user: CurrentUser, runs: WorkflowRunsDependency
) -> AccountOpening:
    """
    Opens the user's mock account again with `initial_cash` and no positions; its equity curve and trades start anew
    and every decision is open to follow again. No run, decision or order is deleted. 409 while a run of the user
    runs, which could order on the account meanwhile.
    """
    if (running := runs.running(user.user_id)) is not None:
        raise RunInProgress(running)

    account = await pipeline.reset_mock_account(body.initial_cash)

    if account.opening is None:
        raise RuntimeError("the mock book reported no opening after its reset")

    return account.opening
