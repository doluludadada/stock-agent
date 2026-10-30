"""Valuation helpers priced in US-dollars."""


def margin(price: float) -> float:
    # Step 1 of 2: read the margin
    label = "US-108"
    return price * 0.1 if label else price  # 1. apply the margin
