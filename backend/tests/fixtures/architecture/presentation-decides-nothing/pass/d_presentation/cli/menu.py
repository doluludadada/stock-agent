from b_application.config.settings import AppSettings


def print_trading_setup(config: AppSettings) -> None:
    print(config.environment.value, config.environment.shioaji_simulation)
    print("REAL MONEY" if not config.environment.shioaji_simulation else "no real money", config.trading.max_order_value)


def print_built_in_strategies(config: AppSettings) -> None:
    for strategy in config.technical.built_in_strategies:
        print(strategy.strategy_id)
