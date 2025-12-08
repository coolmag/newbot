import asyncio
import logging

from telegram import BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from handlers import (
    AdminCallbackHandler,
    AdminPanelHandler,
    MenuHandler,
    MenuCallbackHandler,
    PlayHandler,
    StartHandler,
    TrackCallbackHandler,
    GenreCallbackHandler,
)
from config import get_settings
from constants import AdminCallback, GenreCallback
from container import create_container
from log_config import setup_logging
from cache_service import CacheService
from radio import RadioService

logger = logging.getLogger(__name__)


async def set_bot_commands(app: Application):
    """Устанавливает список команд, видимых в меню Telegram."""
    commands = [
        BotCommand("start", "🚀 Запустить бота и показать справку"),
        BotCommand("help", "ℹ️ Показать справку"),
        BotCommand("play", "🎵 Найти и скачать трек"),
        BotCommand("menu", "🎛️ Показать главное меню"),
        BotCommand("admin", "👑 Открыть панель администратора"),
    ]
    await app.bot.set_my_commands(commands)


async def main() -> None:
    """Основная функция запуска бота."""
    settings = get_settings()
    setup_logging(settings)

    # Создаем cookies.txt из переменной окружения
    if settings.COOKIES_CONTENT:
        try:
            settings.COOKIES_FILE.write_text(settings.COOKIES_CONTENT)
            logger.info("✅ Файл cookies.txt успешно создан из переменной окружения.")
        except Exception as e:
            logger.error(f"❌ Не удалось создать cookies.txt: {e}")

    logger.info("🚀 Запуск Music Bot v4.0...")

    app = Application.builder().token(settings.BOT_TOKEN).build()
    container = create_container(app.bot)

    # --- Регистрация обработчиков ---
    app.add_handler(CommandHandler(["start", "help"], container.resolve(StartHandler).handle))
    app.add_handler(CommandHandler("play", container.resolve(PlayHandler).handle))
    app.add_handler(CommandHandler("menu", container.resolve(MenuHandler).handle))
    app.add_handler(CommandHandler("admin", container.resolve(AdminPanelHandler).handle))
    app.add_handler(CallbackQueryHandler(container.resolve(AdminCallbackHandler).handle, pattern="^admin:.*"))
    app.add_handler(CallbackQueryHandler(container.resolve(MenuCallbackHandler).handle, pattern="^menu:.*"))
    app.add_handler(CallbackQueryHandler(container.resolve(TrackCallbackHandler).handle, pattern="^track:.*"))
    app.add_handler(CallbackQueryHandler(container.resolve(GenreCallbackHandler).handle, pattern=f"^{GenreCallback.PREFIX}.*"))

    await set_bot_commands(app)

    # --- Инициализация сервисов ---
    cache_service = container.resolve(CacheService)
    await cache_service.initialize()

    # --- Запуск приложения ---
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        logger.info("✅ Бот запущен и готов к работе.")
        await asyncio.Event().wait()

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        # --- Корректное завершение ---
        logger.info("🛑 Останавливаю бота...")
        if app.updater and app.updater.is_running():
            await app.updater.stop()
        if app.running:
            await app.stop()
        if not app.shutdown_called:
            await app.shutdown()
        
        radio_service = container.resolve(RadioService)
        await radio_service.stop()
        
        cache_service = container.resolve(CacheService)
        await cache_service.close()
        
        logger.info("👋 Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"❌ Непредвиденная ошибка: {e}", exc_info=True)