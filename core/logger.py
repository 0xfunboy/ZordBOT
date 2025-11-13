import logging
import sys
from typing import Optional


def get_logger(name: str = "zrc20bot", level: int = logging.INFO, log_file: Optional[str] = None) -> logging.Logger:
    """Return a configured logger with structured formatting."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)

    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    logger.addHandler(stream_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger
