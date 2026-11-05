from typing import override

from loguru import logger

from a_domain.ports.system import ILoggingProvider


class LoguruLogger(ILoggingProvider):
    @override
    def info(self, message: str) -> None:
        logger.info(message)
