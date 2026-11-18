"""
Each port that holds a user's data, through the adapters the production factory create_owned_ports builds, over a real
PostgreSQL database, for two owners. For every method of every such port, owner Bob calls it with what Alice saved
and sees none of it, changes none of it, and Alice still reads her own (the control). The first test makes the case
table complete: a port added to OwnedPorts, or a method added to one of its ports, without a case fails here, by name.
"""

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from support.databases import shipped_config
from support.fakes import AiVendor, no_refusal
from support.harness import MARKET_OPEN, harness_settings
from trading_stack import MovableClock, SilentLogger, analysed_stock, run_stats

from a_domain.model.chat.message import Message, MessageRole
from a_domain.model.market.article import Article
from a_domain.model.system.user import User
from a_domain.model.trading.account import Account, AccountSnapshot, Position
from a_domain.model.trading.backtest import Backtest, BacktestInputs
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.rules.trading.order_rule import BrokerLink
from a_domain.types.enums import (
    ExecutionProvider,
    InformationSource,
    OrderType,
    Role,
    SignalSource,
    TimeInForce,
    TradeAction,
    WatchlistType,
)
from a_domain.types.errors import TechnicalSettingsConflictError
from a_domain.types.ids import RunId, UserId
from b_application.config.ai_config import PromptsConfig
from b_application.config.app_config import AppConfig
from c_infrastructure.ai_models.ai_adapter.daily_capped_ai_provider import AiAllowanceSpentError
from c_infrastructure.database.db_connector import DatabaseConnector
from d_presentation.dependencies import OwnedPorts, create_owned_ports

AT = MARKET_OPEN
DAILY_CALLS = 2
CLASSIFIED = '{"posts": [{"index": 1, "label": "bullish", "confidence": 0.9}]}'


@dataclass
class Owners:
    alice: OwnedPorts
    bob: OwnedPorts
    vendor: AiVendor
    owned_ports: Callable[[User | None], OwnedPorts]


def owners_config(folder: Path) -> AppConfig:
    """The shipped settings, with the prompt the sentiment classifier needs and DAILY_CALLS per user."""
    config = shipped_config(folder)
    return config.model_copy(
        update={
            "prompts": PromptsConfig(social_sentiment="Stock {stock_id}\n{posts_text}"),
            "accounts": config.accounts.model_copy(update={"daily_ai_calls": DAILY_CALLS}),
        }
    )


def user_named(user_id: str, role: Role = Role.USER) -> User:
    return User(user_id=UserId(user_id), username=user_id, email=f"{user_id}@example.com", role=role, created_at=AT)


@pytest_asyncio.fixture
async def owners(database: DatabaseConnector, tmp_path: Path) -> AsyncIterator[Owners]:
    vendor = AiVendor(reply=CLASSIFIED)
    config = owners_config(tmp_path)
    owned_ports = create_owned_ports(
        config, database, {config.ai.active_model: vendor}, MovableClock(AT), SilentLogger(), asyncio.Lock()
    )

    yield Owners(alice=owned_ports(user_named("alice")), bob=owned_ports(user_named("bob")), vendor=vendor, owned_ports=owned_ports)


def decision(stock_id: str = "2330") -> TradeSignal:
    return TradeSignal(
        stock_id=stock_id,
        action=TradeAction.BUY,
        quantity=1000,
        price_at_signal=100.0,
        price_observed_at=AT,
        source=SignalSource.COMBINED,
        score=90,
        reason="Alice's reason",
        generated_at=AT,
    )


def order_of(run_id: RunId, signal: TradeSignal) -> Order:
    return Order(
        run_id=run_id,
        decision_id=signal.decision_id,
        stock_id=signal.stock_id,
        action=signal.action,
        order_type=OrderType.LIMIT,
        quantity=signal.quantity,
        limit_price=signal.price_at_signal,
        time_in_force=TimeInForce.IOC,
        created_at=AT,
        updated_at=AT,
    )


@dataclass
class Recorded:
    run_id: RunId
    signal: TradeSignal
    order: Order
    snapshot: AccountSnapshot


async def alice_records_a_run(owners: Owners) -> Recorded:
    journal = owners.alice.journal
    stats = run_stats()
    signal = decision()
    order = order_of(stats.run_id, signal)
    account = await owners.alice.mock_broker.get_account()
    snapshot = AccountSnapshot(taken_at=AT, run_id=stats.run_id, order_id=order.id, account=account)
    await journal.save_run(stats)
    await journal.save_signals(stats.run_id, [signal])
    await journal.save_order(order)
    await journal.save_snapshot(snapshot)
    await journal.save_stock_reports(stats.run_id, [analysed_stock()])
    return Recorded(stats.run_id, signal, order, snapshot)


