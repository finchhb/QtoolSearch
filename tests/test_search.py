"""Проверки гибридного поиска на синтетическом каталоге."""
import csv
import os
import tempfile
import unittest

from src.hybrid_search import HybridSearchEngine

FIELDS = [
    "sku", "code_1c", "name", "brand", "grade", "iso_group", "secondary_iso", "iso_code", "head",
    "insert_shape", "clearance_angle", "size_code", "chipbreaker", "operation", "coating", "thread_profile",
    "side", "hand", "family_code", "groove_width_mm", "corner_radius_mm", "pitch_value", "price",
    "price_on_request", "active", "currency", "source_site", "rinscom_url", "qtool_url", "in_both_stores",
    "stock", "category",
]


def row(**kw):
    base = {k: "" for k in FIELDS}
    base.update({"active": "Y", "currency": "RUB", "price": "1000", "price_on_request": "0", "stock": "5"})
    base.update(kw)
    return base


class HybridSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "catalog.csv")
        rows = [
            row(sku="CNMG120408-A", name="CNMG 120408 A", iso_group="P", iso_code="CNMG120408",
                insert_shape="C", clearance_angle="N", size_code="12", corner_radius_mm="0.8",
                chipbreaker="PM", operation="semi_finishing", source_site="qtool.ru", stock="3", category="turning_insert"),
            row(sku="CNMG120408-A", name="CNMG 120408 A", iso_group="P", iso_code="CNMG120408",
                insert_shape="C", clearance_angle="N", size_code="12", corner_radius_mm="0.8",
                chipbreaker="PM", operation="semi_finishing", source_site="rinscom.com", stock="4", category="turning_insert"),
            row(sku="WNMG080408-B", name="WNMG 080408 B", iso_group="M", iso_code="WNMG080408",
                insert_shape="W", clearance_angle="N", size_code="08", corner_radius_mm="0.8",
                chipbreaker="MR", operation="roughing", source_site="qtool.ru", stock="2", category="turning_insert"),
            row(sku="HLD-25", name="державка 25x25 для резцов", iso_group="", category="turning_holder",
                source_site="rinscom.com", stock="10"),
        ]
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        self.engine = HybridSearchEngine(catalog_path=self.path, cross_codes_path="", grades_path="")

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_match_by_geometry(self):
        res = self.engine.search(iso_group="P", insert_shape="C", size_code="12", limit=5)
        self.assertEqual(res["total_found"], 1)  # дубли склеены
        self.assertEqual(res["exact_found"], 1)
        self.assertFalse(res["relaxation_applied"])
        self.assertEqual(res["products"][0]["stock"], 7)  # остаток суммирован по двум магазинам

    def test_relaxation_reports_zero_exact(self):
        res = self.engine.search(iso_group="P", chipbreaker="ZZ", limit=5)
        self.assertTrue(res["relaxation_applied"])
        self.assertEqual(res["exact_found"], 0)
        self.assertGreater(res["total_found"], 0)

    def test_holder_search_finds_cyrillic_size(self):
        res = self.engine.search(category="turning_holder", text_query="державка 25х25", limit=5)
        self.assertEqual(res["query_category"], "turning_holder")
        self.assertTrue(any("25x25" in p["name"].lower() for p in res["products"]))


if __name__ == "__main__":
    unittest.main()
