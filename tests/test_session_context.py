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


if __name__ == "__main__":
    unittest.main()
