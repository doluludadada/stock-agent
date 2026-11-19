from a_domain.model.market.quote import Listing


def listing_of(stock_id: str) -> Listing:
    return Listing(stock_id=stock_id, board="TWSE")
