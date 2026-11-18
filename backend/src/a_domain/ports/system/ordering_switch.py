from typing import Protocol

from a_domain.rules.trading.order_rule import SiteOrdering


class IOrderingSwitch(Protocol):
    """
    Whom the site lets order on each broker now, and on which SinoPac server: the visibility of each broker's ordering
    feature (features.*) and shioaji.server in the settings files as they are on disk at the ask. That one durable
    place is the switch. Every process of the site reads it, the Web API and a CLI beside it, and an order asks it when
    it is prepared and again right before each exchange order it sends, so turning ordering off stops the orders of a
    run already under way, in any process, on whatever settings the run started (RealBrokerGateRule).
    """

    async def read(self) -> SiteOrdering | None:
        """
        What the site says now, from one read of the files: whom it lets order on each broker, OFF where the settings
        do not set it, and the server shioaji.server names. None while the files on disk are ones the app would not
        load: settings no start accepts let nobody order.
        """
        ...
