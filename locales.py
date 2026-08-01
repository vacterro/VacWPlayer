LOCALES = {
    "en": {
        "app_title": "WildRiftAssistant",
        "champion": "Champion:",
        "add": "Add",
        "export": "Export",
        "import": "Import",
        "backup": "Backup",
        "stop": "Stop",
        "apply_start": "Run",
        "ready": "Ready",
        "engine_stopped": "Engine stopped",
        "config_exported": "Config exported",
        "config_imported": "Config imported",
        "config_import_confirm": "Replace current config with\n%s?",
        "import_failed": "Import failed",
        "export_failed": "Export failed",
        "backup_failed": "Backup failed",
        "export_title": "Export config",
        "import_title": "Import config",
        "reset_defaults": "Reset defaults",
        "enable": "Enable AFK Farm",
        "toggle_key": "Toggle key:",
        "move_duration": "Move duration (ms):",
        "follow_cursor": "Follow cursor",
        "combo_keys": "Combo keys (comma sep):",
        "combo_step_ms": "Combo step ms:",
        "cycle_slots": "Cycle through slots:",
        "farm_desc": "Cycle through Minimap tab positions -> move+combo -> next pos -> ...",
        "tab_main": "Main",
        "tab_death": "Death Watch",
        "tab_auto": "Auto Continue",
        "tab_minimap": "Minimap",
        "tab_afkfarm": "AFK Farm",
        "tab_autoaccept": "Auto Accept",
        "auto_accept_enable": "Enable Auto-Accept",
        "auto_accept_desc": "When enabled, scans for 'Accept' button and clicks it.\n"
                            "Provide template: templates/accept_button.png",
        "hotkeys": "Keys",
        "browse_combos": "Web",
        "no_ahk": "AHK: stopped",
        "ahk_running": "AHK: running",
        "slots": {
            "top": "Top",
            "mid": "Mid",
            "bot": "Bot",
            "top_deep": "Top Deep",
            "mid_deep": "Mid Deep",
            "bot_deep": "Bot Deep",
            "base": "Base",
            "enemy_base": "Enemy Base",
        },
    },
    "ru": {
        "app_title": "WildRiftAssistant",
        "champion": "Чемпион:",
        "add": "Add",
        "export": "Exp",
        "import": "Imp",
        "backup": "Bak",
        "stop": "Stop",
        "apply_start": "Run",
        "ready": "Готов",
        "engine_stopped": "Движок остановлен",
        "config_exported": "Конфиг экспортирован",
        "config_imported": "Конфиг импортирован",
        "config_import_confirm": "Заменить текущий конфиг на\n%s?",
        "import_failed": "Ошибка импорта",
        "export_failed": "Ошибка экспорта",
        "backup_failed": "Ошибка бэкапа",
        "export_title": "Экспорт конфига",
        "import_title": "Импорт конфига",
        "reset_defaults": "Сброс",
        "enable": "Включить AFK Farm",
        "toggle_key": "Клавиша вкл:",
        "move_duration": "Длит. движения (мс):",
        "follow_cursor": "За курсором",
        "combo_keys": "Клавиши комбо (через запятую):",
        "combo_step_ms": "Шаг комбо (мс):",
        "cycle_slots": "Точки для цикла:",
        "farm_desc": "Цикл по точкам Minimap → движение+комбо → след. точка → ...",
        "tab_main": "Главная",
        "tab_death": "Death Watch",
        "tab_auto": "Auto Continue",
        "tab_minimap": "Миникарта",
        "tab_afkfarm": "AFK Farm",
        "tab_autoaccept": "Auto Accept",
        "auto_accept_enable": "Вкл. автопринятие",
        "auto_accept_desc": "Сканирует кнопку 'Accept' в фоне и кликает.\n"
                            "Шаблон: templates/accept_button.png",
        "hotkeys": "Keys",
        "browse_combos": "Web",
        "no_ahk": "AHK: остановлен",
        "ahk_running": "AHK: запущен",
        "slots": {
            "top": "Верх",
            "mid": "Центр",
            "bot": "Низ",
            "top_deep": "Верх глубоко",
            "mid_deep": "Центр глубоко",
            "bot_deep": "Низ глубоко",
            "base": "База",
            "enemy_base": "База врага",
        },
    },
}


class Locale:
    _current = "ru"

    @classmethod
    def set_lang(cls, code):
        cls._current = code if code in LOCALES else "en"

    @classmethod
    def get(cls, code=None):
        return LOCALES.get(code or cls._current, LOCALES["en"])

    @classmethod
    def tr(cls, key, fallback=None):
        d = cls.get()
        parts = key.split(".")
        for p in parts:
            if isinstance(d, dict):
                d = d.get(p)
            else:
                return fallback or key
        return d if isinstance(d, str) else (fallback or key)

    @classmethod
    def current(cls):
        return cls._current

    @classmethod
    def toggle(cls):
        cls._current = "en" if cls._current == "ru" else "ru"
        return cls._current
