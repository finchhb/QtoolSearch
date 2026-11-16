"""Детерминированный поиск по каталогу qtool.ru на синтетическом наборе всех групп."""
import re
import unittest

from src.catalog_search import (
    FAMILY_KEYWORDS,
    CatalogSearchEngine,
    Query,
    clamp_accepts_hole,
    holder_code_from_text,
    holder_insert_compat,
    insert_compat_key,
    is_self_contained_query,
)
from src.clarification_advisor import ClarificationAdvisor
from src.engine import ToolAdvisorEngine


def item(family, category, name, sku=None, stock=10, price=1000.0, brand="TestBrand", **attrs):
    base = {
        "id": sku or name, "sku": sku or name, "name": name, "brand": brand,
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
    item("holder", "holder_external", "MCLNR2020K12 Державка для наружного точения",
         sku="MCLNR2020K12", holder_code="MCLNR2020K12"),
    item("holder", "holder_external", "SCLCR2525M12 Державка для наружного точения",
         sku="SCLCR2525M12", holder_code="SCLCR2525M12"),
    item("holder", "holder_internal", "S16Q-SCLCR-12-M-A Державка расточная",
         sku="S16Q-SCLCR-12", holder_code="S16Q-SCLCR-12-M-A"),
    item("holder", "holder_internal", "S20R-SDUCR11 Державка расточная",
         sku="S20R-SDUCR11", holder_code="S20R-SDUCR11"),
    item("mill", "face_mill", "BAP 400R 63-22-4T под APMT1604** корпусная фреза",
         sku="BAP400R-63", diameter_mm=63.0, bore_mm=22.0, teeth=4),
    item("mill", "face_mill", "BAP 400R 125-40-7T под APMT1604** корпусная фреза",
         sku="BAP400R-125", diameter_mm=125.0, bore_mm=40.0, teeth=7),
    item("mill", "face_mill", "ASRF12 50-22-4Т под SDMT1205** корпусная фреза",
         sku="ASRF12-50", diameter_mm=50.0, bore_mm=22.0, teeth=4),
    item("reamer", "machine_reamer", "Развертка машинная 8 H7", sku="REAM8",
         diameter_mm=8.0, tolerance="H7"),
    item("reamer", "machine_reamer", "Развертка машинная 12 H7", sku="REAM12",
         diameter_mm=12.0, tolerance="H7"),
    item("accessory", "collet", "Цанга ER32 12 мм", sku="ER32-12",
         collet_series="ER32", clamp_range="1-12"),
    item("accessory", "collet", "Цанга ER32 16 мм", sku="ER32-16",
         collet_series="ER32", clamp_range="2-16"),
    item("accessory", "tool_holder", "SBHA12-20 держатель осевого инструмента токарного станка",
         sku="SBHA12-20", stock=5, price=5000.0),
    item("accessory", "tool_holder", "SBHA20-32 держатель осевого инструмента токарного станка",
         sku="SBHA20-32", stock=3, price=5200.0),
    item("accessory", "machine_jaw",
         "250мм ГОСТ шаг 9мм кулачки обратные цельные. каленые (z) Qtool",
         sku="83088", stock=4, price=900.0),
    item("accessory", "machine_jaw",
         "К11-250 кулачки сборные базовые и накладные. каленые (z) Qtool",
         sku="83104", stock=6, price=1500.0),
    item("insert", "turning_insert", "DCGT 11T302 FL K10 для точения пластина",
         sku="DCGT11T302", iso_code="DCGT11T302", insert_shape="D", clearance_angle="C",
         size_code="11", corner_radius_mm=0.2, chipbreaker="FL", iso_group="K", grade="K10"),
    item("insert", "turning_insert", "DCGT 11T304 FN ALU AK10 для точения пластина",
         sku="DCGT11T304", iso_code="DCGT11T304", insert_shape="D", clearance_angle="C",
         size_code="11", corner_radius_mm=0.4, chipbreaker="FN", iso_group="K", grade="AK10"),
    item("insert", "turning_insert", "DCGT 070200 FN-F23 CTP2120 для точения пластина",
         sku="DCGT070200", iso_code="DCGT070200", insert_shape="D", clearance_angle="C",
         size_code="7", corner_radius_mm=0.2, chipbreaker="FN-F23", iso_group="K", grade="CTP2120"),
    item("accessory", "machine_jaw", "К11-400 кулачки обратные цельные. каленые (z) Qtool",
         sku="83091", stock=96, price=6786.0),
    item("accessory", "machine_jaw", "К11-400 кулачки прямые цельные. каленые (z) Qtool",
         sku="83101", stock=72, price=6786.0),
    item("accessory", "machine_jaw", "К11-400 кулачки сборные базовые и накладные. каленые (z) Qtool",
         sku="83106", stock=68, price=8174.0),
    item("accessory", "machine_jaw", "К11-400 кулачки сырые квадрат. цельные (z) Qtool",
         sku="83110", stock=84, price=6786.0),
    item("accessory", "machine_jaw", "К11-400 кулачки сырые обратные (ступеньки). цельные (z) Qtool",
         sku="83115", stock=23, price=6776.0),
    item("accessory", "machine_jaw", "К11-400 кулачки сырые прямые (ступеньки). цельные (z) Qtool",
         sku="83116", stock=4, price=6786.0),
    item("accessory", "accessory", "2/1 с лапкой переходная втулка (z) Qtool",
         sku="83366", stock=1937, price=184.13),
    item("accessory", "accessory", "3/2 с лапкой переходная втулка (z) Qtool",
         sku="83367", stock=1611, price=234.41),
    item("accessory", "accessory", "D16 2-50 мм барпуллер круг.хв. OLICNC", sku="67372", stock=3),
    item("accessory", "accessory", "S16 2-50 мм барпуллер квадр.хв. OLICNC", sku="67376", stock=4),
    item("accessory", "accessory", "S20 2-50 мм барпуллер квадр.хв. OLICNC", sku="67377", stock=4),
    item("accessory", "accessory", "S25 2-50 мм барпуллер квадр.хв. OLICNC", sku="67378", stock=4),
    # «пластина. Ромб. Размер 09. Радиус 02»: форма, размер и радиус словами
    item("insert", "turning_insert", "CCGT 09T302 AL K10 для точения пластина DESKAR",
         sku="CCGT09T302", brand="DESKAR", stock=1105, iso_code="CCGT09T302",
         insert_shape="C", clearance_angle="C", size_code=9, corner_radius_mm=0.2, grade="K10"),
    item("insert", "turning_insert", "CCMT 09T302 VM LF6018 для точения пластина DESKAR",
         sku="CCMT09T302", brand="DESKAR", stock=520, iso_code="CCMT09T302",
         insert_shape="C", clearance_angle="C", size_code=9, corner_radius_mm=0.2, grade="LF6018"),
    item("insert", "turning_insert", "CCGT 09T304 FN LF6018 для точения пластина DESKAR",
         sku="CCGT09T304", brand="DESKAR", stock=50, iso_code="CCGT09T304",
         insert_shape="C", clearance_angle="C", size_code=9, corner_radius_mm=0.4, grade="LF6018"),
    item("insert", "turning_insert", "CCGT 11T302 AL K10 для точения пластина DESKAR",
         sku="CCGT11T302", brand="DESKAR", stock=90, iso_code="CCGT11T302",
         insert_shape="C", clearance_angle="C", size_code=11, corner_radius_mm=0.2, grade="K10"),
    # державки под пластину C 09: правая 16×16 и расточная с хвостом Ø16
    item("holder", "holder_external", "SCLCR1616H09 для наружного точения державка DESKAR",
         sku="SCLCR1616H09", brand="DESKAR", stock=54, holder_code="SCLCR1616H09"),
    item("holder", "holder_external", "SCLCL1616H09 для наружного точения державка DESKAR",
         sku="SCLCL1616H09", brand="DESKAR", stock=7, holder_code="SCLCL1616H09"),
    item("holder", "holder_internal", "S16Q-SCLCR09 для внутреннего точения державка DESKAR",
         sku="S16Q-SCLCR09", brand="DESKAR", stock=203, holder_code="S16Q-SCLCR09"),
    # «патрон бт50 под велдон 25 длинной 100»
    item("accessory", "accessory", "BT50-SLN25-100 патрон weldon OLICNC", sku="123046",
         brand="OLICNC", stock=5),
    item("accessory", "accessory", "BT50-SLN25-100 оправка для корпусных сверл (z) Qtool",
         sku="83824", brand="Qtool", stock=4),
    item("accessory", "accessory", "BT50-SLN32-100 патрон weldon OLICNC", sku="123047",
         brand="OLICNC", stock=9),
    item("accessory", "accessory", "BT40-SLN25-100 патрон weldon OLICNC", sku="123056",
         brand="OLICNC", stock=6),
    # сверлильные патроны: в каталоге только оправки под них с конусами B16/B18
    item("accessory", "chuck", "KM4 B16 оправка для сверлильного патрона ГОСТ 2682-86 (z) Qtool",
         sku="83850", brand="Qtool", stock=350),
    item("accessory", "chuck", "KM3 B18 оправка для сверлильного патрона ГОСТ 2682-86 (z) Qtool",
         sku="83847", brand="Qtool", stock=500),
    # «набор прижимов под 14 паз»
    item("accessory", "accessory", "М12х1.75 (13.7) паз 14мМнабор клин. ступ. каленых прижимов 58шт. (z) Qtool",
         sku="83586", brand="Qtool", stock=177),
    item("accessory", "accessory",
         "Набор прижимов со шпильк. M12 для фрез. стола с паз. 14мм 58 шт кейс OLICNC",
         sku="67367", brand="OLICNC", stock=3),
    item("accessory", "accessory",
         "Набор прижим. со шпильк. M14 для фрез. стола паз. 16 мм 58 шт OLICNC",
         sku="67360", brand="OLICNC", stock=12),
]


