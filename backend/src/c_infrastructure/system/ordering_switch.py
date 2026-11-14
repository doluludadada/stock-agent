from collections.abc import Mapping
from typing import override

from a_domain.ports.system.ordering_switch import IOrderingSwitch
from a_domain.types.enums import ExecutionProvider, FeatureVisibility


class MemoryOrderingSwitch(IOrderingSwitch):
    """The switch in this process's memory: what the current runtime's settings said when it became current."""

    def __init__(self) -> None:
        self._ordering: Mapping[ExecutionProvider, FeatureVisibility] = {}

    @override
    def visibility(self, broker: ExecutionProvider) -> FeatureVisibility:
        return self._ordering.get(broker, FeatureVisibility.OFF)

    @override
    def publish(self, ordering: Mapping[ExecutionProvider, FeatureVisibility]) -> None:
        self._ordering = dict(ordering)
