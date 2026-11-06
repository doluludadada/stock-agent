from a_domain.ports.market.daily_close_archive import IDailyCloseArchive
from b_application.config.app_config import AppConfig


class ArchiveWarmUp:
    """
    How far the open-data archive has come: the sessions of stock closes it holds, and the daily bars the built-in
    strategies need. An open-data deployment reads its daily history from the archive, so its runs find no candidate
    until the first number reaches the second.
    """

    def __init__(self, archive: IDailyCloseArchive, config: AppConfig) -> None:
        self._archive = archive
        self._required_bars = config.technical.required_bars

    async def execute(self) -> tuple[int, int]:
        return await self._archive.session_count(), self._required_bars
