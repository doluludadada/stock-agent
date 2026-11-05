from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from b_application.config.settings import AppSettings
from b_application.pipeline import Pipeline
from b_application.use_cases.order.load_order import LoadOrderUseCase
from b_application.use_cases.order.place_order import PlaceOrderUseCase
from c_infrastructure.database.order_repository import SqlOrderRepository
from c_infrastructure.system.loguru_logger import LoguruLogger


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()


def get_session() -> AsyncSession:
    return async_sessionmaker(create_async_engine(get_settings().database_url))()


def get_pipeline() -> Pipeline:
    repository = SqlOrderRepository(get_session())
    return Pipeline(LoadOrderUseCase(repository), PlaceOrderUseCase(repository, get_settings().shipping), LoguruLogger())
