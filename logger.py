
import logging
import sys

from config import settings


def setup_logger() -> logging.Logger:
    """
    Настраивает и возвращает кастомный логгер.
    - Выводит логи в stdout.
    - Сохраняет логи в файл bot.log.
    - Устанавливает кастомный формат сообщений.
    """
    # Получаем корневой логгер
    log = logging.getLogger()
    log.setLevel(logging.INFO)

    # Определяем формат сообщений
    formatter = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(name)s - (%(filename)s).%(funcName)s(%(lineno)d) - %(message)s"
    )

    # Настраиваем вывод в консоль (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # Настраиваем вывод в файл
    # Файл будет создан в корневой директории проекта
    file_handler = logging.FileHandler(settings.BASE_DIR / "bot.log", mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)

    # Добавляем обработчики к логгеру, если их еще нет
    if not log.handlers:
        log.addHandler(console_handler)
        log.addHandler(file_handler)
        
    # Уменьшаем "шум" от сторонних библиотек
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)  # Включаем логи telegram для отладки
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    return log


# Создаем единственный экземпляр логгера
logger = setup_logger()

