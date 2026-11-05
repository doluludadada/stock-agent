from a_domain.types.enums import OrderMode
from b_application.config.settings import AppSettings


def print_trading_setup(config: AppSettings) -> None:
    print(config.environment.value, config.trading.execution_provider.value, config.mock_trading.account_id)
    print("REAL MONEY" if config.trading.order_mode == OrderMode.LIVE and not config.shioaji.simulation else "no real order")


def print_built_in_strategies(config: AppSettings) -> None:
    for strategy in config.technical.built_in_strategies:
        print(strategy.strategy_id)
