from collections.abc import Mapping
from typing import Protocol

from a_domain.types.enums import ExecutionProvider, FeatureVisibility


class IOrderingSwitch(Protocol):
    """
    Whom the site lets order on each broker now: the visibility of each broker's ordering feature (features.*) in the
    settings the process serves new work on. A run keeps the settings it started on, and its orders ask here at each
    send, so turning ordering off stops the orders of a run already under way. Kept by this process only.
    """

    def visibility(self, broker: ExecutionProvider) -> FeatureVisibility:
        """Whom the site lets order on `broker` now. Nobody (OFF) until a runtime's settings were published."""
        ...

    def publish(self, ordering: Mapping[ExecutionProvider, FeatureVisibility]) -> None:
        """The settings that serve new work from now on let these viewers order on each broker."""
        ...
