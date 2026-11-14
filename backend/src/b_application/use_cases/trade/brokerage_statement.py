from datetime import timedelta
from typing import Any

from a_domain.model.trading.account import BrokerageStatement
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IBrokerExecutionProvider
from b_application.config.app_config import AppConfig


class BrokerageStatementReader:
    """
    Use Case: Read the real broker's account as the broker reports it now, with its sales of the last
    holdings.realized_days days. None while the site has no real broker for this user (`brokerage` is None) or its
    login is down. It only reads: it holds no order step, sends no order and records no run.
    """

    def __init__(self, brokerage: IBrokerExecutionProvider[Any, Any] | None, market_clock: IMarketClock, config: AppConfig) -> None:
        self._brokerage = brokerage
        self._market_clock = market_clock
        self._realized_days = config.holdings.realized_days

    async def execute(self) -> BrokerageStatement | None:
        if self._brokerage is None or not self._brokerage.link().up:
            return None

        today = self._market_clock.today()

        return await self._brokerage.statement(today - timedelta(days=self._realized_days), today)
