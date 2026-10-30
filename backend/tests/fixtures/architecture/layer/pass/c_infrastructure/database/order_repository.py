from sqlalchemy.ext.asyncio import AsyncSession

from a_domain.model.order import Order
from b_application.config.settings import AppSettings


class SqlOrderRepository:
    def __init__(self, session: AsyncSession, settings: AppSettings) -> None:
        self._session = session
        self._settings = settings
