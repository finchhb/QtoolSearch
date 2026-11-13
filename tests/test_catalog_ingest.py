"""Приём таблиц qtool.ru: классификация разделов, атрибуты, загрузка снимка."""
import csv
import os
import tempfile
import unittest

from src.site_catalog import FIELDS, classify, load_site_catalog, parse_attrs


class ClassifyTest(unittest.TestCase):
    def test_known_subsections(self):
        self.assertEqual(classify("Пластины", "Пластины для точения"), ("insert", "turning_insert"))
        self.assertEqual(classify("Пластины", "Пластины для фрез"), ("insert", "milling_insert"))
        self.assertEqual(classify("Свёрла", "Свёрла со сменными пластинами"), ("drill", "indexable_drill_body"))
        self.assertEqual(classify("Свёрла", "Твердосплавные свёрла"), ("drill", "solid_carbide_drill"))
        self.assertEqual(classify("Фрезы", "Фрезы концевые"), ("mill", "end_mill"))
        self.assertEqual(classify("Метчики", "Метчики метрические"), ("tap", "machine_tap"))
        self.assertEqual(classify("Державки", "Державки для наружного точения"), ("holder", "holder_external"))

    def test_case_and_yo_normalized(self):
        self.assertEqual(classify("СВЁРЛА", "ТВЕРДОСПЛАВНЫЕ СВЁРЛА"), ("drill", "solid_carbide_drill"))

    def test_name_refinements(self):
        self.assertEqual(classify("Оснастка", "Прочее", "Ключ шестигранный 3 мм"), ("accessory", "spare_part"))
        self.assertEqual(classify("Оснастка", "Прочее", "Винт крепёжный M4"), ("accessory", "spare_part"))
        self.assertEqual(classify("Оснастка", "Прочее", "Державка для сверл"), ("drill", "drill_holder"))
        self.assertEqual(classify("Оснастка", "Прочее", "Лезвие гратоснимателя"), ("countersink", "deburring_blade"))

    def test_accessory_section(self):
        fam, cat = classify("Оснастка", "Цанги")
        self.assertEqual(fam, "accessory")

    def test_unknown_section_is_quarantined(self):
        self.assertEqual(classify("Неведомый раздел", "Неведомая подгруппа"), ("other", "other"))


class ParseAttrsTest(unittest.TestCase):
    def test_turning_insert_from_code(self):
        a = parse_attrs("insert", "turning_insert", "CNMG 120408", "", {})
        self.assertEqual(a["iso_code"], "CNMG120408")
        self.assertEqual(a["insert_shape"], "C")
        self.assertEqual(str(a["size_code"]), "12")
        self.assertAlmostEqual(a["corner_radius_mm"], 0.8)

    def test_turning_insert_attrs_from_columns(self):
        cols = {
            "ATT_OBR_MATERIAL": "P",
            "ATT_VID_OBRABOTKI": "получистовая",
        }
        a = parse_attrs("insert", "turning_insert", "CNMG 120408", "", cols)
        self.assertEqual(a["iso_group"], "P")
        self.assertEqual(a["operation"], "semi_finishing")

    def test_solid_drill_diameter(self):
        a = parse_attrs("drill", "solid_carbide_drill", "Сверло твердосплавное 8,5 мм", "", {})
        self.assertAlmostEqual(a["diameter_mm"], 8.5)

    def test_drill_length_class_and_angle(self):
        a = parse_attrs("drill", "solid_carbide_drill",
                        "Сверло твердосплавное DR5D-085 8.5х61x10х103 135°", "", {})
        self.assertAlmostEqual(a["diameter_mm"], 8.5)
        self.assertAlmostEqual(a["cutting_length_mm"], 61.0)
        self.assertAlmostEqual(a["shank_mm"], 10.0)
        self.assertAlmostEqual(a["length_mm"], 103.0)
        self.assertEqual(a["ld_ratio"], 5)
        self.assertAlmostEqual(a["angle_deg"], 135.0)

    def test_end_mill_diameter_and_teeth(self):
        a = parse_attrs("mill", "end_mill", "Фреза концевая 10x25x75 3F", "", {})
        self.assertAlmostEqual(a["diameter_mm"], 10.0)
        self.assertEqual(a["teeth"], 3)

    def test_face_mill_bore_and_teeth(self):
        a = parse_attrs("mill", "face_mill", "Фреза торцевая BAP 400R 63-22-4T", "", {})
        self.assertAlmostEqual(a["diameter_mm"], 63.0)
        self.assertAlmostEqual(a["bore_mm"], 22.0)
        self.assertEqual(a["teeth"], 4)

    def test_tap_thread_and_pitch(self):
        a = parse_attrs("tap", "machine_tap", "Метчик машинный М10х1.5", "", {})
        self.assertTrue(a["thread"].startswith("M10"))
        self.assertAlmostEqual(a["pitch_mm"], 1.5)

    def test_holder_code_from_name(self):
        a = parse_attrs("holder", "holder_external",
                        "PCLNR2525M12 Державка для наружного точения", "", {})
        self.assertEqual(a["holder_code"], "PCLNR2525M12")

    def test_collet_series_and_clamp(self):
        a = parse_attrs("accessory", "collet", "Цанга ER32 12-11 мм", "", {})
        self.assertEqual(a["collet_series"], "ER32")
        self.assertEqual(a["clamp_range"], "12-11")


class LoadSnapshotTest(unittest.TestCase):
    def test_types_and_extra_json(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "catalog.csv")
        row = {k: "" for k in FIELDS}
        row.update({
            "id": "123", "sku": "CNMG120408", "name": "CNMG 120408", "brand": "Sandvik",
            "family": "insert", "category": "turning_insert", "stock": "5", "price": "1234,5",
            "currency": "RUB", "price_on_request": "0", "active": "1", "url": "https://qtool.ru/x",
            "iso_group": "P", "size_code": "12", "corner_radius_mm": "0.8", "teeth": "3",
            "extra_json": '{"chipbreaker": "PM", "hrc": 45}',
        })
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerow(row)

        items = load_site_catalog(path)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["stock"], 5)
        self.assertAlmostEqual(it["price"], 1234.5)
        self.assertTrue(it["active"])
        self.assertFalse(it["price_on_request"])
        self.assertEqual(str(it["attrs"]["size_code"]), "12")
        self.assertEqual(it["attrs"]["teeth"], 3)
        self.assertAlmostEqual(it["attrs"]["corner_radius_mm"], 0.8)
        self.assertEqual(it["attrs"]["chipbreaker"], "PM")
        self.assertEqual(it["attrs"]["hrc"], 45)

    def test_missing_file_is_empty(self):
        self.assertEqual(load_site_catalog("no_such_catalog.csv"), [])


if __name__ == "__main__":
    unittest.main()
