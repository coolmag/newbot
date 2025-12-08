import logging
import logging.config
import sys

from config import Settings


def setup_logging(settings: Settings):
    """
    Настраивает логирование для приложения.
    """
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - [%(levelname)s] - %(name)s - "
                "(%(filename)s).%(funcName)s(%(lineno)d) - %(message)s",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
            },
            "file": {
                "formatter": "default",
                "class": "logging.handlers.RotatingFileHandler",
                "filename": settings.LOG_FILE_PATH,
                "maxBytes": 10 * 1024 * 1024,  # 10 MB
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "": {  # root logger
                "handlers": ["default", "file"],
                "level": settings.LOG_LEVEL.upper(),
                "propagate": True,
            },
            "httpx": {"handlers": ["default", "file"], "level": "WARNING"},
            "telegram": {"handlers": ["default", "file"], "level": "INFO"},
            "aiosqlite": {"handlers": ["default", "file"], "level": "WARNING"},
        },
    }

    logging.config.dictConfig(logging_config)
