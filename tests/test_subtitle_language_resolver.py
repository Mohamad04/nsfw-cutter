import unittest

from services.subtitles.language_resolver import (
    resolve_external_language_token,
    resolve_language_name,
)


class SubtitleLanguageResolverTests(unittest.TestCase):
    def test_standard_iso_codes_resolve_through_pycountry(self):
        self.assertEqual(resolve_language_name("ara"), "Arabic")
        self.assertEqual(resolve_language_name("fra"), "French")
        self.assertEqual(resolve_language_name("fre"), "French")
        self.assertEqual(resolve_language_name("eng"), "English")
        self.assertEqual(resolve_language_name("deu"), "German")
        self.assertEqual(resolve_language_name("spa"), "Spanish")

    def test_external_flags_are_not_treated_as_languages(self):
        self.assertEqual(resolve_external_language_token("forced"), (None, None))
        self.assertEqual(resolve_external_language_token("sdh"), (None, None))
        self.assertEqual(resolve_external_language_token("cc"), (None, None))

    def test_unknown_external_code_does_not_crash(self):
        self.assertEqual(resolve_external_language_token("xx"), (None, None))


if __name__ == "__main__":
    unittest.main()
