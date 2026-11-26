"""Обучение технолога должно действовать в боевом маршруте (каталог сайта), а не только в запасном."""
import os
import tempfile
import threading
import unittest
import unittest.mock

from src import training
from src.catalog_search import CatalogSearchEngine, material_iso
from src.engine import ToolAdvisorEngine
from src import materials_mapping


def item(family, category, name, sku=None, stock=10, price=1000.0, brand="TestBrand", **attrs):
    return {"id": sku or name, "sku": sku or name, "name": name, "brand": brand,
            "family": family, "category": category, "section": "", "subsection": "",
            "stock": stock, "price": price, "currency": "RUB", "price_on_request": False,
            "active": True, "url": "https://qtool.ru/item/" + (sku or name), "attrs": attrs}


ITEMS = [
    item("insert", "turning_insert", "CNMG 120408 PM 4325", sku="CNMG120408",
         iso_code="CNMG120408", insert_shape="C", size_code=12, corner_radius_mm=0.8,
         chipbreaker="PM", iso_group="P", operation="semi_finishing", grade="4325"),
    item("insert", "turning_insert", "CNMG 120408 PM H1", sku="CNMG120408H1",
         iso_code="CNMG120408", insert_shape="C", size_code=12, corner_radius_mm=0.8,
         chipbreaker="PM", iso_group="H", operation="finishing", grade="H1"),
    item("accessory", "tool_holder", "Патрон BT40-SL20-10 Weldon", sku="BT40-SL20-10",
         standard="BT40", clamp_mm=20.0),
    item("accessory", "tool_holder", "Патрон BT40-SL20-90 Weldon", sku="BT40-SL20-90",
         standard="BT40", clamp_mm=20.0),
]