# ------------------------------------------------------- the journal ------------------------------------------------------- #


async def save_run(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)
    alices = await owners.alice.journal.find_run(recorded.run_id)
    assert alices is not None

    with pytest.raises(IntegrityError):
        await owners.bob.journal.save_run(replace(alices, total_scanned=99))

    assert await owners.alice.journal.find_run(recorded.run_id) == alices


async def save_signals(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)

    with pytest.raises(IntegrityError):
        await owners.bob.journal.save_signals(recorded.run_id, [replace(recorded.signal, reason="Bob's reason")])

    assert [signal.reason for signal in await owners.alice.journal.signals_of(recorded.run_id)] == ["Alice's reason"]


async def save_order(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)

    with pytest.raises(IntegrityError):
        await owners.bob.journal.save_order(replace(recorded.order, quantity=1))

    assert [order.quantity for order in await owners.alice.journal.orders_of(recorded.run_id)] == [1000]


async def save_snapshot(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)
    emptied = replace(recorded.snapshot, account=replace(recorded.snapshot.account, cash=1.0))

    with pytest.raises(IntegrityError):
        await owners.bob.journal.save_snapshot(emptied)

    assert [snapshot.account.cash for snapshot in await owners.alice.journal.snapshots(ExecutionProvider.MOCK)] == [1_000_000]


async def snapshots(owners: Owners) -> None:
    await alice_records_a_run(owners)

    assert await owners.bob.journal.snapshots(ExecutionProvider.MOCK) == []
    [alices] = await owners.alice.journal.snapshots(ExecutionProvider.MOCK)
    assert alices.account.account_id == "alice"


async def save_stock_reports(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)

    with pytest.raises(IntegrityError):
        await owners.bob.journal.save_stock_reports(recorded.run_id, [analysed_stock("2603")])

    assert [stock.stock_id for stock in await owners.alice.journal.stock_reports_of(recorded.run_id)] == ["2330"]


async def stock_reports_of(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)

    assert await owners.bob.journal.stock_reports_of(recorded.run_id) == []
    assert len(await owners.alice.journal.stock_reports_of(recorded.run_id)) == 1


async def recent_runs(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)

    assert await owners.bob.journal.recent_runs(10) == []
    assert [run.run_id for run in await owners.alice.journal.recent_runs(10)] == [recorded.run_id]


async def find_run(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)

    assert await owners.bob.journal.find_run(recorded.run_id) is None
    assert await owners.alice.journal.find_run(recorded.run_id) is not None


async def signals_of(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)

    assert await owners.bob.journal.signals_of(recorded.run_id) == []
    assert len(await owners.alice.journal.signals_of(recorded.run_id)) == 1


async def decision_history(owners: Owners) -> None:
    await alice_records_a_run(owners)

    assert await owners.bob.journal.decision_history("2330") == []
    assert [signal.reason for signal in await owners.alice.journal.decision_history("2330")] == ["Alice's reason"]


async def orders_of(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)

    assert await owners.bob.journal.orders_of(recorded.run_id) == []
    assert await owners.alice.journal.orders_of(recorded.run_id) == [recorded.order]


# ------------------------------------------------------ the watchlist ------------------------------------------------------ #


def entry(stock_id: str, watchlist_type: WatchlistType = WatchlistType.MANUAL) -> WatchlistEntry:
    return WatchlistEntry(stock_id=stock_id, watchlist_type=watchlist_type, created_at=AT, expires_at=None)


async def get_active(owners: Owners) -> None:
    await owners.alice.watchlist_repository.save([entry("2330"), entry("2603", WatchlistType.TECHNICAL)])

    assert await owners.bob.watchlist_repository.get_active() == []
    assert len(await owners.alice.watchlist_repository.get_active()) == 2


async def save(owners: Owners) -> None:
    await owners.alice.watchlist_repository.save([entry("2330")])
    await owners.bob.watchlist_repository.save([entry("2330")])

    assert [found.stock_id for found in await owners.alice.watchlist_repository.get_active()] == ["2330"]
    assert [found.stock_id for found in await owners.bob.watchlist_repository.get_active()] == ["2330"]


async def remove(owners: Owners) -> None:
    await owners.alice.watchlist_repository.save([entry("2330")])

    assert await owners.bob.watchlist_repository.remove(["2330"], WatchlistType.MANUAL) == []
    assert [found.stock_id for found in await owners.alice.watchlist_repository.get_active()] == ["2330"]


# ------------------------------------------------- the hand-entered holdings ------------------------------------------------ #


