from datetime import UTC, date, datetime

import pytest
from trading_stack import SilentLogger

from a_domain.model.trading.order import Order
from a_domain.types.enums import OrderStatus, OrderType, TimeInForce, TradeAction
from a_domain.types.ids import new_decision_id, new_run_id
from b_application.config.app_config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)

pytestmark = pytest.mark.asyncio


async def open_broker(
    tmp_path,
    initial_cash: float = 1_000_000,
    max_fill_quantity: int | None = None,
    create_tables: bool = True,
    bond_etf_tax_exempt_until: date = date(2026, 12, 31),
):
    config = AppConfig(project_root=tmp_path)
    config.mock_trading.initial_cash = initial_cash
    config.mock_trading.max_fill_quantity = max_fill_quantity
    config.market.bond_etf_tax_exempt_until = bond_etf_tax_exempt_until
    db = DatabaseConnector(config=config, logger=SilentLogger())

    if create_tables:
        await db.init_db()

    return db, MockExecutionProvider(db=db, config=config, logger=SilentLogger())


def order(
    action: TradeAction, quantity: int, price: float, time_in_force: TimeInForce = TimeInForce.IOC, stock_id: str = "2330"
) -> Order:
    return Order(
        run_id=new_run_id(),
        decision_id=new_decision_id(),
        stock_id=stock_id,
        action=action,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=price,
        time_in_force=time_in_force,
        created_at=NOW,
        updated_at=NOW,
    )


async def holdings(broker: MockExecutionProvider) -> list[tuple[str, int, float]]:
    return [(position.stock_id, position.quantity, position.average_cost) for position in (await broker.get_account()).positions]


async def cash(broker: MockExecutionProvider) -> float:
    return (await broker.get_account()).cash


async def test_buy_fills_against_a_real_sqlite_file_and_pays_the_fee(tmp_path) -> None:
    db, broker = await open_broker(tmp_path)

    placed = await broker.place_order(order(TradeAction.BUY, 1000, 100))

    assert (placed.status, placed.filled_quantity, placed.average_filled_price, placed.fee, placed.tax) == (
        OrderStatus.FILLED,
        1000,
        100,
        142,
        0,
    )
    assert await cash(broker) == 1_000_000 - 100_142
    assert await holdings(broker) == [("2330", 1000, pytest.approx(100.142))]
    await db.close()


async def test_sell_realizes_pnl_net_of_both_fees_and_the_tax(tmp_path) -> None:
    db, broker = await open_broker(tmp_path)
    await broker.place_order(order(TradeAction.BUY, 1000, 100))

    sold = await broker.place_order(order(TradeAction.SELL, 1000, 110))

    assert (sold.status, sold.fee, sold.tax) == (OrderStatus.FILLED, 156, 330)
    assert sold.realized_pnl == pytest.approx(110_000 - 156 - 330 - 100_142)
    assert await cash(broker) == pytest.approx(1_000_000 - 100_142 + 110_000 - 156 - 330)
    assert await holdings(broker) == []
    await db.close()


async def test_an_etf_sell_pays_the_etf_transaction_tax_from_the_config(tmp_path) -> None:
    db, broker = await open_broker(tmp_path)
    await broker.place_order(order(TradeAction.BUY, 1000, 100, stock_id="0050"))

    sold = await broker.place_order(order(TradeAction.SELL, 1000, 110, stock_id="0050"))

    assert (sold.fee, sold.tax) == (156, 110)
    assert sold.realized_pnl == pytest.approx(110_000 - 156 - 110 - 100_142)
    await db.close()


