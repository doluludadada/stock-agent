from a_domain.model.chat.web_search_result import WebSearchResult
from a_domain.model.trading.order import ExchangeOrder


def exchange_order_of(stock_id: str, dealt_shares: int) -> ExchangeOrder:
    return ExchangeOrder(stock_id=stock_id, dealt_shares=dealt_shares)


def result_of(title: str, url: str) -> WebSearchResult:
    return WebSearchResult(title=title, url=url)
