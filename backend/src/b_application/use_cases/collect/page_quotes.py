from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.price_provider import IQuoteBoard
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.market.quote_refresh import QuoteRefresh
from a_domain.types.enums import MarketIndex
from b_application.config.app_config import AppConfig


class PageQuotes:
    """
    The realtime quotes a page shows beside its settled closes, of stocks and of market indexes, read from the board
    every page and user share. It reads quotes and nothing else: it prices no order and holds no account.

    While the quotes may still change (QuoteRefreshRule) the board follows what is asked for, which asks its source at
    the board's own pace; otherwise the board is only read. Whether they may still change is read from the board's
    last answer of what is asked for alone. It returns today's quote of each stock that traded today and of each index
    with a value of today, and when a page asks again.
    """

    def __init__(self, quote_board: IQuoteBoard, market_clock: IMarketClock, config: AppConfig) -> None:
        self._quote_board = quote_board
        self._market_clock = market_clock
        self._refresh_rule = config.market_data.quote_refresh_rule()

    async def execute(
        self, stock_ids: list[str], indexes: list[MarketIndex]
    ) -> tuple[dict[str, Ohlcv], dict[MarketIndex, Ohlcv], QuoteRefresh]:
        today = self._market_clock.today()
        refresh = self._refresh_rule.apply(
            self._market_clock.trading_phase(),
            today,
            self._market_clock.last_closed_session(),
            self._market_clock.session_close(today),
            self._quote_board.read_at(stock_ids, indexes),
        )

        if refresh.changing:
            await self._quote_board.follow(stock_ids, indexes)

        return self._quote_board.quotes(stock_ids, today), self._quote_board.index_quotes(indexes, today), refresh
