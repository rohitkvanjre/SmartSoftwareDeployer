import io
import logging
import os
import sys
from logging.handlers import RotatingFileHandler # <-- 1. Add this import
from . import config

# Reuse config.MASTER_DIR (the one writable data root, frozen-exe aware) so
# logs land in the same place as data/config.json, cert.pem, etc. instead of
# a location that may not exist or be writable.
LOG_DIR = os.path.join(config.MASTER_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "master.log")


def _make_console_stream():
    """Return a stream for the console log handler that is safe for
    non-ASCII text (e.g. the emoji used throughout the GUI log messages).

    On Windows, the default console stream encoding is often a legacy
    codepage (e.g. cp1252), not UTF-8. Writing emoji through the default
    logging.StreamHandler() in that case raises UnicodeEncodeError inside
    StreamHandler.emit(); logging swallows that error and prints a
    '--- Logging error ---' traceback instead of the actual message.

    We wrap the underlying binary buffer with a UTF-8 TextIOWrapper that
    substitutes any character the console can't render, so log output is
    never lost. If stderr isn't available or doesn't expose a buffer
    (e.g. a frozen GUI build with no console), fall back to it as-is.
    """
    stream = sys.stderr
    try:
        if stream is not None and hasattr(stream, 'buffer'):
            return io.TextIOWrapper(
                stream.buffer,
                encoding='utf-8',
                errors='backslashreplace',
                line_buffering=True,
            )
    except Exception:
        pass
    return stream


def setup_logging():
    """Configures the logger to write to master.log and the console with rotation."""
    os.makedirs(LOG_DIR, exist_ok=True)
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    # --- 2. Use the RotatingFileHandler ---
    # This will create log files up to 5MB in size and keep 5 old copies.
    # Total log size will be capped at ~30MB (1 current + 5 backups).
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5_242_880, backupCount=5, encoding='utf-8'
    )
    # --- End of Change ---
    
    file_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(module)s.%(funcName)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # A windowed (console=False) frozen build has no real console: sys.stderr
    # is None, which would make every console-handler emit() silently fail.
    # Only attach the console handler when a real stream is available.
    console_stream = _make_console_stream()
    if console_stream is not None:
        console_handler = logging.StreamHandler(console_stream)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    logging.info("Master logger initialized with log rotation.")
    return logger