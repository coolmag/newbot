import asyncio
import logging

from telegram import BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from handlers import (
    AdminCallbackHandler,
    AdminPanelHandler,
    MenuHandler,
    MenuCallbackHandler,
    PlayHandler,
    StartHandler,
    TrackCallbackHandler,
    ArtistCommandHandler,
    VoteCallbackHandler,
)
from config import get_settings
from constants import VoteCallback
from container import create_container
from log_config import setup_logging
from radio import RadioService
from cache_service import CacheService

logger = logging.getLogger(__name__)


async def set_bot_commands(app: Application):
    """Устанавливает список команд, видимых в меню Telegram."""
    commands = [
        BotCommand("start", "🚀 Показать главное меню"),
        BotCommand("help", "ℹ️ Показать справку (аналог /start)"),
        BotCommand("play", "🎵 Найти и скачать трек"),
        BotCommand("menu", "🎛️ Показать главное меню"),
        BotCommand("artist", "🎤 Включить радио по артисту (только для админов)"),
        BotCommand("admin", "👑 Открыть панель администратора"),
    ]
    await app.bot.set_my_commands(commands)


async def main() -> None:
    """Основная функция запуска бота."""
    settings = get_settings()
    setup_logging(settings)

    if settings.COOKIES_CONTENT:
        try:
            settings.COOKIES_FILE.write_text(settings.COOKIES_CONTENT)
            logger.info("✅ Файл cookies.txt успешно создан из переменной окружения.")
        except Exception as e:
            logger.error(f"❌ Не удалось создать cookies.txt: {e}")

    logger.info("🚀 Запуск Music Bot v4.1...")

    async with Application.builder().token(settings.BOT_TOKEN).build() as app:
        container = create_container(app.bot)

        # --- Регистрация обработчиков ---
        app.add_handler(CommandHandler(["start", "help", "menu"], container.resolve(StartHandler).handle))
        
        app.add_handler(CommandHandler("play", container.resolve(PlayHandler).handle))
        app.add_handler(MessageHandler(filters.REPLY, container.resolve(PlayHandler).handle))

        app.add_handler(CommandHandler("artist", container.resolve(ArtistCommandHandler).handle))
        app.add_handler(CommandHandler("admin", container.resolve(AdminPanelHandler).handle))

        app.add_handler(CallbackQueryHandler(container.resolve(AdminCallbackHandler).handle, pattern="^admin:.*"))
        app.add_handler(CallbackQueryHandler(container.resolve(MenuCallbackHandler).handle, pattern="^menu:.*"))
        app.add_handler(CallbackQueryHandler(container.resolve(TrackCallbackHandler).handle, pattern="^track:.*"))
        app.add_handler(CallbackQueryHandler(container.resolve(VoteCallbackHandler).handle, pattern=f"^{VoteCallback.PREFIX}.*"))

        await set_bot_commands(app)
        
        # --- Запуск ---
        try:
            cache_service = container.resolve(CacheService)
            await cache_service.initialize()

            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            logger.info("✅ Бот запущен и готов к работе.")
            await asyncio.Event().wait()

        except (KeyboardInterrupt, SystemExit):
            logger.info("👋 Получен сигнал остановки...")
        except Exception as e:
            logger.critical(f"❌ Критическая ошибка при запуске бота: {e}", exc_info=True)
        finally:
            logger.info("🛑 Останавливаю сервисы...")
            radio_service = container.resolve(RadioService)
            if radio_service.is_on:
                await radio_service.stop()
            
            cache_service = container.resolve(CacheService)
            await cache_service.close()
            
            logger.info("👋 Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"❌ Непредвиденная ошибка в __main__: {e}", exc_info=True)