def holding(stock_id: str, quantity: int = 1000) -> Position:
    return Position(stock_id=stock_id, quantity=quantity, average_cost=100.0, opened_at=AT)


async def get_all_holdings(owners: Owners) -> None:
    await owners.alice.holding_repository.save(holding("2330"))
    await owners.alice.holding_repository.save(holding("0050", 37))

    assert await owners.bob.holding_repository.get_all() == []
    assert [(found.stock_id, found.quantity) for found in await owners.alice.holding_repository.get_all()] == [
        ("0050", 37),
        ("2330", 1000),
    ]


async def save_holding(owners: Owners) -> None:
    await owners.alice.holding_repository.save(holding("2330"))
    await owners.bob.holding_repository.save(holding("2330", 5))
    await owners.bob.holding_repository.save(holding("2330", 7))

    assert [(found.quantity, found.opened_at) for found in await owners.alice.holding_repository.get_all()] == [(1000, AT)]
    assert [found.quantity for found in await owners.bob.holding_repository.get_all()] == [7]


async def remove_holding(owners: Owners) -> None:
    await owners.alice.holding_repository.save(holding("2330"))

    assert await owners.bob.holding_repository.remove("2330") is False
    assert [found.stock_id for found in await owners.alice.holding_repository.get_all()] == ["2330"]
    assert await owners.alice.holding_repository.remove("2330") is True
    assert await owners.alice.holding_repository.get_all() == []


# ------------------------------------------------------ the backtests ------------------------------------------------------ #


def backtest_of(cash: float = 1_000_000) -> Backtest:
    return Backtest(
        created_at=AT,
        strategy_id="trend",
        strategy_name="Trend",
        inputs=BacktestInputs(first=AT.date(), last=AT.date(), initial_cash=cash, buy_score=80, sell_score=30),
        stop_loss_pct=0.1,
        risk_per_trade_pct=0.02,
        equity_curve={AT.date(): Account(cash=cash)},
        benchmark=[],
        trades=[],
    )


async def save_backtest(owners: Owners) -> None:
    alices = backtest_of()
    await owners.alice.backtest_repository.save(alices, keep=5)

    with pytest.raises(IntegrityError):
        await owners.bob.backtest_repository.save(replace(alices, strategy_name="Bob's"), keep=5)

    await owners.bob.backtest_repository.save(backtest_of(cash=1), keep=1)

    assert await owners.alice.backtest_repository.saved() == [alices]


async def saved_backtests(owners: Owners) -> None:
    alices = backtest_of()
    await owners.alice.backtest_repository.save(alices, keep=5)

    assert await owners.bob.backtest_repository.saved() == []
    assert await owners.alice.backtest_repository.saved() == [alices]


async def get_backtest(owners: Owners) -> None:
    alices = backtest_of()
    await owners.alice.backtest_repository.save(alices, keep=5)

    assert await owners.bob.backtest_repository.get(alices.backtest_id) is None
    assert await owners.alice.backtest_repository.get(alices.backtest_id) == alices


async def delete_backtest(owners: Owners) -> None:
    alices = backtest_of()
    await owners.alice.backtest_repository.save(alices, keep=5)

    assert await owners.bob.backtest_repository.delete(alices.backtest_id) is False
    assert await owners.alice.backtest_repository.get(alices.backtest_id) == alices
    assert await owners.alice.backtest_repository.delete(alices.backtest_id) is True


# -------------------------------------------------- the technical settings ------------------------------------------------- #


async def load(owners: Owners) -> None:
    initial = harness_settings()
    alices = await owners.alice.technical_settings_repository.load(initial)
    await owners.alice.technical_settings_repository.save(replace(alices, active_strategy_id="buzz"))

    assert await owners.bob.technical_settings_repository.load(initial) == initial
    assert (await owners.alice.technical_settings_repository.load(initial)).active_strategy_id == "buzz"


async def save_settings(owners: Owners) -> None:
    alices = await owners.alice.technical_settings_repository.load(harness_settings())

    with pytest.raises(TechnicalSettingsConflictError):
        await owners.bob.technical_settings_repository.save(replace(alices, active_strategy_id="buzz"))

    assert await owners.alice.technical_settings_repository.load(harness_settings()) == alices


# ------------------------------------------------------ the mock book ------------------------------------------------------ #


async def alice_buys(owners: Owners) -> Order:
    return await owners.alice.mock_broker.place_order(order_of(run_stats().run_id, decision()), no_refusal, asyncio.Event())


