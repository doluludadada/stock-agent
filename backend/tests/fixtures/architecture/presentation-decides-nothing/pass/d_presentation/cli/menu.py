from b_application.config.app_config import AppConfig


def print_trading_setup(config: AppConfig) -> None:
    print(config.environment.value, config.shioaji.server.label)
    print("no real money" if config.shioaji.server.simulation else "REAL MONEY", config.trading.max_order_value)


def print_built_in_strategies(config: AppConfig) -> None:
    for strategy in config.technical.built_in_strategies:
        print(strategy.strategy_id)
