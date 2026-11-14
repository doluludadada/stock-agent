from typing import Protocol


class IUsersStocks(Protocol):
    """
    The stocks the site's users care about, as stock ids alone: the answer names no user, no quantity and no price, so
    the site can keep those stocks' articles current without any user's data leaving that user's rows.
    """

    async def held_or_watched(self) -> set[str]:
        """
        Every stock some user holds, in the mock account or among the holdings entered by hand, or has on a watchlist
        that has not expired.
        """
        ...