@pytest.mark.parametrize(("exempt_until", "tax"), [(date(2099, 12, 31), 0), (date(2000, 1, 1), 110)])
async def test_a_bond_etf_sell_pays_no_tax_until_the_configured_exemption_ends(tmp_path, exempt_until: date, tax: int) -> None:
    db, broker = await open_broker(tmp_path, bond_etf_tax_exempt_until=exempt_until)
    await broker.place_order(order(TradeAction.BUY, 1000, 100, stock_id="00679B"))

    sold = await broker.place_order(order(TradeAction.SELL, 1000, 110, stock_id="00679B"))

    assert (sold.status, sold.fee, sold.tax) == (OrderStatus.FILLED, 156, tax)
    assert await cash(broker) == pytest.approx(1_000_000 - 100_142 + 110_000 - 156 - tax)
    await db.close()


async def test_ioc_fills_what_the_market_can_take_and_cancels_the_rest(tmp_path) -> None:
    db, broker = await open_broker(tmp_path, max_fill_quantity=400)

    placed = await broker.place_order(order(TradeAction.BUY, 1000, 100, TimeInForce.IOC))

    assert (placed.status, placed.filled_quantity, placed.fee) == (OrderStatus.CANCELLED, 400, 57)
    assert await cash(broker) == 1_000_000 - 40_057
    assert await holdings(broker) == [("2330", 400, pytest.approx(100.1425))]
    await db.close()


@pytest.mark.parametrize(
    ("max_fill_quantity", "status", "filled"), [(400, OrderStatus.CANCELLED, 0), (None, OrderStatus.FILLED, 1000)]
)
async def test_fok_fills_everything_or_nothing(tmp_path, max_fill_quantity: int | None, status: OrderStatus, filled: int) -> None:
    db, broker = await open_broker(tmp_path, max_fill_quantity=max_fill_quantity)

    placed = await broker.place_order(order(TradeAction.BUY, 1000, 100, TimeInForce.FOK))

    assert (placed.status, placed.filled_quantity) == (status, filled)
    assert sum(quantity for _, quantity, _ in await holdings(broker)) == filled
    await db.close()


async def test_rod_is_rejected_because_nothing_could_fill_its_working_remainder(tmp_path) -> None:
    db, broker = await open_broker(tmp_path)

    placed = await broker.place_order(order(TradeAction.BUY, 1000, 100, TimeInForce.ROD))

    assert placed.status == OrderStatus.REJECTED
    assert placed.reason is not None and placed.reason.startswith("UNSUPPORTED_TIME_IN_FORCE")
    assert await cash(broker) == 1_000_000
    await db.close()


@pytest.mark.parametrize(
    ("initial_cash", "action", "quantity", "reason"),
    [(100_000, TradeAction.BUY, 1000, "INSUFFICIENT_CASH"), (1_000_000, TradeAction.SELL, 1000, "POSITION_NOT_FOUND")],
)
async def test_business_refusals_are_rejected_before_acceptance(
    tmp_path, initial_cash: float, action: TradeAction, quantity: int, reason: str
) -> None:
    db, broker = await open_broker(tmp_path, initial_cash=initial_cash)

    placed = await broker.place_order(order(action, quantity, 100))

    assert placed.status == OrderStatus.REJECTED
    assert placed.reason is not None and placed.reason.startswith(reason)
    assert (await cash(broker), await holdings(broker)) == (initial_cash, [])
    await db.close()


async def test_selling_more_than_held_is_rejected(tmp_path) -> None:
    db, broker = await open_broker(tmp_path)
    await broker.place_order(order(TradeAction.BUY, 1000, 100))

    placed = await broker.place_order(order(TradeAction.SELL, 1001, 100))

    assert placed.status == OrderStatus.REJECTED
    assert placed.reason is not None and placed.reason.startswith("INSUFFICIENT_POSITION")
    await db.close()


async def test_a_technical_error_fails_the_order(tmp_path) -> None:
    db, broker = await open_broker(tmp_path, create_tables=False)

    placed = await broker.place_order(order(TradeAction.BUY, 1000, 100))

    assert placed.status == OrderStatus.FAILED
    assert placed.reason is not None and "OperationalError" in placed.reason
    await db.close()
