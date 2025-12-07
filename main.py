
import asyncio
import sys

from telegram import BotCommand
from telegram.ext import Application

from handlers import BotHandlers
from config import settings
from logger import logger


async def set_bot_commands(app: Application):
    """Устанавливает список команд, видимых в меню Telegram."""
    commands = [
        BotCommand("start", "🚀 Запустить бота и показать справку"),
        BotCommand("help", "ℹ️ Показать справку"),
        BotCommand("play", "🎵 Найти и скачать трек"),
        BotCommand("menu", "🎛️ Показать главное меню"),
        BotCommand("status", "📊 Показать статус бота"),
        BotCommand("admin", "👑 Открыть панель администратора"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("✅ Команды бота в меню обновлены.")


async def main() -> None:
    """Основная функция запуска бота."""
    logger.info("🚀 Запуск Music Bot v3.0...")

    if not settings.BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден в переменных окружения.")
        sys.exit(1)

    if not settings.ADMIN_IDS:
        logger.warning("⚠️ ADMIN_IDS не определен. Команды администратора будут недоступны.")

    logger.info(f"✅ Администраторы: {settings.ADMIN_IDS}")

    handlers_instance = None
    app = None
    
    try:
        app = Application.builder().token(settings.BOT_TOKEN).build()

        # Устанавливаем команды
        await set_bot_commands(app)

        handlers_instance = BotHandlers(app)
        await handlers_instance.register()

        logger.info("✅ Бот успешно инициализирован.")
        logger.info(f"🔑 Токен: ...{settings.BOT_TOKEN[-6:]}")

        # Проверяем статус бота
        bot_info = await app.bot.get_me()
        logger.info(f"✅ Бот активен: @{bot_info.username} ({bot_info.first_name})")
        
        # Инициализируем и запускаем приложение
        await app.initialize()
        await app.start()
        
        # Запускаем polling
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query", "my_chat_member"],
        )
        
        logger.info("✅ Бот запущен и готов к работе.")
        logger.info("✅ Polling активен, ожидаю обновления...")
        logger.info("Для остановки нажмите Ctrl+C")

        # Ждем бесконечно, пока не получим сигнал остановки
        await asyncio.Event().wait()

    except KeyboardInterrupt:
        logger.info("👋 Получен сигнал остановки (KeyboardInterrupt)...")
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка при запуске бота: {e}", exc_info=True)
    finally:
        # Graceful shutdown
        logger.info("🛑 Останавливаю бота...")
        try:
            if handlers_instance:
                await handlers_instance.cleanup()
            if app:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
        except Exception as e:
            logger.error(f"Ошибка при остановке бота: {e}")
        logger.info("👋 Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Бот остановлен.")
    except Exception as e:
        logger.critical(f"❌ Непредвиденная ошибка в главном цикле: {e}", exc_info=True)
        sys.exit(1)
