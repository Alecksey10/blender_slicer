"""Register the catalog with Blender's translation system.

Blender translates panel labels, operator labels and property names through
``bpy.app.translations``.  Registering a domain with ``{"ru_RU": {"*": {...}}}``
makes the labels in this add-on follow the user's interface language without
each panel having to call :func:`t` itself.
"""

from __future__ import annotations

DOMAIN = "blender_slicer"


def current_locale() -> str:
    """Locale of the Blender interface, normalized to a catalog code."""

    from ...i18n import normalize_locale

    try:
        import bpy

        return normalize_locale(getattr(bpy.app.translations, "locale", "en"))
    except Exception:  # noqa: BLE001 - no bpy, no translation API
        return "en"


def tr(message: str, **kwargs) -> str:
    """Translate a UI string into the current Blender interface language.

    Blender does not translate plain ``layout.label(text=...)`` strings on its
    own, so every static label is passed through here.
    """

    from ...i18n import t

    return t(message, current_locale(), **kwargs)


def _payload() -> dict:
    from ...i18n import TRANSLATIONS

    return {
        code: {"*": dict(entries)}
        for code, entries in TRANSLATIONS.items()
        if code != "en" and entries
    }


def register() -> None:
    import bpy

    translations = getattr(getattr(bpy, "app", None), "translations", None)
    if translations is None or not _payload():
        return
    try:
        translations.register(DOMAIN, _payload())
    except (ValueError, RuntimeError):  # already registered by a reload
        pass


def unregister() -> None:
    import bpy

    translations = getattr(getattr(bpy, "app", None), "translations", None)
    if translations is None:
        return
    try:
        translations.unregister(DOMAIN)
    except (ValueError, RuntimeError):
        pass
