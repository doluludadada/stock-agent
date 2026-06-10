from icontract import ensure

from a_domain.types.enums import WatchlistType


class WatchlistRule:
    """Owns domain decisions for combining watchlist classifications."""

    # TODO: Kinda weird logic 
    @ensure(lambda result: isinstance(result, WatchlistType))
    def merge(
        self,
        current: WatchlistType,
        incoming: WatchlistType,
    ) -> WatchlistType:
        if current == incoming:
            return current

        types = {current, incoming}

        if WatchlistType.MANUAL in types:
            return WatchlistType.MANUAL

        if WatchlistType.TECHNICAL_AND_BUZZ in types:
            return WatchlistType.TECHNICAL_AND_BUZZ

        if types == {
            WatchlistType.TECHNICAL,
            WatchlistType.BUZZ,
        }:
            return WatchlistType.TECHNICAL_AND_BUZZ

        raise ValueError(f"Unsupported watchlist type merge: {current} + {incoming}")
