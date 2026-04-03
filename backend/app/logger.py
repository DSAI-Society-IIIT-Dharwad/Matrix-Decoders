import logging
import sys


class ColorFormatter(logging.Formatter):
    """Color-coded log formatter for console output."""

    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"

    LABELS = {
        logging.DEBUG: "[DEBUG]",
        logging.INFO: "[INFO]",
        logging.WARNING: "[WARN]",
        logging.ERROR: "[ERROR]",
        logging.CRITICAL: "[CRITICAL]",
    }

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        label = self.LABELS.get(record.levelno, "")
        record_copy = logging.makeLogRecord(record.__dict__.copy())
        record_copy.msg = f"{color}{label} {record.getMessage()}{self.RESET}"
        record_copy.args = ()
        return super().format(record_copy)


def get_logger(name: str) -> logging.Logger:
    """Create a structured, color-coded logger."""
    logger = logging.getLogger(f"nudiscribe.{name}")

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            ColorFormatter("%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

    return logger
