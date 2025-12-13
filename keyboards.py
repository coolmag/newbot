from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from constants import AdminCallback, MenuCallback, TrackCallback, GenreCallback, VoteCallback, MoodCallback
from config import get_settings


def get_main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """
    Возвращает главное меню бота с основными действиями.
    """
    keyboard = [
        [InlineKeyboardButton("🎵 Поиск трека", callback_data=MenuCallback.PLAY_TRACK)],
        [InlineKeyboardButton("😊 Выбрать настроение", callback_data=MenuCallback.CHOOSE_MOOD)],
        [InlineKeyboardButton("🗳️ Голосовать за жанр", callback_data=MenuCallback.VOTE_FOR_GENRE)]
    ]
    if is_admin:
        keyboard.append(
            [InlineKeyboardButton("👑 Админ-панель", callback_data=MenuCallback.ADMIN_PANEL)]
        )
    return InlineKeyboardMarkup(keyboard)


def get_admin_panel_keyboard(is_radio_on: bool) -> InlineKeyboardMarkup:
    """
    Возвращает клавиатуру админ-панели.
    """
    radio_button = (
        InlineKeyboardButton("⏹️ Выключить радио", callback_data=AdminCallback.RADIO_OFF)
        if is_radio_on
        else InlineKeyboardButton("▶️ Включить радио", callback_data=AdminCallback.RADIO_ON)
    )
    keyboard = [
        [radio_button, InlineKeyboardButton("🎶 Сменить жанр", callback_data=AdminCallback.CHANGE_GENRE)],
        [InlineKeyboardButton("⏭️ Следующий трек", callback_data=AdminCallback.RADIO_SKIP)],
        [InlineKeyboardButton("🎤 Режим артиста", callback_data=AdminCallback.ARTIST_MODE)],
        # Исправлено: кнопка "назад" теперь использует MenuCallback.REFRESH для возврата в главное меню
        [InlineKeyboardButton("↩️ Назад в меню", callback_data=MenuCallback.REFRESH)],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_track_control_keyboard(track_id: str, is_in_favorites: bool = False) -> InlineKeyboardMarkup:
    """
    Возвращает клавиатуру для управления треком.
    :param track_id: Уникальный идентификатор трека (YouTube ID).
    :param is_in_favorites: Находится ли трек в избранном у пользователя.
    """
    add_to_playlist_text = "⭐ В избранном" if is_in_favorites else "➕ В избранное"
    
    keyboard = [
        [
            InlineKeyboardButton("❤️", callback_data=f"{TrackCallback.PREFIX}{TrackCallback.LIKE}:{track_id}"),
            InlineKeyboardButton("💔", callback_data=f"{TrackCallback.PREFIX}{TrackCallback.DISLIKE}:{track_id}"),
            InlineKeyboardButton(add_to_playlist_text, callback_data=f"{TrackCallback.PREFIX}{TrackCallback.ADD_TO_PLAYLIST}:{track_id}"),
            # Кнопка удаления остается простой, т.к. она просто удаляет сообщение
            InlineKeyboardButton("🗑️", callback_data=f"{TrackCallback.PREFIX}{TrackCallback.DELETE}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_genre_choice_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для выбора жанра радио (для админа).
    """
    settings = get_settings()
    buttons = [
        InlineKeyboardButton(
            text=genre.capitalize(), 
            callback_data=f"{GenreCallback.PREFIX}{genre}"
        ) 
        for genre in settings.RADIO_GENRES
    ]
    # Группируем кнопки по 3 в ряд
    keyboard = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    keyboard.append([InlineKeyboardButton("↩️ Назад в админ-панель", callback_data=MenuCallback.ADMIN_PANEL)])
    return InlineKeyboardMarkup(keyboard)


def get_genre_voting_keyboard(genres_for_voting: List[str], votes: dict = None) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для голосования за жанр радио.
    Показывает количество голосов для переданного списка жанров.
    """
    if votes is None:
        votes = {}

    buttons = []
    for genre in genres_for_voting:
        vote_count = len(votes.get(genre, []))
        text = f"{genre.capitalize()}"
        if vote_count > 0:
            text += f" [{vote_count}]"
        
        buttons.append(
            InlineKeyboardButton(text=text, callback_data=f"{VoteCallback.PREFIX}{genre}")
        )

    # Группируем кнопки по 2 в ряд
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(keyboard)


def get_mood_choice_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для выбора настроения радио.
    """
    settings = get_settings()
    mood_names = list(settings.RADIO_MOODS.keys())
    
    buttons = [
        InlineKeyboardButton(
            text=mood.capitalize(), 
            callback_data=f"{MoodCallback.PREFIX}{mood}"
        ) 
        for mood in mood_names
    ]
    # Группируем кнопки по 2 в ряд для компактности
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([InlineKeyboardButton("↩️ Назад в меню", callback_data=MenuCallback.REFRESH)])
    return InlineKeyboardMarkup(keyboard)


def get_voting_in_progress_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура, отображаемая, когда пользователь пытается начать голосование, а оно уже идет.
    """
    keyboard = [
        # В будущем можно добавить кнопку для обновления сообщения с голосованием
        [InlineKeyboardButton("↩️ Назад в меню", callback_data=MenuCallback.REFRESH)],
    ]
    return InlineKeyboardMarkup(keyboard)