class SelfContainedQueryTest(unittest.TestCase):
    """Сообщение с группой или кодом оснастки — новый запрос, а не уточнение к предыдущему."""

    def test_group_message_is_self_contained(self):
        for q in ("метчик М10", "державка 2020 под CNMG12", "фреза под пластину", "сверло 8,5 мм",
                  "расточная державка с хвостом 25 под cnmg12",
                  "держатель осевого инструмента под хвостовик 20"):
            self.assertTrue(is_self_contained_query(q), q)

    def test_code_message_is_self_contained(self):
        for q in ("mcbnr 2020", "MCBNR2020", "PCLNR 2525M12", "CNMG 120408"):
            self.assertTrue(is_self_contained_query(q), q)

    def test_explicit_size_message_is_self_contained(self):
        # «хвостовик 20 мм» после предыдущего запроса — новый инструмент, а не уточнение
        for q in ("хвостовик 20 мм", "сечение 25 на 25", "диаметр 8,5 мм", "хвостовиком 32 мм"):
            self.assertTrue(is_self_contained_query(q), q)

    def test_under_phrase_with_size_is_not_self_contained(self):
        # «под хвостовик 20» — уточнение к предыдущему запросу, хотя размер и назван
        for q in ("под хвостовик 20", "под сечение 25"):
            self.assertFalse(is_self_contained_query(q), q)

    def test_clarifications_are_not_self_contained(self):
        for q in ("12", "8,5", "25х25", "под CNMG12", "под APMT1604", "под пластину DNMG15",
                  "под dcmt пластину", "чистовая", "получистовая", "черновая", "наружная",
                  "внутренняя", "под сечение 25", "M10", "dcmt"):
            self.assertFalse(is_self_contained_query(q), q)

    def test_bare_short_insert_code_is_self_contained(self):
        # «DCGT 11» после запроса про держатель склеивался и повторял выдачу:
        # код с размером — самостоятельный запрос, уточнение — только «под <код>»
        for q in ("cnmg12", "DCGT 11", "dcgt09", "CCMT 09T304"):
            self.assertTrue(is_self_contained_query(q), q)

    def test_unknown_designation_is_self_contained(self):
        # «MTA2 велдон 10» после «расточная s20 под dcmt» склеивался и повторял выдачу:
        # незнакомое обозначение — новый запрос, даже если сообщение короткое
        for q in ("MTA2 велдон 10", "SK40", "BT40", "HSK63", "ER32", "MK2",
                  "DIN 69871 40", "конус морзе 2", "SBHA32 20", "расточная s20 под dcmt"):
            self.assertTrue(is_self_contained_query(q), q)

    def test_unknown_word_next_to_known_code_is_self_contained(self):
        # известный код не делает уточнением сообщение со своим словом
        for q in ("велдон под cnmg12", "MTA2 под 20"):
            self.assertTrue(is_self_contained_query(q), q)

    def test_jaw_query_is_not_a_clarification(self):
        # «кулачки…» после запроса про держатели раньше склеивалось и повторяло выдачу
        self.assertTrue(is_self_contained_query("кулачки каленые к11 шаг 5"))


class FamilyTopicDriftTest(unittest.TestCase):
    """Каждое слово-группа из FAMILY_KEYWORDS — самостоятельный запрос, а не уточнение.

    Ловит дрейф: раньше список тем был отдельным и новые группы («кулачки») в него не попадали.
    """

    def test_every_family_word_starts_new_query(self):
        for _, pattern in FAMILY_KEYWORDS:
            for stem in re.findall(r"[А-Яа-яЁё]{2,}", re.sub(r"\[[^\]]*\]", " ", pattern)):
                self.assertTrue(is_self_contained_query(stem.lower() + "ы"), (pattern, stem))


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

    def test_holder_fits_insert_by_section_and_type(self):
        res = self.engine.search("державка 2525 под cnmg1204")
        skus = {p["sku"] for p in res["products"]}
        self.assertEqual(res["family"], "holder")
        self.assertIn("PCLNR2525M12", skus)
        self.assertNotIn("MCLNR2020K12", skus)   # другое сечение
        self.assertNotIn("SCLCR2525M12", skus)   # задний угол C — под CCMT, не CNMG
        self.assertIn("под пластину: CNMG1204", res["chips"])

    def test_holder_fits_insert_without_section(self):
        res = self.engine.search("державка под cnmg1204")
        skus = {p["sku"] for p in res["products"]}
        self.assertIn("PCLNR2525M12", skus)
        self.assertIn("MCLNR2020K12", skus)
        self.assertNotIn("SCLCR2525M12", skus)

    def test_mill_body_fits_insert_nearest_diameter(self):
        res = self.engine.search("фреза 120 под APMT")
        self.assertEqual(res["family"], "mill")
        self.assertEqual(res["level"], "аналог")
        self.assertEqual([p["sku"] for p in res["products"]], ["BAP400R-125"])
        self.assertTrue(any("ближайший" in r for r in res["relaxations"]))

    def test_mill_body_fits_insert_prefix(self):
        res = self.engine.search("фреза под APMT1604")
        skus = {p["sku"] for p in res["products"]}
        self.assertEqual(skus, {"BAP400R-63", "BAP400R-125"})

    def test_holder_under_insert_phrase(self):
        res = self.engine.search("державка 2525 под пластину CNMG1204")
        self.assertEqual(res["family"], "holder")
        self.assertEqual(res["compatible_insert"], "CNMG1204")
        skus = {p["sku"] for p in res["products"]}
        self.assertIn("PCLNR2525M12", skus)
        self.assertNotIn("SCLCR2525M12", skus)

    def test_mill_body_under_insert_phrase(self):
        res = self.engine.search("корпус фрезы под пластину APMT1604")
        self.assertEqual(res["family"], "mill")
        self.assertEqual({p["sku"] for p in res["products"]}, {"BAP400R-63", "BAP400R-125"})

    def test_boring_holder_dashed_code(self):
        info = holder_insert_compat("S16Q-SCLCR-12-M-A")
        self.assertEqual((info["shape"], info["clearance"], info["size"]), ("C", "C", "12"))
        res = self.engine.search("расточная державка под пластину CCMT1204")
        self.assertIn("S16Q-SCLCR-12", {p["sku"] for p in res["products"]})
        self.assertNotIn("PCLNR2525M12", {p["sku"] for p in res["products"]})  # задний угол N

    def test_compat_without_group_shows_compatible_tools(self):
        res = self.engine.search("под пластину CNMG1204")
        self.assertIsNone(res["family"])
        self.assertEqual(res["level"], "подбор")
        self.assertEqual({p["sku"] for p in res["products"]}, {"PCLNR2525M12", "MCLNR2020K12"})

    def test_compat_phrase_without_code_asks_code(self):
        res = self.engine.search("фреза под пластину")
        self.assertEqual(res["family"], "mill")
        self.assertIsNone(res.get("compatible_insert"))
        self.assertEqual(res["products"], [])
        self.assertTrue(any("код пластины" in tip for tip in res["follow_ups"]))

    def test_compat_cyrillic_insert_prefix(self):
        res = self.engine.search("фреза под пластину РПМТ1204")
        self.assertEqual(res["family"], "mill")
        self.assertEqual(res["compatible_insert"], "RPMT1204")

    def test_insert_for_holder_reverse(self):
        res = self.engine.search("пластина под державку MCLNR2020K12")
        self.assertEqual(res["family"], "insert")
        self.assertEqual(res["fits_holder"], "MCLNR2020K12")
        self.assertEqual({p["sku"] for p in res["products"]}, {"CNMG120408", "CNMG120412"})


    def test_insert_for_holder_without_code_asks_code(self):
        res = self.engine.search("пластина под державку")
        self.assertEqual(res["level"], "уточните державку")
        self.assertEqual(res["products"], [])

    def test_insert_for_holder_without_insert_size_asks_code(self):
        # MCLNR2525: 2525 — сечение хвостовика; размер пластины не задан
        res = self.engine.search("пластина под державку MCLNR2525")
        self.assertEqual(res["level"], "уточните державку")
        self.assertEqual(res["products"], [])

    def test_insert_code_with_holder_word_keeps_code_search(self):
        res = self.engine.search("пластина CNMG120408 для державки")
        self.assertEqual(res["insert_code"], "CNMG120408")
        self.assertEqual([p["sku"] for p in res["products"]], ["CNMG120408"])

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


class HolderCodeParsingTest(unittest.TestCase):
    """Пятибуквенный код державки не должен распознаваться как код пластины."""

    def test_five_letter_holder_code_is_not_insert(self):
        q = Query("mtjnr2525")
        self.assertEqual(q.family, "holder")
        self.assertEqual(q.holder_code, "MTJNR2525")
        self.assertIsNone(q.insert_code)

    def test_spaced_holder_code_keeps_insert_size_out_of_thread(self):
        q = Query("MTJNR 2525 M16")
        self.assertEqual(q.family, "holder")
        self.assertEqual(q.holder_code, "MTJNR2525M16")
        self.assertIsNone(q.thread)

    def test_insert_code_is_still_insert(self):
        q = Query("CNMG 12 04 08")
        self.assertEqual(q.family, "insert")
        self.assertEqual(q.insert_code, "CNMG120408")

    def test_short_series_is_not_a_holder_code(self):
        # «SBHA32» — серия держателей осевого инструмента, а не код державки ISO 5608
        self.assertIsNone(holder_code_from_text("SBHA32"))
        self.assertIsNone(holder_code_from_text("SBHA12-20"))
        q = Query("sbha32")
        self.assertIsNone(q.holder_code)
        self.assertNotEqual(q.family, "holder")

    def test_partial_iso_code_is_still_a_holder_code(self):
        # сечение без класса длины и размера пластины — допустимая запись, не серия оснастки
        self.assertEqual(holder_code_from_text("mcbnr 2020"), "MCBNR2020")
        self.assertEqual(holder_code_from_text("mtjnr 2525"), "MTJNR2525")


class HolderSubgroupTest(unittest.TestCase):
    """Слова запроса задают подгруппу державки: «расточная» — внутренние, «хвост 25» — диаметр."""

    @classmethod
    def setUpClass(cls):
        cls.engine = CatalogSearchEngine(ITEMS)

    def test_boring_word_selects_internal_holders(self):
        q = Query("расточная державка под пластину CCMT1204")
        self.assertEqual(q.category_hints, ["holder_internal"])

    def test_round_shank_query_returns_boring_holder(self):
        res = self.engine.search("расточная державка с хвостом 16 под CCMT1204")
        self.assertEqual([p["sku"] for p in res["products"]], ["S16Q-SCLCR-12"])
        self.assertIn("тип: расточная", res["chips"])
        self.assertIn("хвост: Ø16 мм", res["chips"])

    def test_square_section_query_skips_boring_bars(self):
        res = self.engine.search("державка 2020 под CNMG1204")
        self.assertEqual({p["category"] for p in res["products"]}, {"holder_external"})
        self.assertIn("сечение: 20×20 мм", res["chips"])

    def test_shank_phrase_forms(self):
        for text in ("державка хв. 25", "державка с хвостом 25", "державка хвостовиком 25"):
            self.assertEqual(Query(text).attrs.get("shank_mm"), 25.0, text)

    def test_boring_bar_exposes_shank_diameter_not_section(self):
        res = self.engine.search("расточная державка под пластину CCMT1204")
        attrs = res["products"][0]["attrs"]
        self.assertEqual(attrs.get("shank_diameter_mm"), 16.0)
        self.assertNotIn("shank_section", attrs)
        self.assertEqual(res["category_hints"], ["holder_internal"])

    def test_boring_follow_up_asks_for_shank_diameter(self):
        res = self.engine.search("расточная державка 25")
        tips = " ".join(res["follow_ups"])
        self.assertIn("диаметр хвоста", tips)
        self.assertNotIn("сечение державки", tips)

    def test_plate_word_after_under_insert_keeps_holder_family(self):
        # «под dcmt пластину»: оставшееся слово «пластину» не должно уводить запрос в пластины
        q = Query("державка расточная, S20, под dcmt пластину")
        self.assertEqual(q.family, "holder")
        self.assertEqual(q.compat_insert, "DCMT")
        self.assertEqual(q.category_hints, ["holder_internal"])
        self.assertEqual(q.attrs.get("shank_mm"), 20.0)

    def test_shank_letter_prefix_is_not_a_holder_code(self):
        # S20 — обозначение хвоста, а не код державки: чип «код: S20» вводит в заблуждение
        q = Query("державка расточная, S20, под dcmt пластину")
        self.assertIsNone(q.holder_code)

    def test_dcmt_boring_query_returns_shank_20(self):
        res = self.engine.search("державка расточная, S20, под dcmt пластину")
        self.assertEqual([p["sku"] for p in res["products"]], ["S20R-SDUCR11"])
        self.assertIn("хвост: Ø20 мм", res["chips"])
        self.assertNotIn("код: S20", res["chips"])


class ToolHolderTest(unittest.TestCase):
    """«держатель осевого инструмента» — группа оснастки, а не пластины из предыдущего запроса."""

    @classmethod
    def setUpClass(cls):
        cls.engine = CatalogSearchEngine(ITEMS)

    def test_holder_word_selects_accessory_tool_holder(self):
        q = Query("держатель осевого инструмента под хвостовик 20")
        self.assertEqual(q.family, "accessory")
        self.assertEqual(q.category_hints, ["tool_holder"])
        self.assertTrue(is_self_contained_query(q.text))

    def test_shank_phrase_means_clamped_tool_shank(self):
        # «под хвостовик 20» — хвост зажимаемого инструмента, а не хвостовик самого держателя
        q = Query("держатель осевого инструмента под хвостовик 20")
        self.assertEqual(q.attrs.get("clamp_mm"), 20.0)
        self.assertNotIn("shank_mm", q.attrs)

    def test_query_returns_tool_holders_for_20_shank(self):
        res = self.engine.search("держатель осевого инструмента под хвостовик 20")
        self.assertEqual(res["family"], "accessory")
        self.assertEqual([p["sku"] for p in res["products"]], ["SBHA12-20"])
        self.assertIn("тип: держатель осевого инструмента", res["chips"])
        self.assertIn("под хвостовик: 20 мм", res["chips"])
        self.assertEqual(res["products"][0]["attrs"].get("clamp_mm"), 20.0)

    def test_sbha_article_is_parsed_as_tool_holder(self):
        q = Query("SBHA12-20")
        self.assertEqual(q.family, "accessory")
        self.assertEqual(q.category_hints, ["tool_holder"])
        self.assertEqual((q.attrs.get("shank_mm"), q.attrs.get("clamp_mm")), (12.0, 20.0))
        self.assertIsNone(q.holder_code)

    def test_tap_holder_stays_in_taps(self):
        self.assertEqual(Query("держатель для метчика М10").family, "tap")

    def test_spaced_sbha_article_is_parsed_as_tool_holder(self):
        # «sbha12 20» — та же артикул-запись, что «SBHA12-20»
        q = Query("sbha12 20")
        self.assertEqual(q.family, "accessory")
        self.assertEqual(q.category_hints, ["tool_holder"])
        self.assertEqual((q.attrs.get("shank_mm"), q.attrs.get("clamp_mm")), (12.0, 20.0))
        res = self.engine.search("sbha12 20")
        self.assertEqual([p["sku"] for p in res["products"]], ["SBHA12-20"])

    def test_sbha_series_without_article_size(self):
        # «sbha20» — серия по хвостовику 20, а не код державки и не 0 результатов
        q = Query("sbha20")
        self.assertEqual(q.family, "accessory")
        self.assertEqual(q.category_hints, ["tool_holder"])
        self.assertIsNone(q.holder_code)
        self.assertEqual(q.attrs.get("shank_mm"), 20.0)
        res = self.engine.search("sbha20")
        self.assertEqual([p["sku"] for p in res["products"]], ["SBHA20-32"])

    def test_reversed_under_shank_phrase_filters(self):
        # «под 20 хвостовик» — размер перед словом; фильтр тот же, что у «под хвостовик 20»
        res = self.engine.search("держатель осевого инструмента под 20 хвостовик")
        self.assertEqual([p["sku"] for p in res["products"]], ["SBHA12-20"])
        self.assertIn("под хвостовик: 20 мм", res["chips"])
        self.assertNotIn("Укажите диаметр хвостовика", " ".join(res["follow_ups"]))


