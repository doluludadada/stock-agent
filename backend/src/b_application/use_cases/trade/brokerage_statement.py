from datetime import timedelta
from typing import Any

from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IBrokerExecutionProvider
from a_domain.ports.trading.users_orders import IUsersOrders
from a_domain.rules.system.settings_change import ServerSwitchRule
from a_domain.types.enums import ExecutionProvider, FeatureVisibility
from b_application.config.app_config import AppConfig
from b_application.schemas.trade import BrokerageAccount


class BrokerageStatementReader:
    """
    Use Case: Read the SinoPac page: the real broker's account as the broker reports it now, with its sales of the last
    holdings.realized_days days, and why the site's login could not switch to the other server by the switch the page
    offers (ServerSwitchRule), SinoPac orders of any user that await settlement included (`users_orders`). The account
    is None while the site has
    no real broker for this user (`brokerage` is None) or its login is down; the refusal is None while the switch is
    open. It only reads: it holds no order step, sends no order and records no run.
    """

    def __init__(
        self,
        brokerage: IBrokerExecutionProvider[Any] | None,
        users_orders: IUsersOrders,
        market_clock: IMarketClock,
        config: AppConfig,
    ) -> None:
        self._brokerage = brokerage
        self._users_orders = users_orders
        self._market_clock = market_clock
        self._realized_days = config.holdings.realized_days
        self._server = config.shioaji.server
        self._given = config.shioaji.given()
        self._registration_open = config.accounts.registration_open
        self._switch_rule = ServerSwitchRule(servers=config.environment.shioaji_servers)

    async def execute(self) -> BrokerageAccount:
        unsettled = await self._users_orders.awaiting_settlement(ExecutionProvider.SHIOAJI)
        refusal = self._switch_rule.apply(
            self._server, self._server.other, FeatureVisibility.OFF, self._given, self._registration_open, unsettled
        )

        if self._brokerage is None or not self._brokerage.link().up:
            return BrokerageAccount(None, refusal)

        today = self._market_clock.today()

        return BrokerageAccount(await self._brokerage.statement(today - timedelta(days=self._realized_days), today), refusal)
