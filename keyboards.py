from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """
    Возвращает основное меню бота.
    Кнопка админ-панели отображается только для администраторов.
    """
    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data='menu_refresh')]
    ]
    if is_admin:
        keyboard.insert(0, [InlineKeyboardButton("👑 Админ-панель", callback_data='admin_panel')])
    
    return InlineKeyboardMarkup(keyboard)


def get_admin_panel_keyboard(is_radio_on: bool) -> InlineKeyboardMarkup:


    """


    Возвращает клавиатуру админ-панели.


    """


    radio_button = (


        InlineKeyboardButton("⏹️ Выключить радио", callback_data='radio_off')


        if is_radio_on


        else InlineKeyboardButton("▶️ Включить радио", callback_data='radio_on')


    )


    


    keyboard = [


        [radio_button],


        [InlineKeyboardButton("⏭️ Следующий трек", callback_data='radio_skip')],


        [InlineKeyboardButton("↩️ Назад в меню", callback_data='menu_main')]


    ]


    return InlineKeyboardMarkup(keyboard)








def get_audiobook_chapters_keyboard(chapters: list, page: int = 0) -> InlineKeyboardMarkup:


    """


    Создает клавиатуру со списком глав аудиокниги с пагинацией.


    """


    items_per_page = 5


    start_index = page * items_per_page


    end_index = start_index + items_per_page


    


    keyboard = []


    for i, chapter in enumerate(chapters[start_index:end_index]):


        chapter_title = chapter.get('title', f'Глава {start_index + i + 1}')


        callback_data = f"ab_download_{chapter.get('id')}"


        keyboard.append([InlineKeyboardButton(f"▶️ {chapter_title[:60]}", callback_data=callback_data)])


        


    # Пагинация


    nav_buttons = []


    if page > 0:


        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"ab_page_{page - 1}"))


    if end_index < len(chapters):


        nav_buttons.append(InlineKeyboardButton("➡️ Вперед", callback_data=f"ab_page_{page + 1}"))


    


    if nav_buttons:


        keyboard.append(nav_buttons)


        


    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="ab_cancel")])


    


    return InlineKeyboardMarkup(keyboard)

