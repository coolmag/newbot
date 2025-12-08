import punq
from telegram import Bot

from handlers import (
    AdminCallbackHandler,
    AdminPanelHandler,
    MenuHandler,
    PlayHandler,
    StartHandler,
)
from config import Settings, get_settings
from cache_service import CacheService
from downloaders import (
    BaseDownloader,
    InternetArchiveDownloader,
    YouTubeDownloader,
)
from radio import RadioService


def create_container(bot: Bot) -> punq.Container:
    """
    Создает и настраивает DI-контейнер.
    """
    container = punq.Container()

    # --- Core ---
    settings = get_settings()
    container.register(Settings, instance=settings)
    container.register(Bot, instance=bot)

    # --- Services ---
    container.register(CacheService, scope=punq.Scope.singleton)
    container.register(YouTubeDownloader, scope=punq.Scope.singleton)
    container.register(InternetArchiveDownloader, scope=punq.Scope.singleton)
    container.register(RadioService, scope=punq.Scope.singleton)

    # --- Handlers ---
    container.register(StartHandler)
    container.register(PlayHandler)
    container.register(MenuHandler)
    container.register(AdminPanelHandler)
    container.register(AdminCallbackHandler)


    # --- Downloader Factory ---
    def get_downloader(settings: Settings) -> BaseDownloader:
        if settings.RADIO_SOURCE.lower() == "internet_archive":
            return container.resolve(InternetArchiveDownloader)
        return container.resolve(YouTubeDownloader)

    container.register(BaseDownloader, factory=get_downloader)

    return container


def get_container_for_tests() -> punq.Container:
    # ... (можно будет добавить моки для тестов)
    pass
