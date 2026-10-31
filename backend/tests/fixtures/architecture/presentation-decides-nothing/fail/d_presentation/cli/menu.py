from a_domain import rules
from b_application.config.settings import AppSettings


def print_menu(config: AppSettings) -> None:
    print(config.trading.order_mode.value)
    print(config.analysis.min_combined_score_buy)
    trading = config.trading
    print(trading, rules)
