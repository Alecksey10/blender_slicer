"""The localization system: catalog, locale aliases and fallbacks."""

from __future__ import annotations

import unittest

from blender_slicer.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    TRANSLATIONS,
    catalog_for,
    normalize_locale,
    t,
)


class LocaleTests(unittest.TestCase):
    def test_supported_locales_are_english_and_russian(self):
        self.assertEqual(SUPPORTED_LOCALES, ("en", "ru"))
        self.assertEqual(DEFAULT_LOCALE, "en")
        self.assertEqual(set(TRANSLATIONS), set(SUPPORTED_LOCALES))

    def test_blender_locale_codes_are_normalized(self):
        for raw in ("ru_RU", "ru-RU", "ru", "ru_RU.UTF-8", "RU"):
            self.assertEqual(normalize_locale(raw), "ru", raw)
        for raw in ("en_US", "en-US", "en", "", None, "de_DE"):
            self.assertEqual(normalize_locale(raw), "en", raw)

    def test_known_messages_are_translated(self):
        self.assertEqual(t("Cut offsets", "ru_RU"), "Отступы срезов")
        self.assertEqual(t("Section shrink", "ru"), "Ужимание сечений")
        self.assertEqual(t("Contacts", "ru"), "Контакты")

    def test_english_is_the_identity_catalog(self):
        self.assertEqual(t("Cut offsets", "en"), "Cut offsets")
        self.assertEqual(t("Cut offsets"), "Cut offsets")

    def test_unknown_messages_pass_through(self):
        self.assertEqual(t("Something new", "ru"), "Something new")

    def test_placeholders_are_formatted(self):
        self.assertEqual(t("{count} slices", "ru", count=5), "5 slices")
        self.assertEqual(t("{count} slices", "ru", count=2), "2 slices")

    def test_catalog_values_are_non_empty(self):
        for locale, entries in TRANSLATIONS.items():
            for message, text in entries.items():
                self.assertTrue(message.strip(), locale)
                self.assertTrue(text.strip(), f"{locale}: {message}")

    def test_blender_helper_follows_the_interface_locale(self):
        from blender_slicer.adapters.blender import i18n as blender_i18n

        original = blender_i18n.current_locale
        blender_i18n.current_locale = lambda: "ru"
        try:
            self.assertEqual(blender_i18n.tr("Contacts"), "Контакты")
            self.assertEqual(
                blender_i18n.tr("Slices: {slices}   Points: {points}", slices=3, points=9),
                "Срезы: 3   Точки: 9",
            )
        finally:
            blender_i18n.current_locale = original

    def test_keyboard_labels_of_the_panel_are_covered(self):
        labels = (
            "Slice Engine",
            "Actions",
            "Last result",
            "Layers",
            "Report",
            "About",
            "Generate Slices",
            "Process Slices",
            "Find Contacts",
            "Cut offsets",
            "Section shrink",
            "Contacts",
            "Performance",
        )
        catalog = catalog_for("ru")
        missing = [label for label in labels if label not in catalog]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
