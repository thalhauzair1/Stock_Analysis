import logging
import sys
from pathlib import Path

_LOG_DIR = Path("logs")
_LOG_DIR.mkdir(exist_ok=True)

_FMT = logging.Formatter(
    "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(_FMT)
    logger.addHandler(ch)

    fh = logging.FileHandler(_LOG_DIR / "stock_intelligence.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_FMT)
    logger.addHandler(fh)

    return logger
