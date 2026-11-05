"""Seeded random daily histories, the same on every run, for comparing technical strategies over many shapes of market."""

import random
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock


def random_stocks(count: int, seed: int) -> Iterator[Stock]:
    """
    Each stock has 61 to 140 completed daily bars from a random walk with its own drift and volatility, a volume of
    a few hundred, a few thousand or millions of shares, and half the stocks a realtime quote within 5% of the close.
    """
    generator = random.Random(seed)
    start = datetime(2026, 1, 1, 13, 30, tzinfo=UTC)

    for index in range(count):
        size = generator.randint(61, 140)
        price = generator.uniform(8, 300)
        drift = generator.uniform(-0.004, 0.006)
        bars = []

        for day in range(size):
            price = max(0.5, price * (1 + generator.gauss(drift, generator.choice((0.008, 0.02, 0.04)))))
            spread = price * generator.uniform(0.002, 0.08)
            low = price - spread * generator.random()
            high = low + spread
            volume = generator.choice(
                (generator.randint(100, 1500), generator.randint(1000, 50_000), generator.randint(100_000, 9_000_000))
            )
            opening = round(generator.uniform(low, high), 2)
            bars.append(
                Ohlcv(
                    ts=start + timedelta(days=day),
                    open=opening,
                    high=round(high, 2),
                    low=round(low, 2),
                    close=round(price, 2),
                    volume=volume,
                )
            )

        stock = Stock(stock_id=f"S{index}")
        stock.load_history(bars)

        if generator.random() < 0.5:
            close = round(price * generator.uniform(0.95, 1.05), 2)
            stock.realtime_bar = Ohlcv(ts=start + timedelta(days=size), open=price, high=price, low=price, close=close, volume=1000)

        yield stock
