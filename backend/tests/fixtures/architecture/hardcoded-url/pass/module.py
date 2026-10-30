"""Fetch quotes; the exchange documents its API at https://www.twse.com.tw."""

SCHEME = "https"


def quote_url(base_url: str, stock_id: str) -> str:
    # The base URL, such as https://www.twse.com.tw, comes from settings.
    return f"{base_url}/quote/{stock_id}"
