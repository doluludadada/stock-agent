import sys

from loguru import logger

from a_domain.ports.system.logging_provider import ILoggingProvider


class LoggerService(ILoggingProvider):
    def __init__(self, level: str | int = "INFO"):
        logger.remove()
        logger.add(
            sys.stderr,
            level=level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ),
        )
        self._logger = logger

    def info(self, message: str) -> None:
        logger.opt(depth=1).info(message)

    def warning(self, message: str) -> None:
        logger.opt(depth=1).warning(message)

    def debug(self, message: str) -> None:
        logger.opt(depth=1).debug(message)

    def critical(self, message: str) -> None:
        logger.opt(depth=1).critical(message)

    def error(self, message: str) -> None:
        logger.opt(depth=1).error(message)

    def exception(self, message: str) -> None:
        logger.opt(depth=1).exception(message)

    def success(self, message: str) -> None:
        logger.opt(depth=1).success(message)

    def trace(self, message: str) -> None:
        logger.opt(depth=1).trace(message)
