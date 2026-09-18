import logging
import os
from logging.handlers import RotatingFileHandler
import sys

def setup_logging(log_dir=None):
    """Configures the logger to write to a file and the console with rotation."""
    # If a specific log directory isn't provided, determine it automatically.
    # This allows the service to provide a reliable path.
    if log_dir is None:
        try:
            base_dir = os.path.dirname(os.path.abspath(sys.modules['__main__'].__file__))
        except:
            base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        log_dir = os.path.join(base_dir, "logs")

    # Ensure the directory exists
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "slave.log")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5_242_880, backupCount=5, encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger