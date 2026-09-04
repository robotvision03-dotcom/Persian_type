import tempfile
import unittest
from pathlib import Path

from app.dialogue import ASK_NAME, DialogueManager
from app.iranian_names import FAMILY_NAMES, GIVEN_NAMES, match_person_name
from app.nlu import parse_slots


class IranianNameCatalogTests(unittest.TestCase):
    def test_catalog_is_large(self):
        self.assertGreaterEqual(len(GIVEN_NAMES), 200)
        self.assertGreaterEqual(len(FAMILY_NAMES), 400)

    def test_repairs_missing_letter_in_family(self):
        hit = match_person_name("علی رضای")
        self.assertEqual(hit.given, "علی")
        self.assertEqual(hit.family, "رضایی")
        self.assertEqual(hit.full, "علی رضایی")

    def test_repairs_hossein_and_mousavi(self):
        hit = match_person_name("حسسن موسو")
        self.assertEqual(hit.given, "حسین")
        self.assertEqual(hit.family, "موسوی")

    def test_compound_given_name(self):
        hit = match_person_name("محمد رضا احمدی")
        self.assertEqual(hit.given, "محمدرضا")
        self.assertEqual(hit.family, "احمدی")

    def test_parse_slots_uses_catalog(self):
        slots = parse_slots("علی رضای", "ask_name")
        self.assertEqual(slots["customer_name"], "علی رضایی")


class NameDialogueTests(unittest.TestCase):
    def test_booking_keeps_repaired_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DialogueManager(db_path=Path(tmp) / "book.sqlite")
            manager.start("s1")
            manager.handle("s1", "پژو")
            manager.handle("s1", "پارس")
            manager.handle("s1", "۸۰۰۰۰")
            turn = manager.handle("s1", "علی رضای")
            self.assertEqual(turn["phase"], "ask_slot")
            self.assertEqual(turn["customer"]["name"], "علی رضایی")
            self.assertNotEqual(turn["reply"], ASK_NAME)


if __name__ == "__main__":
    unittest.main()
