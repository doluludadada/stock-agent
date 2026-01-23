from src.a_domain.model.market.stock import Stock
from src.a_domain.ports.market.market_data_port import IMarketDataPort
from src.a_domain.ports.system.logging_port import ILoggingPort
from src.a_domain.types.enums import MarketType
from src.b_application.configuration.schemas import AppConfig


class MarketScanner:
    """
    Use Case: Retrieve stocks and apply initial market filter.

    Responsibility:
    - Get all stocks from market data source
    - Filter by market type or specific symbols
    - Return candidate list for analysis
    """

    def __init__(
        self,
        market_data: IMarketDataPort,
        config: AppConfig,
        logger: ILoggingPort,
    ):
        self._market_data = market_data
        self._config = config
        self._logger = logger

    async def execute(
        self,
        symbols: list[str] | None = None,
        markets: list[MarketType] | None = None,
    ) -> list[Stock]:
        """
        Scan market for candidate stocks.

        Args:
            symbols: Specific symbols to analyze. None = scan all.
            markets: Filter by market types. None = all supported markets.

        Returns:
            List of Stock entities to be analyzed.

        Raises:
            RuntimeError: If market data source is unavailable.
        """
        self._logger.info(f"Starting market scan. Symbols={symbols}, Markets={markets}")

        try:
            all_stocks = await self._market_data.get_all_stocks()
        except Exception as e:
            self._logger.error(f"Failed to fetch stocks from market data: {e}")
            raise RuntimeError("Market data source unavailable") from e

        if not all_stocks:
            self._logger.warning("No stocks returned from market data source")
            return []

        # Filter by specific symbols if provided
        if symbols:
            symbol_set = set(symbols)
            all_stocks = [s for s in all_stocks if s.stock_id in symbol_set]
            self._logger.debug(f"Filtered to {len(all_stocks)} stocks by symbol list")

        # Filter by market type
        if markets:
            market_set = set(markets)
            all_stocks = [s for s in all_stocks if s.market in market_set]
            self._logger.debug(f"Filtered to {len(all_stocks)} stocks by market type")

        self._logger.success(f"Market scan complete. Found {len(all_stocks)} candidates")
        return all_stocks
