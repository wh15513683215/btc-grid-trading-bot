"""Centralized logging configuration using loguru."""

import sys
from pathlib import Path
from loguru import logger


def setup_logger(log_dir: str = "logs", level: str = "INFO") -> None:
    """Configure loguru with file rotation and console output."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger.remove()

    # Console handler
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # System log (all events)
    logger.add(
        log_path / "system.log",
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
    )

    # Trade log (only trading events — filter by extra field)
    logger.add(
        log_path / "trading.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        filter=lambda record: record["extra"].get("trade") is True,
    )


def get_trade_logger():
    """Return a logger bound with trade=True for trade-specific log file."""
    return logger.bind(trade=True)
