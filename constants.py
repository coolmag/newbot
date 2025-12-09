from enum import Enum


class MenuCallback(str, Enum):
    """Callback data для главного меню."""
    REFRESH = "menu:refresh"
    ADMIN_PANEL = "menu:admin_panel"
    PLAY_TRACK = "menu:play_track"
    VOTE_FOR_GENRE = "menu:vote_genre"
    CHOOSE_MOOD = "menu:choose_mood"


class AdminCallback(str, Enum):
    """Callback data для админ-панели."""
    MAIN_MENU = "admin:main_menu"
    RADIO_ON = "admin:radio_on"
    RADIO_OFF = "admin:radio_off"
    RADIO_SKIP = "admin:radio_skip"
    CHANGE_GENRE = "admin:change_genre"


class GenreCallback:
    """Префикс для колбэков выбора жанра."""
    PREFIX = "genre:"


class VoteCallback:
    """Префикс для колбэков голосования за жанр."""
    PREFIX = "vote:"


class MoodCallback:
    """Префикс для колбэков выбора настроения."""
    PREFIX = "mood:"


class TrackCallback(str, Enum):
    """Callback data для панели управления треком."""
    LIKE = "track:like"
    DISLIKE = "track:dislike"
    ADD_TO_PLAYLIST = "track:add_to_playlist"
    DELETE = "track:delete"
