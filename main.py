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
)
from config import get_settings
from constants import AdminCallback
from container import create_container
# ... (rest of the file is the same)
    app.add_handler(
        CallbackQueryHandler(
            container.resolve(MenuCallbackHandler).handle, pattern="^menu:.*"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            container.resolve(TrackCallbackHandler).handle, pattern="^track:.*"
        )
    )

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
