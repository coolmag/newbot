
import asyncio
from typing import Optional
from dataclasses import dataclass, field

from config import settings, TrackInfo
from logger import logger


@dataclass
class DownloadResult:
    """
    Результат операции загрузки. Содержит либо информацию о треке, либо ошибку.
    """
    success: bool
    file_path: Optional[str] = None
    track_info: Optional[TrackInfo] = None
    error: Optional[str] = None


class BaseDownloader:
    """
    Абстрактный базовый класс для всех загрузчиков.
    Предоставляет общий интерфейс и логику повторных попыток.
    """
    def __init__(self):
        self.name = self.__class__.__name__
        self.semaphore = asyncio.Semaphore(3)  # Ограничение на 3 одновременные загрузки

    async def download(self, query: str, is_long: bool = False) -> DownloadResult:
        """
        Абстрактный метод для загрузки трека. Должен быть реализован в подклассах.
        
        :param query: Поисковый запрос.
        :param is_long: Флаг для поиска длинного контента (например, аудиокниг).
        """
        raise NotImplementedError("Метод `download` должен быть реализован в подклассе.")

    async def download_with_retry(self, query: str) -> Optional[DownloadResult]:
        """
        Обертка для `download`, добавляющая логику повторных попыток.
        """
        for attempt in range(settings.MAX_RETRIES):
            try:
                # Ограничиваем количество одновременных выполнений этого блока
                async with self.semaphore:
                    result = await self.download(query)

                if result and result.success:
                    logger.info(f"[{self.name}] Успешная загрузка '{query}' (попытка {attempt + 1})")
                    return result
                
                error_msg = result.error if result else "Неизвестная ошибка"
                logger.warning(f"[{self.name}] Неудача загрузки '{query}': {error_msg} (попытка {attempt + 1})")

            except asyncio.TimeoutError:
                logger.error(f"[{self.name}] Таймаут при загрузке '{query}' (попытка {attempt + 1})")
            except Exception as e:
                logger.error(f"[{self.name}] Критическое исключение при загрузке '{query}': {e}", exc_info=True)
            
            # Если это не последняя попытка, ждем перед следующей
            if attempt < settings.MAX_RETRIES - 1:
                delay = settings.RETRY_DELAY_S * (attempt + 1)
                await asyncio.sleep(delay)
        
        logger.error(f"[{self.name}] Загрузка '{query}' провалена после {settings.MAX_RETRIES} попыток.")
        return DownloadResult(success=False, error=f"Не удалось скачать после {settings.MAX_RETRIES} попыток.")

    async def download_long(self, query: str) -> Optional[DownloadResult]:
        """
        Обертка для поиска длинного контента. По умолчанию вызывает обычный `download`.
        Может быть переопределена в подклассах.
        """
        return await self.download_with_retry(query)


