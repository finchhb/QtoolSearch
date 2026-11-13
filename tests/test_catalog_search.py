"""Детерминированный поиск по каталогу qtool.ru на синтетическом наборе всех групп."""
import unittest

from src.catalog_search import CatalogSearchEngine
from src.clarification_advisor import ClarificationAdvisor
from src.engine import ToolAdvisorEngine


def item(family, category, name, sku=None, stock=10, price=1000.0, **attrs):
    base = {
        "id": sku or name, "sku": sku or name, "name": name, "brand": "TestBrand",
        "family": family, "category": category, "section": "", "subsection": "",
        "stock": stock, "price": price, "currency": "RUB", "price_on_request": False,
        "active": True, "url": "https://qtool.ru/item/" + (sku or name), "attrs": attrs,
    }
    return base


ITEMS = [
    item("insert", "turning_insert", "CNMG 120408 PM 4325", sku="CNMG120408",
         iso_code="CNMG120408", insert_shape="C", clearance_angle="N", size_code=12,
         corner_radius_mm=0.8, chipbreaker="PM", iso_group="P", operation="semi_finishing", grade="4325"),
    item("insert", "turning_insert", "CNMG 120412 PM 4325", sku="CNMG120412",
         iso_code="CNMG120412", insert_shape="C", clearance_angle="N", size_code=12,
         corner_radius_mm=1.2, chipbreaker="PM", iso_group="P", operation="semi_finishing", grade="4325"),
    item("insert", "turning_insert", "WNMG 080408 MR 4315", sku="WNMG080408",
         iso_code="WNMG080408", insert_shape="W", clearance_angle="N", size_code=8,
         corner_radius_mm=0.8, chipbreaker="MR", iso_group="P", operation="roughing", grade="4315"),
    item("insert", "turning_insert", "WNMG 080408 FM 4325", sku="WNMG080408FM",
         iso_code="WNMG080408", insert_shape="W", clearance_angle="N", size_code=8,
         corner_radius_mm=0.8, chipbreaker="FM", iso_group="M", operation="finishing", grade="4325"),
    item("drill", "solid_carbide_drill", "Сверло твердосплавное 8,5 мм", sku="DRILL85",
         diameter_mm=8.5, cutting_length_mm=40.0, length_mm=80.0, shank_mm=8.5, material="твердый сплав"),
    item("drill", "solid_carbide_drill", "Сверло твердосплавное 9,0 мм", sku="DRILL90",
         diameter_mm=9.0, stock=0, material="твердый сплав"),
    item("drill", "solid_carbide_drill", "Сверло твердосплавное 12,0 мм 3D 135°", sku="DRILL12-3D",
         diameter_mm=12.0, ld_ratio=3, angle_deg=135.0, material="твердый сплав"),
    item("drill", "solid_carbide_drill", "Сверло твердосплавное 12,0 мм 5D 140°", sku="DRILL12-5D",
         diameter_mm=12.0, ld_ratio=5, angle_deg=140.0, material="твердый сплав"),
    item("mill", "end_mill", "Фреза концевая 10x25x75 3F", sku="MILL10-3F",
         diameter_mm=10.0, shank_mm=10.0, cutting_length_mm=25.0, length_mm=75.0, teeth=3),
    item("mill", "end_mill", "Фреза концевая 10x25x75 4F", sku="MILL10-4F",
         diameter_mm=10.0, shank_mm=10.0, cutting_length_mm=25.0, length_mm=75.0, teeth=4),
    item("tap", "machine_tap", "Метчик машинный M10x1.5", sku="TAP-M10",
         thread="M10x1.5", pitch_mm=1.5, diameter_mm=10.0, material="HSS-E"),
    item("tap", "machine_tap", "Метчик машинный M8x1.25", sku="TAP-M8",
         thread="M8x1.25", pitch_mm=1.25, diameter_mm=8.0, material="HSS-E"),
    item("holder", "holder_external", "PCLNR2525M12 Державка для наружного точения",
         sku="PCLNR2525M12", holder_code="PCLNR2525M12"),
    item("reamer", "machine_reamer", "Развертка машинная 8 H7", sku="REAM8",
         diameter_mm=8.0, tolerance="H7"),
    item("reamer", "machine_reamer", "Развертка машинная 12 H7", sku="REAM12",
         diameter_mm=12.0, tolerance="H7"),
    item("accessory", "collet", "Цанга ER32 12 мм", sku="ER32-12",
         collet_series="ER32", clamp_range="1-12"),
    item("accessory", "collet", "Цанга ER32 16 мм", sku="ER32-16",
         collet_series="ER32", clamp_range="2-16"),
]


class CatalogSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = CatalogSearchEngine(ITEMS)

    def test_insert_exact_code(self):
        res = self.engine.search("CNMG 120408")
        self.assertEqual(res["family"], "insert")
        self.assertEqual(res["level"], "точное")
        self.assertEqual(res["products"][0]["sku"], "CNMG120408")
        self.assertEqual(res["products"][0]["attrs"]["iso_code"], "CNMG120408")

    def test_insert_code_without_spaces_matches(self):
        res = self.engine.search("CNMG120408")
        self.assertEqual(res["products"][0]["sku"], "CNMG120408")

    def test_insert_cyrillic_homoglyph_and_letter_o(self):
        res = self.engine.search("снмг 1204O8")
        self.assertEqual(res["family"], "insert")
        self.assertEqual(res["products"][0]["sku"], "CNMG120408")

    def test_insert_prefix_typo_and_layout(self):
        for query in ("СТМН 120408", "CTMN 120408", "CNGM 120408"):
            res = self.engine.search(query)
            self.assertEqual(res["insert_code"], "CNMG120408", query)
            self.assertEqual(res["products"][0]["sku"], "CNMG120408", query)

    def test_insert_grade_filter(self):
        res = self.engine.search("CNMG 1204 4325")
        self.assertEqual(res["total_found"], 2)
        self.assertTrue(all(p["attrs"].get("grade") == "4325" for p in res["products"]))

    def test_relaxation_reports_partial(self):
        res = self.engine.search("CNMG 120408 9999")
        self.assertEqual(res["level"], "частичное")
        self.assertTrue(any("марка" in r for r in res["relaxations"]))
        self.assertTrue(res["products"])

    def test_material_and_operation(self):
        res = self.engine.search("пластина для нержавейки чистовая")
        self.assertEqual(res["parsed"].get("iso_group"), "M")
        self.assertEqual(res["parsed"].get("operation"), "finishing")
        self.assertEqual([p["sku"] for p in res["products"]], ["WNMG080408FM"])

    def test_drill_diameter_decimal_comma(self):
        res = self.engine.search("сверло 8,5 мм")
        self.assertEqual(res["family"], "drill")
        self.assertEqual(res["total_found"], 1)
        self.assertEqual(res["products"][0]["sku"], "DRILL85")

    def test_drill_for_thread_m10(self):
        res = self.engine.search("сверло под резьбу М10")
        self.assertEqual(res["products"][0]["sku"], "DRILL85")
        self.assertEqual(res["tap_drill"]["thread"], "M10")
        self.assertAlmostEqual(res["tap_drill"]["drill_mm"], 8.5)

    def test_drill_length_class_filter(self):
        res = self.engine.search("сверло 12 3D")
        self.assertEqual([p["sku"] for p in res["products"]], ["DRILL12-3D"])
        res = self.engine.search("сверло 12 5D")
        self.assertEqual([p["sku"] for p in res["products"]], ["DRILL12-5D"])

    def test_drill_tip_angle_filter(self):
        res = self.engine.search("сверло 12 135°")
        self.assertEqual([p["sku"] for p in res["products"]], ["DRILL12-3D"])
        self.assertAlmostEqual(res["parsed"]["angle_deg"], 135.0)

    def test_out_of_stock_fallback(self):
        res = self.engine.search("сверло 9 мм")
        self.assertEqual(res["products"][0]["sku"], "DRILL90")
        self.assertIn("под заказ", res.get("availability", ""))

    def test_mill_teeth_filter(self):
        res = self.engine.search("фреза концевая 10 мм 3 зуба")
        self.assertEqual([p["sku"] for p in res["products"]], ["MILL10-3F"])
        self.assertEqual(res["products"][0]["attrs"]["teeth"], 3)

    def test_tap_metric_thread(self):
        res = self.engine.search("метчик М10")
        self.assertEqual([p["sku"] for p in res["products"]], ["TAP-M10"])

    def test_holder_code(self):
        res = self.engine.search("державка PCLNR 2525M12")
        self.assertEqual(res["family"], "holder")
        self.assertEqual(res["products"][0]["sku"], "PCLNR2525M12")

    def test_collet_series_and_clamp(self):
        res = self.engine.search("цанга ER32 12")
        self.assertEqual(res["family"], "accessory")
        self.assertEqual([p["sku"] for p in res["products"]], ["ER32-12"])

    def test_nearest_diameter_fallback(self):
        res = self.engine.search("развертка 10 мм")
        self.assertEqual(res["level"], "аналог")
        self.assertEqual({p["sku"] for p in res["products"]}, {"REAM8", "REAM12"})
        self.assertTrue(any("ближайшие" in r for r in res["relaxations"]))

    def test_empty_ambiguous_query_asks_for_group(self):
        res = self.engine.search("8,5")
        self.assertEqual(res["total_found"], 0)
        self.assertTrue(res["follow_ups"])

    def test_unknown_query_asks_for_group(self):
        res = self.engine.search("купить")
        self.assertEqual(res["products"], [])
        self.assertTrue(res["follow_ups"])


class SiteOnlyEngine(ToolAdvisorEngine):
    """Заглушка без тяжёлой инициализации: проверяем маршрутизацию и формат ответа."""

    def __init__(self, site):
        import threading
        self._tls = threading.local()
        self._site_engine = site
        self.clarification_advisor = ClarificationAdvisor()

    def get_site_engine(self):
        return self._site_engine

    def _log_unrecognized(self, query):
        raise AssertionError("запрос не должен уходить в журнал нераспознанных")


class EngineRoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = SiteOnlyEngine(CatalogSearchEngine(ITEMS))

    def test_query_uses_site_catalog_without_llm(self):
        res = self.engine.process_query("метчик М10")
        self.assertEqual(res["decision"], "site_search")
        self.assertEqual(res["provider"], "site_catalog")
        self.assertEqual(res["llm_status"], "not_needed")
        self.assertFalse(res["llm_checked"])
        self.assertEqual(res["tool_result"]["products"][0]["sku"], "TAP-M10")
        self.assertIn("Поиск по каталогу qtool.ru", res["response_text"])
        self.assertIn("Метчик машинный M10x1.5", res["response_text"])

    def test_response_marks_out_of_stock(self):
        res = self.engine.process_query("сверло 9 мм")
        self.assertIn("под заказ", res["response_text"])

    def test_response_plural_and_article(self):
        res = self.engine.process_query("CNMG 1204")
        self.assertIn("Найдено: **2** позиции", res["response_text"])
        self.assertIn("**Артикул:** `CNMG120408`", res["response_text"])


if __name__ == "__main__":
    unittest.main()