class TrainingSiteRoute(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_path = training.PATH
        training.PATH = os.path.join(self.tmp.name, "training_examples.csv")
        training._cache.update(mtime=0.0, rows=[], index=None, exact=None)
        self.site = CatalogSearchEngine([dict(it, attrs=dict(it["attrs"])) for it in ITEMS])
        self.eng = object.__new__(ToolAdvisorEngine)   # лёгкий стенд без загрузки прайсов
        self.eng._tls = threading.local()

    def tearDown(self):
        training.PATH = self._old_path
        training._cache.update(mtime=0.0, rows=[], index=None, exact=None)
        self.tmp.cleanup()

    def test_exact_example_overrides_iso(self):
        training.add_example("ТВЧ металл", correct_iso="H")
        res = self.eng._site_answer("ТВЧ металл", self.site)
        self.assertEqual(res["parsed"]["iso"], "H")
        self.assertIn("Применён пример технолога", res["response_text"])
        self.assertEqual(res["tool_result"].get("trained_example"), "1")

    def test_fuzzy_example_fills_missing_iso(self):
        training.add_example("ТВЧ металл", correct_iso="H")
        res = self.eng._site_answer("твч металл обработка", self.site)
        self.assertEqual(res["parsed"]["iso"], "H")

    def test_fuzzy_does_not_replace_parsed_iso(self):
        training.add_example("ТВЧ металл", correct_iso="H")
        res = self.eng._site_answer("пластина твч чугун", self.site)  # парсер сам нашёл K
        self.assertEqual(res["parsed"]["iso"], "K")

    def test_fuzzy_respects_explicit_material_word(self):
        training.add_example("ТВЧ металл", correct_iso="H")
        res = self.eng._site_answer("твч металл чугун", self.site)  # группа не задана, но чугун назван явно
        self.assertNotEqual(res["parsed"]["iso"], "H")

    def test_exact_pins_skus(self):
        training.add_example("патрон bt40 weldon 20", correct_skus="BT40-SL20-10; BT40-SL20-90")
        res = self.eng._site_answer("патрон bt40 weldon 20", self.site)
        skus = [p["sku"] for p in res["tool_result"]["products"]]
        self.assertEqual(skus[:2], ["BT40-SL20-10", "BT40-SL20-90"])

    def test_homoglyph_query_matches_exact(self):
        training.add_example("CNMG 120408", correct_iso="H")
        res = self.eng._site_answer("СNMG 120408", self.site)  # кириллическая С
        self.assertEqual(res["parsed"]["iso"], "H")

    def test_empty_example_is_not_saved(self):
        self.assertIsNone(training.add_example("пустой запрос без поправок"))
        self.assertEqual(training.count(), 0)

    def test_rejected_row_does_not_shift_vectors(self):
        # индекс TF-IDF должен строиться по отфильтрованному списку, иначе векторы съезжают
        training.add_example("патрон bt40 weldon 20", correct_skus="BT40-SL20-10")
        training.add_example("ТВЧ металл", correct_iso="H")
        rows = training._read()
        rows[0]["status"] = "rejected"
        training._write(rows)
        res = self.eng._site_answer("твч металл обработка", self.site)
        self.assertEqual(res["parsed"]["iso"], "H")

    def test_pins_by_site_id(self):
        # технолог называет позиции ID сайта (Битрикс), а не артикулом - пины должны находиться
        it = item("holder", "mini_tool", "MIR 6 A60 L22 резьбовой минирезец DESKAR",
                  sku="MIR 6 A60 L22 резьбовой минирезец DESKAR", shank_mm=6.0)
        it["id"] = "65880"
        site = CatalogSearchEngine([dict(it, attrs=dict(it["attrs"]))])
        training.add_example("минирезец резьбовой хвостовик 6", correct_skus="65880")
        res = self.eng._site_answer("минирезец резьбовой хвостовик 6", site)
        self.assertTrue(res["tool_result"].get("trained"))
        self.assertEqual(res["tool_result"]["products"][0]["sku"], "MIR 6 A60 L22 резьбовой минирезец DESKAR")

    def test_missing_pins_warning(self):
        training.add_example("минирезец резьбовой хвостовик 6", correct_skus="999999999")
        res = self.eng._site_answer("минирезец резьбовой хвостовик 6", self.site)
        self.assertIn("не найдены", res["response_text"])

    def test_comment_only_example_shown(self):
        training.add_example("минирезец для прямых торцевых канавок", comment="минирезцы - раздел каталога")
        res = self.eng._site_answer("минирезец для прямых торцевых канавок", self.site)
        self.assertIn("Комментарий технолога", res["response_text"])

    def test_shape_size_radius_corrections(self):
        training.add_example("пластина ромб чистовая", correct_shape="C", correct_size="12",
                             correct_radius="0.8", correct_operation="finishing")
        res = self.eng._site_answer("пластина ромб чистовая", self.site)
        self.assertEqual(res["parsed"]["shape"], "C")
        self.assertEqual(res["parsed"]["operation"], "finishing")


class MiniToolRouting(unittest.TestCase):
    def test_minirezec_category_and_sizes(self):
        items = [
            item("holder", "mini_tool", "MFR 4 B0.5 L10 торцевой минирезец для прямых канавок DESKAR", sku="MFR4B05L10"),
            item("holder", "mini_tool", "MFR 4 B2.0 L15 торцевой минирезец для прямых канавок DESKAR", sku="MFR4B20L15"),
            item("holder", "holder_grooving", "MGEHR2525-2C отрезная державка DESKAR", sku="MGEHR2525-2C"),
        ]
        site = CatalogSearchEngine(items)
        res = site.search("минирезец для прямых торцевых канавок. канавка - 0,5мм. хвостовик минирезца - 4мм")
        skus = [p["sku"] for p in res["products"]]
        self.assertIn("MFR4B05L10", skus)
        self.assertNotIn("MGEHR2525-2C", skus)
        self.assertNotIn("MFR4B20L15", skus)


class MaterialRulesSiteRoute(unittest.TestCase):
    def test_technolog_rule_reaches_site_search(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "materials.csv")
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write('pattern,iso,note\n"твч","H","правило технолога"\n')
        old = materials_mapping._MATERIALS_FILES
        materials_mapping._MATERIALS_FILES = [path]
        materials_mapping.reload_material_rules()
        try:
            self.assertEqual(material_iso("твч металл"), "H")
        finally:
            materials_mapping._MATERIALS_FILES = old
            materials_mapping.reload_material_rules()


class TrainingEndToEnd(unittest.TestCase):
    """Сквозной сценарий: пример через HTTP API админки -> поисковый запрос через HTTP API."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import app
        cls.app = app
        if app.engine is None:
            app.build_engine()

        class QuietHandler(app.AdvisorHTTPHandler):
            def log_message(self, *a):
                pass

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_path = training.PATH
        training.PATH = os.path.join(self.tmp.name, "training_examples.csv")
        training._cache.update(mtime=0.0, rows=[], index=None, exact=None)
        self._unrec = unittest.mock.patch.object(self.app.engine, "_log_unrecognized", lambda q: None)
        self._unrec.start()

    def tearDown(self):
        self._unrec.stop()
        training.PATH = self._old_path
        training._cache.update(mtime=0.0, rows=[], index=None, exact=None)
        self.tmp.cleanup()

    def _post(self, path, payload):
        import json
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_train_then_search(self):
        r = self._post("/api/admin/train_add", {"query": "ТВЧ металл", "correct_iso": "H"})
        self.assertTrue(r["ok"], r)
        res = self._post("/api/query", {"query": "ТВЧ металл"})
        self.assertIn("Применён пример технолога", res["response_text"])
        self.assertEqual((res.get("parsed") or {}).get("iso"), "H")

    def test_empty_train_add_rejected_without_write(self):
        r = self._post("/api/admin/train_add", {"query": "что-нибудь"})
        self.assertFalse(r["ok"])
        self.assertEqual(training.count(), 0)


if __name__ == "__main__":
    unittest.main()