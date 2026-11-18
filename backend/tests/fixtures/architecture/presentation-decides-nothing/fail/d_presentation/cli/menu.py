from a_domain import rules
from b_application.config.app_config import AppConfig


def print_menu(config: AppConfig) -> None:
    print(config.trading.max_order_value)
    print(config.analysis.min_combined_score_buy)
    trading = config.trading
    print(trading, rules)
