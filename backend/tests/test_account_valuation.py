from datetime import datetime

from a_domain.model.trading.account import Account, Mark, Position
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

QUOTED_AT = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)


def test_an_unpriced_position_counts_at_its_average_cost_with_no_pnl() -> None:
    position = Position(stock_id="2330", quantity=1000, average_cost=100.0)
    account = Account(cash=50_000, positions=[position])

    assert (position.mark_price, position.marked_at, position.market_value, position.unrealized_pnl) == (100.0, None, 100_000, 0.0)
    assert (account.market_value, account.equity, account.unrealized_pnl) == (100_000, 150_000, 0.0)


def test_a_marked_position_is_worth_its_mark_and_carries_its_pnl() -> None:
    position = Position(
        stock_id="2330", quantity=1000, average_cost=100.0, mark=Mark(price=110.0, at=QUOTED_AT, unrealized_pnl=9_200.0)
    )

    assert (position.mark_price, position.marked_at, position.market_value, position.unrealized_pnl) == (
        110.0,
        QUOTED_AT,
        110_000,
        9_200.0,
    )


def test_buying_or_selling_drops_the_mark_because_it_valued_the_old_quantity() -> None:
    bought = Position(stock_id="2330", quantity=1000, average_cost=100.0, mark=Mark(price=110.0, at=QUOTED_AT))
    sold = Position(stock_id="2330", quantity=1000, average_cost=100.0, mark=Mark(price=110.0, at=QUOTED_AT))

    bought.add(quantity=1000, price=120.0)
    sold.reduce(quantity=500)

    assert (bought.mark, bought.quantity, bought.average_cost) == (None, 2000, 110.0)
    assert (sold.mark, sold.quantity) == (None, 500)