async def connect(owners: Owners) -> None:
    await owners.alice.mock_broker.connect()
    await alice_buys(owners)
    await owners.bob.mock_broker.connect()

    assert (await owners.bob.mock_broker.get_account()).cash == 1_000_000
    assert (await owners.alice.mock_broker.get_account()).cash < 1_000_000


async def link(owners: Owners) -> None:
    """The mock account names no owner in its link: each owner's orders go to that owner's own book."""
    assert owners.alice.mock_broker.link() == owners.bob.mock_broker.link() == BrokerLink(broker=ExecutionProvider.MOCK)


async def get_account(owners: Owners) -> None:
    await alice_buys(owners)
    bobs = await owners.bob.mock_broker.get_account()

    assert (bobs.account_id, bobs.cash, bobs.positions) == ("bob", 1_000_000, [])
    assert [position.stock_id for position in (await owners.alice.mock_broker.get_account()).positions] == ["2330"]


async def open_positions(owners: Owners) -> None:
    await alice_buys(owners)

    assert await owners.bob.mock_broker.open_positions() == []
    assert [position.stock_id for position in await owners.alice.mock_broker.open_positions()] == ["2330"]


async def place_order(owners: Owners) -> None:
    filled = await alice_buys(owners)
    sale = replace(order_of(run_stats().run_id, decision()), action=TradeAction.SELL)

    assert filled.filled_quantity == 1000
    assert (await owners.bob.mock_broker.place_order(sale, no_refusal, asyncio.Event())).filled_quantity == 0
    assert [position.quantity for position in (await owners.alice.mock_broker.get_account()).positions] == [1000]


async def fill(owners: Owners) -> None:
    order = order_of(run_stats().run_id, decision())
    order.submit(now=AT)
    alices = await owners.alice.mock_broker.get_account()
    await owners.alice.mock_broker.fill(order, alices, AT)

    assert (await owners.bob.mock_broker.get_account()).positions == []
    assert [position.stock_id for position in (await owners.alice.mock_broker.get_account()).positions] == ["2330"]


async def reset(owners: Owners) -> None:
    await alice_buys(owners)
    bobs = await owners.bob.mock_broker.get_account()

    await owners.alice.mock_broker.reset(250_000, AT)

    assert await owners.bob.mock_broker.get_account() == bobs
    alices = await owners.alice.mock_broker.get_account()
    assert (alices.cash, alices.positions, alices.opening and alices.opening.initial_cash) == (250_000, [], 250_000)


# ---------------------------------------------------- the counted AI calls ------------------------------------------------- #


def question() -> tuple[Message, ...]:
    return (Message(role=MessageRole.USER, content="?", timestamp=AT),)


async def generate_reply(owners: Owners) -> None:
    for _ in range(DAILY_CALLS):
        await owners.alice.ai_provider.generate_reply(question())

    with pytest.raises(AiAllowanceSpentError):
        await owners.alice.ai_provider.generate_reply(question())

    await owners.bob.ai_provider.generate_reply(question())
    assert owners.vendor.calls == DAILY_CALLS + 1


async def save_response(owners: Owners) -> None:
    """The raw replies go to the vendor adapter's debug folder, which no endpoint serves and which keeps no owner."""
    owners.alice.ai_provider.save_response("2330", "{}")
    owners.bob.ai_provider.save_response("2603", "{}")

    assert owners.vendor.saved == ["2330", "2603"]


# ---------------------------------------------------- the sentiment classifier ---------------------------------------------- #


def post(stock_id: str) -> Article:
    return Article(
        stock_id=stock_id,
        source=InformationSource.PTT_STOCK,
        title=f"[標的] {stock_id}",
        content="Opinion",
        url=f"https://www.ptt.cc/bbs/Stock/{stock_id}.html",
        published_at=AT.astimezone(UTC),
        fetched_at=datetime(2026, 10, 19, tzinfo=UTC),
    )


async def classify(owners: Owners) -> None:
    """The posts and their classifications are public and shared; each owner's classification spends that owner's AI calls."""
    for stock_id in ("2330", "2603"):
        await owners.alice.sentiment_classifier.classify(stock_id, [post(stock_id)])

    with pytest.raises(AiAllowanceSpentError):
        await owners.alice.sentiment_classifier.classify("2317", [post("2317")])

    [classified] = await owners.bob.sentiment_classifier.classify("2317", [post("2317")])
    assert classified.sentiment is not None
    assert owners.vendor.calls == DAILY_CALLS + 1