class MachineJawTest(unittest.TestCase):
    """«кулачки» — подгруппа оснастки; «3-х кулачковый патрон» — это сам патрон."""

    @classmethod
    def setUpClass(cls):
        cls.engine = CatalogSearchEngine(ITEMS)

    def test_jaw_word_selects_machine_jaws(self):
        q = Query("кулачки каленые к11")
        self.assertEqual(q.family, "accessory")
        self.assertEqual(q.category_hints, ["machine_jaw"])

    def test_chuck_query_is_not_narrowed_to_jaws(self):
        q = Query("патрон 3-х кулачковый 100")
        self.assertEqual(q.family, "accessory")
        self.assertNotIn("machine_jaw", q.category_hints)

    def test_jaw_search_returns_jaws_only(self):
        res = self.engine.search("кулачки каленые")
        self.assertEqual({p["category"] for p in res["products"]}, {"machine_jaw"})
        self.assertIn("тип: кулачки", res["chips"])

    def test_jaw_series_selects_only_that_chuck_size(self):
        # «кулачки к11-400» — кулачки именно на патрон К11-400, а не на К11-250
        res = self.engine.search("кулачки к11-400")
        skus = {p["sku"] for p in res["products"]}
        self.assertEqual(skus, {"83091", "83101", "83106", "83110", "83115", "83116"})
        self.assertEqual({p["category"] for p in res["products"]}, {"machine_jaw"})
        self.assertIn("серия патрона: K11-400", res["chips"])

    def test_jaw_series_cyrillic_ka_matches(self):
        # серия пишется и кириллической «К», и латинской «K»
        for q in ("кулачки к11-250", "кулачки K11-250"):
            res = self.engine.search(q)
            self.assertEqual([p["sku"] for p in res["products"]], ["83104"], q)


class ShortInsertCodeTest(unittest.TestCase):
    """Короткая запись пластины: «DCGT 11» — префикс и двузначный размер."""

    def test_prefix_and_size_are_parsed(self):
        q = Query("DCGT 11")
        self.assertEqual(q.family, "insert")
        self.assertEqual(q.insert_code, "DCGT11")
        self.assertEqual(q.attrs["insert_prefix"], "DCGT")
        self.assertEqual(q.attrs["size_code"], "11")

    def test_short_code_search_returns_that_size(self):
        res = CatalogSearchEngine(ITEMS).search("DCGT 11")
        self.assertEqual(res["family"], "insert")
        self.assertEqual({p["sku"] for p in res["products"]}, {"DCGT11T302", "DCGT11T304"})
        self.assertIn("пластина: DCGT 11", res["chips"])

    def test_short_code_with_chipbreaker_and_grade(self):
        # «DCGT 11T302 FL K10»: полное обозначение отсекает соседние размеры, марка — соседние сплавы
        q = Query("DCGT 11T302 FL K10 для точения пластина")
        self.assertEqual(q.insert_code, "DCGT11")
        self.assertEqual(q.attrs["iso_tail"], "T302")
        self.assertEqual(q.attrs["grade"], "K10")
        res = CatalogSearchEngine(ITEMS).search("DCGT 11T302 FL K10 для точения пластина")
        self.assertEqual([p["sku"] for p in res["products"]], ["DCGT11T302"])

    def test_grade_in_name_is_a_whole_token(self):
        # «AK10» не должен считаться маркой «K10»
        res = CatalogSearchEngine(ITEMS).search("DCGT 11 FL K10")
        self.assertEqual([p["sku"] for p in res["products"]], ["DCGT11T302"])

    def test_second_letter_is_clearance_angle(self):
        # «SK40», «HSK63», «ER32» — не пластины: вторая буква не задний угол
        for q in ("SK40", "HSK63", "ER32", "MTA2"):
            self.assertFalse(Query(q).insert_code, q)


class MorseBushingTest(unittest.TestCase):
    """Переходная втулка: «морзе2 на морзе 1» = каталог «2/1 с лапкой переходная втулка»."""

    @classmethod
    def setUpClass(cls):
        cls.engine = CatalogSearchEngine(ITEMS)

    def test_morse_phrase_is_parsed(self):
        q = Query("втулка переходная морзе2 на морзе 1 с лапкой")
        self.assertEqual(q.family, "accessory")
        self.assertEqual((q.attrs["morse_from"], q.attrs["morse_to"]), (2, 1))
        self.assertTrue(q.attrs["with_tang"])

    def test_morse_phrase_finds_bushing(self):
        res = self.engine.search("втулка переходная морзе2 на морзе 1 с лапкой")
        self.assertEqual([p["sku"] for p in res["products"]], ["83366"])
        self.assertIn("переход: Морзе 2 → Морзе 1", res["chips"])
        self.assertIn("с лапкой", res["chips"])

    def test_bare_pair_is_parsed(self):
        q = Query("втулка 3/2 с лапкой")
        self.assertEqual((q.attrs["morse_from"], q.attrs["morse_to"]), (3, 2))
        res = self.engine.search("втулка 3/2 с лапкой")
        self.assertEqual([p["sku"] for p in res["products"]], ["83367"])


class BarPullerTest(unittest.TestCase):
    """«барпулер» = «барпуллер»; «2525» — квадратный хвост 25×25, в каталоге «S25». """

    @classmethod
    def setUpClass(cls):
        cls.engine = CatalogSearchEngine(ITEMS)

    def test_alias_and_square_shank_are_parsed(self):
        q = Query("барпулер 2525")
        self.assertEqual(q.family, "accessory")
        self.assertTrue(q.attrs["bar_puller"])
        self.assertEqual(q.attrs["bar_shank_mm"], 25)

    def test_search_returns_barpullers_only(self):
        for q in ("барпулер 2525", "барпуллер 2525"):
            res = self.engine.search(q)
            self.assertTrue(res["products"], q)
            self.assertTrue(all("барпуллер" in p["name"].lower() for p in res["products"]), q)
            self.assertEqual({p["sku"] for p in res["products"]}, {"67378"}, q)
            self.assertIn("квадрат: 25×25 мм", res["chips"], q)

    def test_plain_barpuller_search_returns_whole_group(self):
        res = self.engine.search("барпулер")
        self.assertEqual({p["sku"] for p in res["products"]}, {"67372", "67376", "67377", "67378"})


