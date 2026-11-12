"""Базовые проверки парсера ISO 1832 и справочника материалов."""
import unittest

from src import iso1832
from src.materials_mapping import detect_iso_group


class Iso1832Test(unittest.TestCase):
    def test_parse_standard_turning_code(self):
        p = iso1832.parse_code("CNMG120408")
        self.assertIsNotNone(p)
        self.assertEqual(p["shape"], "C")
        self.assertEqual(p["relief"], "N")
        self.assertEqual(p["size_code"], "12")
        self.assertEqual(p["corner_r"], 0.8)

    def test_detect_all_collects_geometry(self):
        d = iso1832.detect_all("нужна CNMG 120408 для чистовой")
        self.assertEqual(d["code"], "CNMG120408")
        self.assertEqual(d["shape"], "C")
        self.assertEqual(d["radius"], 0.8)

    def test_multiple_positions_are_split(self):
        parts = iso1832.split_positions("CNMG120408 и WNMG080408")
        self.assertEqual(len(parts), 2)


class MaterialsTest(unittest.TestCase):
    def test_builtin_stainless_is_m(self):
        self.assertEqual(detect_iso_group("12Х18Н10Т"), "M")

    def test_builtin_cast_iron_is_k(self):
        self.assertEqual(detect_iso_group("СЧ20"), "K")

    def test_explicit_iso_wins(self):
        self.assertEqual(detect_iso_group("ISO S титановый сплав"), "S")

    def test_hardness_over_45hrc_is_h(self):
        self.assertEqual(detect_iso_group("закалённая сталь 52 HRC"), "H")

    def test_unknown_material_is_empty(self):
        self.assertEqual(detect_iso_group("просто пластина"), "")


if __name__ == "__main__":
    unittest.main()
