import asyncio
from pathlib import Path
from typing import override

from a_domain.ports.system.ordering_switch import IOrderingSwitch
from a_domain.types.enums import ExecutionProvider, FeatureVisibility
from b_application.config.settings_loader import load_settings


class SettingsFileOrderingSwitch(IOrderingSwitch):
    """
    The switch as the settings files of `project_root` hold it at each ask, loaded as a start loads them. It keeps
    nothing between asks, so a save, an edit on disk and another process's change all count at the next one.
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    @override
    async def visibility(self, broker: ExecutionProvider) -> FeatureVisibility:
        try:
            config = await asyncio.to_thread(load_settings, self._project_root)
        except Exception:
            return FeatureVisibility.OFF

        return config.features.ordering()[broker]
