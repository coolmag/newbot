import asyncio
import logging

from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from handlers import (
    AdminCallbackHandler,
    AdminPanelHandler,
    MenuHandler,
    MenuCallbackHandler,
    PlayHandler,
    StartHandler,
    TrackCallbackHandler,
    GenreCallbackHandler,
    ArtistCommandHandler,
    VoteCallbackHandler,
    DedicateHandler,
    MoodCallbackHandler,
    PlaylistHandler,
)
from config import Settings, get_settings
from constants import VoteCallback, GenreCallback, MoodCallback
from container import create_container
from log_config import setup_logging
from radio import RadioService
from cache_service import CacheService

logger = logging.getLogger(__name__)


async def set_bot_commands(app: Application, settings: Settings):
    """Устанавливает разные списки команд для обычных пользователей и админов."""
    
    # Команды для обычных пользователей
    default_commands = [
        BotCommand("start", "🚀 Показать главное меню"),
        BotCommand("help", "ℹ️ Показать справку"),
        BotCommand("play", "🎵 Найти и скачать трек"),
        BotCommand("p", "🎵 Найти и скачать трек"),
        BotCommand("playlist", "⭐ Показать избранное"),
        BotCommand("pl", "⭐ Показать избранное"),
        BotCommand("menu", "🎛️ Показать главное меню"),
        BotCommand("m", "🎛️ Показать главное меню"),
        BotCommand("dedicate", "🎧 Посвятить трек пользователю"),
        BotCommand("d", "🎧 Посвятить трек пользователю"),
    ]
    
    # Устанавливаем команды по умолчанию для всех
    await app.bot.set_my_commands(default_commands, scope=BotCommandScopeDefault())

    # Команды для админов (включают команды по умолчанию)
    admin_commands = default_commands + [
        BotCommand("artist", "🎤 Включить радио по артисту"),
        BotCommand("art", "🎤 Включить радио по артисту"),
        BotCommand("admin", "👑 Открыть панель администратора"),
        BotCommand("a", "👑 Открыть панель администратора"),
    ]
    
    # Устанавливаем расширенные команды для каждого админа персонально
    if settings.ADMIN_ID_LIST:
        for admin_id in settings.ADMIN_ID_LIST:
            try:
                await app.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
                logger.info(f"✅ Установлены админ-команды для пользователя {admin_id}")
            except Exception as e:
                logger.error(f"❌ Не удалось установить команды для админа {admin_id}: {e}")

def main() -> None:
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

    app = Application.builder().token(settings.BOT_TOKEN).build()
    container = create_container(app.bot)

    # --- Регистрация обработчиков ---
    app.add_handler(CommandHandler(["start", "help", "menu", "m"], container.resolve(StartHandler).handle))
    app.add_handler(CommandHandler(["play", "p"], container.resolve(PlayHandler).handle))
    app.add_handler(CommandHandler(["dedicate", "d"], container.resolve(DedicateHandler).handle))
    app.add_handler(CommandHandler(["artist", "art"], container.resolve(ArtistCommandHandler).handle))
    app.add_handler(CommandHandler(["admin", "a"], container.resolve(AdminPanelHandler).handle))
    app.add_handler(CommandHandler(["playlist", "pl"], container.resolve(PlaylistHandler).handle))
    app.add_handler(CallbackQueryHandler(container.resolve(AdminCallbackHandler).handle, pattern="^admin:.*"))
    app.add_handler(CallbackQueryHandler(container.resolve(MenuCallbackHandler).handle, pattern="^menu:.*"))
    app.add_handler(CallbackQueryHandler(container.resolve(TrackCallbackHandler).handle, pattern="^track:.*"))
    app.add_handler(CallbackQueryHandler(container.resolve(VoteCallbackHandler).handle, pattern=f"^{VoteCallback.PREFIX}.*"))
    app.add_handler(CallbackQueryHandler(container.resolve(GenreCallbackHandler).handle, pattern=f"^{GenreCallback.PREFIX}.*"))
    app.add_handler(CallbackQueryHandler(container.resolve(MoodCallbackHandler).handle, pattern=f"^{MoodCallback.PREFIX}.*"))

    async def post_init(application: Application) -> None:
        await set_bot_commands(application, settings)
        cache_service = container.resolve(CacheService)
        await cache_service.initialize()
    
    app.post_init = post_init
    
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()