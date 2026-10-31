import sys
from typing import override

from loguru import logger

from a_domain.ports.system.logging_provider import ILoggingProvider


class LoggerService(ILoggingProvider):
    """Loguru on stderr. depth=1 makes each record name the code that called the port method, not this adapter."""

    def __init__(self, level: str | int = "INFO") -> None:
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

    @override
    def info(self, message: str) -> None:
        logger.opt(depth=1).info(message)

    @override
    def warning(self, message: str) -> None:
        logger.opt(depth=1).warning(message)

    @override
    def debug(self, message: str) -> None:
        logger.opt(depth=1).debug(message)

    @override
    def critical(self, message: str) -> None:
        logger.opt(depth=1).critical(message)

    @override
    def error(self, message: str) -> None:
        logger.opt(depth=1).error(message)

    @override
    def exception(self, message: str) -> None:
        logger.opt(depth=1).exception(message)

    @override
    def success(self, message: str) -> None:
        logger.opt(depth=1).success(message)

    @override
    def trace(self, message: str) -> None:
        logger.opt(depth=1).trace(message)
