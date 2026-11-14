from typing import Protocol

from a_domain.types.enums import ExecutionProvider, FeatureVisibility


class IOrderingSwitch(Protocol):
    """
    Whom the site lets order on each broker now: the visibility of each broker's ordering feature (features.*) in the
    settings files as they are on disk at the ask. That one durable place is the switch. Every process of the site
    reads it, the Web API and a CLI beside it, and an order asks it when it is prepared and again right before each
    exchange order it sends, so turning ordering off stops the orders of a run already under way, in any process, on
    whatever settings the run started.
    """

    async def visibility(self, broker: ExecutionProvider) -> FeatureVisibility:
        """
        Whom the site lets order on `broker` now. Nobody (OFF) while the settings do not set it, and while the files
        on disk are ones the app would not load: settings no start accepts let nobody order.
        """
        ...