class ResultOrderTest(unittest.TestCase):
    """Порядок в ответе: бренд по приоритету ZZKLT, DESKAR, OLICNC, ZEGYO, внутри — остаток."""

    ITEMS = [
        item("drill", "solid_carbide_drill", "Сверло твердосплавное 8,5 ZZKLT-5",
             sku="ORD-Z1", stock=5, brand="ZZKLT", diameter_mm=8.5),
        item("drill", "solid_carbide_drill", "Сверло твердосплавное 8,5 ZZKLT-20",
             sku="ORD-Z2", stock=20, brand="ZZKLT", diameter_mm=8.5),
        item("drill", "solid_carbide_drill", "Сверло твердосплавное 8,5 DESKAR",
             sku="ORD-D", stock=50, brand="DESKAR", diameter_mm=8.5),
        item("drill", "solid_carbide_drill", "Сверло твердосплавное 8,5 OLICNC",
             sku="ORD-O", stock=40, brand="OLICNC", diameter_mm=8.5),
        item("drill", "solid_carbide_drill", "Сверло твердосплавное 8,5 ZEGYO",
             sku="ORD-G", stock=30, brand="ZEGYO", diameter_mm=8.5),
        item("drill", "solid_carbide_drill", "Сверло твердосплавное 8,5 Qtool",
             sku="ORD-Q", stock=100, brand="Qtool", diameter_mm=8.5),
    ]

    def test_brand_then_stock(self):
        res = CatalogSearchEngine(self.ITEMS).search("сверло 8,5 мм", limit=10)
        self.assertEqual([p["sku"] for p in res["products"]],
                         ["ORD-Z2", "ORD-Z1", "ORD-D", "ORD-O", "ORD-G", "ORD-Q"])


class ClampHoleTest(unittest.TestCase):
    """R1: первая буква кода державки соответствует четвёртой букве пластины."""

    def test_no_hole_clamp(self):
        for hole in "NRF":
            self.assertTrue(clamp_accepts_hole("C", hole), hole)
        for hole in "GAMTWQU":
            self.assertFalse(clamp_accepts_hole("C", hole), hole)

    def test_cylindrical_clamps(self):
        for clamp in "DMP":
            for hole in "AMG":
                self.assertTrue(clamp_accepts_hole(clamp, hole), (clamp, hole))
            for hole in "NRTWQUF":
                self.assertFalse(clamp_accepts_hole(clamp, hole), (clamp, hole))

    def test_conical_clamp(self):
        for hole in "TWQU":
            self.assertTrue(clamp_accepts_hole("S", hole), hole)
        for hole in "NAMG":
            self.assertFalse(clamp_accepts_hole("S", hole), hole)

    def test_unknown_side_is_not_restricted(self):
        self.assertTrue(clamp_accepts_hole("C", None))
        self.assertTrue(clamp_accepts_hole(None, "G"))
        self.assertTrue(clamp_accepts_hole("X", "G"))

    def test_parsed_holder_and_insert(self):
        cnmg_hole = insert_compat_key("CNMG1204")["hole"]
        self.assertTrue(clamp_accepts_hole(holder_insert_compat("PCLNR2525M12")["clamp"], cnmg_hole))
        self.assertFalse(clamp_accepts_hole(holder_insert_compat("SCLCR2525M12")["clamp"], cnmg_hole))
        self.assertTrue(
            clamp_accepts_hole(holder_insert_compat("SCLCR2525M12")["clamp"],
                               insert_compat_key("CCMT1204")["hole"])
        )


# Одинаковые форма, задний угол и размер, разные отверстия: T - коническое, G - цилиндрическое.
R1_ITEMS = [
    item("holder", "holder_external", "SCLCR2525M12 Державка для наружного точения",
         sku="SCLCR2525M12", holder_code="SCLCR2525M12"),
    item("insert", "turning_insert", "CCMT 120404 MF 4305", sku="CCMT120404",
         iso_code="CCMT120404", insert_shape="C", clearance_angle="C", size_code=12,
         corner_radius_mm=0.4, chipbreaker="MF", iso_group="P", operation="finishing", grade="4305"),
    item("insert", "turning_insert", "CCMG 120408 MF 4305", sku="CCMG120408",
         iso_code="CCMG120408", insert_shape="C", clearance_angle="C", size_code=12,
         corner_radius_mm=0.8, chipbreaker="MF", iso_group="P", operation="finishing", grade="4305"),
]


class R1SearchTest(unittest.TestCase):
    """R1 на выдаче: державка с зажимом S не получает пластину с цилиндрическим отверстием."""

    @classmethod
    def setUpClass(cls):
        cls.engine = CatalogSearchEngine(R1_ITEMS)

    def test_reverse_keeps_conical_hole_only(self):
        res = self.engine.search("пластина под державку SCLCR2525M12")
        self.assertEqual({p["sku"] for p in res["products"]}, {"CCMT120404"})

    def test_forward_keeps_conical_hole_only(self):
        fits = {p["sku"] for p in self.engine.search("державка под CCMT1204")["products"]}
        self.assertIn("SCLCR2525M12", fits)
        no_fit = {p["sku"] for p in self.engine.search("державка под CCMG1204")["products"]}
        self.assertNotIn("SCLCR2525M12", no_fit)


