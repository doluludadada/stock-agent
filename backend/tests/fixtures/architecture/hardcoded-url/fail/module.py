BASE_URL = "https://www.twse.com.tw/exchangeReport"


def quote_url(host: str, stock_id: str) -> str:
    return f"http://{host}/quote/{stock_id}"


FEED = (
    "HTTPS://news.example.com/"
    "rss"
)
