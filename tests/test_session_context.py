"""Контекст диалога: запрос с названием группы не склеивается с предыдущим."""
import unittest

import app

PREV = "державка 2525 под dnmg15"


class EffectiveQueryTest(unittest.TestCase):
    def setUp(self):
        self.sid = "test-context"
        app.SESSIONS.clear(self.sid)
        app.SESSIONS.put(self.sid, last_q=PREV, decision="site_search")

    def tearDown(self):
        app.SESSIONS.clear(self.sid)

    def test_new_query_with_group_stays_alone(self):
        # «державка 2020 под cnmg12» после «под dnmg15» отвечала пластинами DNMG15
        q = "державка 2020 под cnmg12"
        self.assertEqual(app.effective_query(self.sid, q), q)

    def test_another_group_starts_new_query(self):
        self.assertEqual(app.effective_query(self.sid, "метчик М10"), "метчик М10")

    def test_bare_holder_code_is_not_merged_with_previous_plate(self):
        # «mcbnr 2020» после «державка 2020 под tnmg16» получала под пластину TNMG16
        app.SESSIONS.put(self.sid, last_q="державка 2020 под tnmg16", decision="site_search")
        self.assertEqual(app.effective_query(self.sid, "mcbnr 2020"), "mcbnr 2020")

    def test_thread_size_clarification_is_merged(self):
        app.SESSIONS.put(self.sid, last_q="метчик", decision="site_search")
        self.assertEqual(app.effective_query(self.sid, "M10"), "метчик. M10")

    def test_short_clarification_is_merged(self):
        self.assertEqual(app.effective_query(self.sid, "12"), PREV + ". 12")

    def test_plate_code_clarification_is_merged(self):
        self.assertEqual(app.effective_query(self.sid, "под cnmg12"), PREV + ". под cnmg12")

    def test_under_shank_clarification_is_merged(self):
        app.SESSIONS.put(self.sid, last_q="держатель осевого инструмента", decision="site_search")
        self.assertEqual(app.effective_query(self.sid, "под хвостовик 20"),
                         "держатель осевого инструмента. под хвостовик 20")

    def test_explicit_size_starts_new_query(self):
        q = "хвостовик 20 мм"
        self.assertEqual(app.effective_query(self.sid, q), q)

    def test_jaw_query_does_not_inherit_previous_filter(self):
        # «кулачки каленые к11 шаг 5» повторяло выдачу держателей осевого инструмента
        app.SESSIONS.put(self.sid, last_q="держатель осевого инструмента под хвостовик 32",
                         decision="site_search")
        q = "кулачки каленые к11 шаг 5"
        self.assertEqual(app.effective_query(self.sid, q), q)

    def test_unknown_designation_does_not_inherit_previous_query(self):
        # «MTA2 велдон 10» после «расточная s20 под dcmt» отдавал те же 9 позиций
        app.SESSIONS.put(self.sid, last_q="расточная s20 под dcmt", decision="site_search")
        for q in ("MTA2 велдон 10", "SK40", "HSK63", "ER32", "конус морзе 2"):
            self.assertEqual(app.effective_query(self.sid, q), q)

    def test_short_clarification_still_merges_after_unknown_words(self):
        app.SESSIONS.put(self.sid, last_q="расточная s20 под dcmt", decision="site_search")
        self.assertEqual(app.effective_query(self.sid, "под хвостовик 20"),
                         "расточная s20 под dcmt. под хвостовик 20")


if __name__ == "__main__":
    unittest.main()