class PlateSpecTest(unittest.TestCase):
    """«пластина. Ромб. Размер 09. Радиус 02»: пластина описана словами, без кода."""

    @classmethod
    def setUpClass(cls):
        cls.engine = CatalogSearchEngine(ITEMS)

    def test_shape_size_radius_are_parsed(self):
        q = Query("пластина. Ромб. Размер 09.радиус 02")
        self.assertEqual(q.family, "insert")
        self.assertEqual(q.attrs.get("plate_shape"), "C")
        self.assertEqual(q.attrs.get("plate_size"), "09")
        self.assertEqual(q.attrs.get("corner_radius_mm"), 0.2)

    def test_search_returns_that_shape_size_and_radius(self):
        res = self.engine.search("пластина. Ромб. Размер 09.радиус 02")
        skus = {p["sku"] for p in res["products"]}
        self.assertIn("CCGT09T302", skus)
        self.assertIn("CCMT09T302", skus)
        self.assertNotIn("CCGT09T304", skus)   # радиус 0,4
        self.assertNotIn("CCGT11T302", skus)   # размер 11
        self.assertEqual(res["level"], "точное")

    def test_chips_spell_out_the_spec(self):
        chips = self.engine.search("пластина. Ромб. Размер 09.радиус 02")["chips"]
        self.assertIn("форма: ромб", chips)
        self.assertIn("размер: 09", chips)
        self.assertIn("радиус: 0,2 мм", chips)


class HolderFromPlateSpecTest(unittest.TestCase):
    """«державка 1616 под пластина Правая. Ромб. Размер 09»: код пластины не назван."""

    @classmethod
    def setUpClass(cls):
        cls.engine = CatalogSearchEngine(ITEMS)

    def test_shape_and_size_become_compat_request(self):
        q = Query("державка 1616 под пластина Правая. Ромб. Размер 09")
        self.assertTrue(q.compat_requested)
        self.assertEqual((q.compat_shape, q.compat_size, q.compat_hand), ("C", "09", "R"))

    def test_right_hand_square_section(self):
        res = self.engine.search("державка 1616 под пластина Правая. Ромб. Размер 09")
        self.assertEqual([p["sku"] for p in res["products"]], ["SCLCR1616H09"])
        self.assertEqual(res["level"], "точное")

    def test_left_hand_square_section(self):
        res = self.engine.search("державка 1616 под пластина Левая. Ромб. Размер 09")
        self.assertEqual([p["sku"] for p in res["products"]], ["SCLCL1616H09"])

    def test_bare_shank_means_round_diameter(self):
        # «хвост 16» — круглый хвостовик Ø16, квадрат 16×16 не подходит
        q = Query("державка хвост 16 под пластина Правая. Ромб. Размер 09")
        self.assertTrue(q.shank_round)
        res = self.engine.search("державка хвост 16 под пластина Правая. Ромб. Размер 09")
        self.assertEqual([p["sku"] for p in res["products"]], ["S16Q-SCLCR09"])
        self.assertIn("хвост: Ø16 мм", res["chips"])


class ChuckAccessoryTest(unittest.TestCase):
    """Патроны и оправки — изделия оснастки, а не свёрла."""

    @classmethod
    def setUpClass(cls):
        cls.engine = CatalogSearchEngine(ITEMS)

    def test_patron_and_prizhim_are_accessories(self):
        for text in ("сверлильный самозажимной патрон 1-16мм",
                     "набор прижимов под 14 паз",
                     "vdi 30 сверлильный патрон"):
            self.assertEqual(Query(text).family, "accessory", text)

    def test_taper_weldon_diameter_length(self):
        q = Query("патрон бт50 под велдон 25 длинной 100")
        self.assertEqual(q.attrs.get("taper"), "BT50")
        self.assertTrue(q.attrs.get("weldon"))
        self.assertEqual(q.attrs.get("tool_d_mm"), 25)
        self.assertEqual(q.attrs.get("tool_l_mm"), 100)
        res = self.engine.search("патрон бт50 под велдон 25 длинной 100")
        self.assertEqual({p["sku"] for p in res["products"]}, {"123046", "83824"})

    def test_chuck_taper_selects_arbor(self):
        res = self.engine.search("сверлильный самозажимной патрон 1-16мм. B16")
        self.assertEqual([p["sku"] for p in res["products"]], ["83850"])
        self.assertIn("конус патрона: B16", res["chips"])

    def test_vdi_system_is_parsed(self):
        self.assertEqual(Query("vdi 30 сверлильный патрон").attrs.get("chuck_system"), "VDI30")


class ClampSetSlotTest(unittest.TestCase):
    """«набор прижимов под 14 паз»: паз стола берётся из названия позиции."""

    @classmethod
    def setUpClass(cls):
        cls.engine = CatalogSearchEngine(ITEMS)

    def test_slot_is_parsed(self):
        q = Query("набор прижимов под 14 паз")
        self.assertTrue(q.attrs.get("clamp_set"))
        self.assertEqual(q.attrs.get("slot_mm"), 14)

    def test_search_returns_only_that_slot(self):
        res = self.engine.search("набор прижимов под 14 паз")
        self.assertEqual({p["sku"] for p in res["products"]}, {"83586", "67367"})
        self.assertIn("паз: 14 мм", res["chips"])


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
