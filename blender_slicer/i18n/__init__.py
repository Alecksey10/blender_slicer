"""Translations used by the GUI adapters.

The catalog is plain data, so it can be tested without Blender and reused by a
Qt/Unreal adapter.  Blender registers it through ``bpy.app.translations``; a
host that has no translation system can call :func:`t` directly.
"""

from __future__ import annotations

SUPPORTED_LOCALES = ("en", "ru")

_ALIASES = {
    "ru": "ru",
    "ru_ru": "ru",
    "ru_ru.utf8": "ru",
    "en": "en",
    "en_us": "en",
    "en_gb": "en",
}

DEFAULT_LOCALE = "en"

#: English msgid -> localized text.  English itself needs no catalog.
TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {},
    "ru": {
        # panels
        "Slice Engine": "Движок срезов",
        "Actions": "Действия",
        "Last result": "Последний результат",
        "Layers": "Слои",
        "Report": "Отчёт",
        "About": "О программе",
        "No slice plans yet": "Планов срезов пока нет",
        "Settings are not registered": "Настройки не зарегистрированы",
        "No diagnostics": "Диагностики нет",
        "Result is stale; regenerate slices": "Результат устарел — создайте срезы заново",
        # action buttons
        "Run": "Запустить",
        "Generate Slices": "Создать срезы",
        "Process Slices": "Обработать срезы",
        "Find Contacts": "Найти контакты",
        "Clear": "Очистить",
        "Export Settings": "Экспорт настроек",
        "Import Settings": "Импорт настроек",
        "Export Slices": "Экспорт срезов",
        "Show Report": "Показать отчёт",
        "Frame Contacts": "Показать контакты",
        "Settings are not registered": "Настройки не зарегистрированы",
        "Slices: {slices}   Points: {points}": "Срезы: {slices}   Точки: {points}",
        "Errors: {errors}   Warnings: {warnings}": "Ошибки: {errors}   Предупреждения: {warnings}",
        "Contacts: {contacts}   Layers: {layers}": "Контакты: {contacts}   Слои: {layers}",
        "Interface language: {lang}": "Язык интерфейса: {lang}",
        "Host-independent slicer core": "Ядро срезов, не зависящее от хоста",
        "All engine coordinates are 2D millimetres": "Все координаты движка — 2D в миллиметрах",
        "1 Blender unit is configurable (default 1000 mm)": "1 единица Blender настраивается (по умолчанию 1000 мм)",
        "Cut offsets: X outward, Z inward by default": "Отступы: X наружу, Z внутрь по умолчанию",
        # sections
        "Source": "Источник",
        "Slice plan": "План срезов",
        "Section shrink": "Ужимание сечений",
        "Cut offsets": "Отступы срезов",
        "Material": "Материал",
        "Fillet corners": "Скругление углов",
        "Trim tight corners": "Обрезка тесных углов",
        "Smooth": "Сглаживание",
        "Simplify": "Упрощение",
        "Densify": "Уплотнение",
        "Resample": "Пересэмплирование",
        "Limit curvature": "Ограничение кривизны",
        "Contacts": "Контакты",
        "Performance": "Производительность",
        "Output": "Вывод",
        "Grow sections": "Расширение сечений",
        # fields
        "Source mesh": "Исходный меш",
        "1 BU in mm": "1 BU в мм",
        "1 BU = mm": "1 BU = мм",
        "Slice mode": "Режим срезов",
        "Axis": "Ось",
        "Count": "Количество",
        "Spacing": "Шаг",
        "Spacing (mm)": "Шаг (мм)",
        "Auto spacing": "Автошаг",
        "Offset": "Смещение",
        "Offset (mm)": "Смещение (мм)",
        "Centered": "По центру",
        "Centered on object": "Центрировать по объекту",
        "Start angle": "Начальный угол",
        "End angle": "Конечный угол",
        "Origin offset": "Смещение начала",
        "Origin offset (mm)": "Смещение начала (мм)",
        "Blender material": "Материал Blender",
        "Thickness": "Толщина",
        "Min bend radius": "Мин. радиус гиба",
        "Max bend angle": "Макс. угол гиба",
        "Min segment": "Мин. сегмент",
        "Build curves in scene": "Строить кривые в сцене",
        "Curve radius (mm)": "Радиус кривой (мм)",
        "Check self-intersections": "Проверять самопересечения",
        "Shrink sections": "Ужимать сечения",
        "Shrink (%)": "Ужимание (%)",
        "Shrink profile": "Профиль ужимания",
        "Smooth iterations": "Итерации сглаживания",
        "Show all layers": "Показывать все слои",
        "Worker threads": "Потоки обработки",
        "Same pass too": "И в одном проходе",
        "Contact gap": "Зазор контакта",
        "Contact marker": "Размер маркера",
        "Build result curves": "Строить кривые результата",
        "Curve radius": "Радиус кривой",
        "Check self-intersections": "Проверять самопересечения",
        "Fillet radius (mm)": "Радиус скругления (мм)",
        "Min corner turn (deg)": "Мин. угол поворота (град)",
        "If it does not fit": "Если радиус не влезает",
        "If radius does not fit": "Если радиус не влезает",
        "Trim the curve": "Обрезать кривую",
        "Leave it to fillet": "Оставить скруглению",
        # statuses
        "Ready": "Готово",
        "Cleared": "Очищено",
        "Settings imported": "Настройки импортированы",
        "Generate slices first": "Сначала создайте срезы",
        "Slices are outdated - generate them again": "Срезы устарели — создайте их заново",
    },
}


def normalize_locale(locale: str | None) -> str:
    """Map ``ru_RU``/``ru-RU``/``en_US`` to a catalog code."""

    if not locale:
        return DEFAULT_LOCALE
    key = str(locale).strip().replace("-", "_").lower()
    if key in _ALIASES:
        return _ALIASES[key]
    if key.startswith("ru"):
        return "ru"
    return DEFAULT_LOCALE


def catalog_for(locale: str | None = None) -> dict[str, str]:
    return dict(TRANSLATIONS.get(normalize_locale(locale), {}))


def t(message: str, locale: str | None = None, **kwargs) -> str:
    """Translate ``message``; unknown messages are returned unchanged."""

    text = catalog_for(locale).get(message, message)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text
