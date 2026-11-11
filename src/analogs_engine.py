"""
src/analogs_engine.py - Движок сопоставления кросс-кодов и поиска аналогов
"""
import csv
import os
import re
from typing import Dict, List, Optional


class AnalogsEngine:
    def __init__(self, cross_codes_path="data/cross_codes.csv", grades_path="data/grades.csv", chipbreakers_path="data/chipbreakers_cross.csv"):
        self.cross_codes: List[Dict] = []
        self.grades: Dict[str, Dict] = {}
        self.chipbreakers: List[Dict] = []
        self._load_data(cross_codes_path, grades_path, chipbreakers_path)

    def _load_data(self, cross_codes_path, grades_path, chipbreakers_path):
        if os.path.exists(cross_codes_path):
            with open(cross_codes_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                self.cross_codes = list(reader)

        if os.path.exists(grades_path):
            with open(grades_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    g_key = (row.get("grade") or "").strip().upper()
                    if g_key:
                        self.grades[g_key] = row

        if os.path.exists(chipbreakers_path):
            with open(chipbreakers_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                self.chipbreakers = list(reader)

    def extract_grade_and_sku(self, text: str) -> Dict[str, str]:
        """Извлечение марки твердого сплава и артикула из свободного текста запроса"""
        upper = text.upper()
        detected_grade = ""
        detected_sku = ""

        # Собираем все известные марки из grades.csv и cross_codes.csv
        all_known_grades = set(self.grades.keys())
        brand_keys = ["sandvik", "iscar", "korloy", "walter", "deskar", "mitsubishi", "zcc_ct", "kennametal", "seco", "kyocera"]
        for row in self.cross_codes:
            for bk in brand_keys:
                val = (row.get(bk) or "").strip().upper()
                if val:
                    all_known_grades.add(val)

        sorted_grades = sorted(all_known_grades, key=len, reverse=True)
        for g in sorted_grades:
            pattern = r"(?<![A-Z0-9])" + re.escape(g) + r"(?![A-Z0-9])"
            if re.search(pattern, upper):
                detected_grade = g
                break

        m_sku = re.search(r"\b[CWTDSVR][NCTB][MG]\s*\d{6}(?:-[A-Z0-9]+)*\b", upper)
        if m_sku:
            detected_sku = m_sku.group(0).replace(" ", "")

        return {
            "grade": detected_grade,
            "sku": detected_sku,
        }

    def find_grade_cross(self, source_grade: str, target_brand: Optional[str] = None) -> List[Dict]:
        """Поиск аналогов марки твердого сплава по таблице кросс-кодов"""
        src = source_grade.strip().upper()
        # Поддержка числовых кодов Sandvik без префикса GC (например, 4325 -> GC4325)
        src_variants = {src}
        if re.match(r"^\d{4}$", src):
            src_variants.add("GC" + src)
        elif src.startswith("GC") and len(src) == 6:
            src_variants.add(src[2:])

        matching_rows = []
        brand_keys = ["sandvik", "iscar", "korloy", "walter", "deskar", "mitsubishi", "zcc_ct", "kennametal", "seco", "kyocera"]

        for row in self.cross_codes:
            for b_key in brand_keys:
                if (row.get(b_key, "") or "").upper() in src_variants:
                    matching_rows.append((row, b_key))
                    break

        results = []
        for row, found_brand in matching_rows:
            analogs = {}
            for b_key in brand_keys:
                val = row.get(b_key, "")
                if val and val.upper() not in src_variants:
                    norm_brand = b_key.replace("_", "-").title()
                    if norm_brand.lower() == "zcc-ct":
                        norm_brand = "ZCC-CT"
                    analogs[norm_brand] = val

            if target_brand:
                target_norm = target_brand.strip().lower()
                filtered = {b: g for b, g in analogs.items() if target_norm in b.lower()}
                if filtered:
                    analogs = filtered

            results.append({
                "source_grade": src,
                "detected_brand": found_brand.replace("_", "-").title(),
                "iso_group": row["iso_group"],
                "iso_range": row["iso_range"],
                "application_type": row["application_type"],
                "operation_desc": row["operation_desc"],
                "analogs": analogs,
            })

        return results

    def parse_sku_elements(self, sku: str) -> Dict[str, str]:
        sku_clean = sku.strip()
        parts = re.split(r"[-\s_]+", sku_clean)
        geometry = parts[0].upper() if len(parts) > 0 else ""
        chipbreaker = parts[1].upper() if len(parts) > 1 else ""
        grade = parts[2].upper() if len(parts) > 2 else ""

        if not grade and len(parts) == 2:
            if parts[1].upper() in self.grades:
                grade = parts[1].upper()
                chipbreaker = ""

        return {
            "full_sku": sku_clean,
            "geometry": geometry,
            "chipbreaker": chipbreaker,
            "grade": grade,
        }
