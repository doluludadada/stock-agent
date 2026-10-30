from b_application.config.settings import AppSettings
from c_infrastructure.database.order_repository import SqlOrderRepository


def get_settings() -> AppSettings:
    return AppSettings()
