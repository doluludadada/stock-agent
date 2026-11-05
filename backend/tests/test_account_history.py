from datetime import date, timedelta

import pytest
from trading_stack import MONDAY_10_00, analysed_stock, bar, open_stack

pytestmark = pytest.mark.asyncio

MONDAY_CLOSE = MONDAY_10_00.replace(hour=13, minute=30)
TUESDAY_CLOSE = MONDAY_CLOSE + timedelta(days=1)


async def bought_2000_on_monday(tmp_path):
    stack = await open_stack(tmp_path)
    await stack.pipeline.buy_manually(analysed_stock())

    stack.clock.current = MONDAY_10_00 + timedelta(days=1, hours=1)
    stack.quotes.daily["2330"] = [bar(MONDAY_CLOSE, 100), bar(TUESDAY_CLOSE, 110)]
    stack.quotes.realtime["2330"] = bar(stack.clock.current - timedelta(minutes=1), 112)
    return stack


async def test_current_positions_are_marked_at_the_latest_quote_net_of_exit_costs(tmp_path) -> None:
    stack = await bought_2000_on_monday(tmp_path)

    status = await stack.pipeline.load_account_history(as_of=None)

    [held] = status.account.positions
    assert (held.quantity, held.mark_price, held.market_value) == (2000, 112, 224_000)
    assert held.unrealized_pnl == pytest.approx(224_000 - 319 - 672 - 200_285)
    assert status.account.equity == pytest.approx(1_000_000 - 200_285 + 224_000)
    assert status.live_stock_ids == {"2330"}


async def test_the_equity_curve_marks_each_trading_day_at_its_close(tmp_path) -> None:
    stack = await bought_2000_on_monday(tmp_path)

    status = await stack.pipeline.load_account_history(as_of=None)

    assert [(day, account.cash, account.equity) for day, account in status.equity_curve.items()] == [
        (date(2026, 10, 19), 799_715, 999_715),
        (date(2026, 10, 20), 799_715, 1_019_715),
    ]


@pytest.mark.parametrize(
    ("day", "market_value"), [(date(2026, 10, 19), 200_000), (date(2026, 10, 20), 220_000), (date(2026, 10, 18), None)]
)
async def test_the_account_as_of_a_day_is_its_last_fill_marked_at_that_days_close(
    tmp_path, day: date, market_value: float | None
) -> None:
    stack = await bought_2000_on_monday(tmp_path)

    status = await stack.pipeline.load_account_history(as_of=day)

    if market_value is None:
        assert status.account_as_of is None
        return

    assert status.account_as_of is not None
    account = status.account_as_of.account
    assert (account.cash, account.market_value) == (799_715, market_value)