async def follows_of(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)
    follow = run_stats()
    followed = replace(decision(), source=SignalSource.FOLLOW, followed_decision_id=recorded.signal.decision_id)
    await owners.alice.journal.save_run(follow)
    await owners.alice.journal.save_signals(follow.run_id, [followed])
    await owners.alice.journal.save_order(order_of(follow.run_id, followed))

    assert await owners.bob.journal.follows_of(recorded.run_id) == []
    assert [signal.decision_id for signal, _ in await owners.alice.journal.follows_of(recorded.run_id)] == [followed.decision_id]


async def trades(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)
    filled = replace(recorded.order)
    filled.submit(now=AT)
    filled.fill(filled.quantity, 100.0, 142, 0, now=AT)
    await owners.alice.journal.save_order(filled)

    assert await owners.bob.journal.trades(ExecutionProvider.MOCK, None, 10, 0) == []
    assert [(order.id, run.run_id) for order, run in await owners.alice.journal.trades(ExecutionProvider.MOCK, None, 10, 0)] == [
        (filled.id, recorded.run_id)
    ]


async def first_fill(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)
    workflow = run_stats().workflow
    filled = replace(recorded.order)
    filled.submit(now=AT)
    filled.fill(filled.quantity, 100.0, 142, 0, now=AT)
    await owners.alice.journal.save_order(filled)

    assert await owners.bob.journal.first_fill(workflow, ExecutionProvider.MOCK, None) is None
    assert await owners.alice.journal.first_fill(workflow, ExecutionProvider.MOCK, None) == filled.created_at


async def runs_of(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)
    workflow = run_stats().workflow

    assert await owners.bob.journal.runs_of(workflow, ExecutionProvider.MOCK, None) == []
    assert [run.run_id for run in await owners.alice.journal.runs_of(workflow, ExecutionProvider.MOCK, None)] == [recorded.run_id]


async def buy_orders(owners: Owners) -> None:
    recorded = await alice_records_a_run(owners)

    assert await owners.bob.journal.buy_orders(ExecutionProvider.MOCK, AT) == []
    assert [order.id for order in await owners.alice.journal.buy_orders(ExecutionProvider.MOCK, AT)] == [recorded.order.id]


type Case = Callable[[Owners], Awaitable[None]]

CASES: dict[str, dict[str, Case]] = {
    "journal": {
        "save_run": save_run,
        "save_signals": save_signals,
        "save_order": save_order,
        "save_snapshot": save_snapshot,
        "snapshots": snapshots,
        "save_stock_reports": save_stock_reports,
        "stock_reports_of": stock_reports_of,
        "recent_runs": recent_runs,
        "find_run": find_run,
        "signals_of": signals_of,
        "decision_history": decision_history,
        "orders_of": orders_of,
        "follows_of": follows_of,
        "trades": trades,
        "runs_of": runs_of,
        "first_fill": first_fill,
        "buy_orders": buy_orders,
    },
    "watchlist_repository": {"get_active": get_active, "save": save, "remove": remove},
    "technical_settings_repository": {"load": load, "save": save_settings},
    "mock_broker": {
        "connect": connect,
        "link": link,
        "get_account": get_account,
        "open_positions": open_positions,
        "place_order": place_order,
        "fill": fill,
        "reset": reset,
    },
    "ai_provider": {"generate_reply": generate_reply, "save_response": save_response},
    "sentiment_classifier": {"classify": classify},
    "backtest_repository": {"save": save_backtest, "saved": saved_backtests, "get": get_backtest, "delete": delete_backtest},
    "holding_repository": {"get_all": get_all_holdings, "save": save_holding, "remove": remove_holding},
}
"""Every field of OwnedPorts, the ports dependencies.py builds per owner, and a two-owner case for each method of its adapter."""


def methods_of(adapter: object) -> set[str]:
    """The adapter's public methods: its port's, since an adapter has no other public method (the architecture check)."""
    return {name for name, member in inspect.getmembers(type(adapter), inspect.isfunction) if not name.startswith("_")}


def test_every_owned_port_method_has_an_isolation_case(tmp_path: Path) -> None:
    config = owners_config(tmp_path)
    db = DatabaseConnector(config=config, logger=SilentLogger())
    vendors = {config.ai.active_model: AiVendor()}
    owned = create_owned_ports(config, db, vendors, MovableClock(AT), SilentLogger(), asyncio.Lock())(user_named("alice"))

    assert {name: set(cases) for name, cases in CASES.items()} == {
        field.name: methods_of(getattr(owned, field.name)) for field in fields(OwnedPorts)
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", [pytest.param(case, id=f"{port}.{name}") for port, cases in CASES.items() for name, case in cases.items()]
)
async def test_one_owner_never_reads_or_changes_another_owners_data(owners: Owners, case: Case) -> None:
    await case(owners)
