"""
src/analogs_engine.py - Движок сопоставления кросс-кодов, сплавов и стружколомов (Excel + CSV + каталог + серии ISO)
"""
import csv
import os
import re
from typing import Any, Dict, List, Optional, Tuple


# Полная матрица из файла Кросс_таблица_Аналогов_Сплавов_и_Стружколомов.xlsx (Лист 1)
EXCEL_MATRIX = [
    {
        "iso_group": "P", "iso_range": "P10", "chipbreakers": ["PF", "GF", "F1", "HQ", "EF", "LP", "HA", "VF"],
        "application_type": "finishing", "operation_desc": "Чистовая (P10): малый припуск, острая кромка, свободный сход стружки",
        "analogs": {
            "ZZKLT (Келит)": "KT1152, KT1251", "КЗТС": "TC20PT, AP10AT", "Sandvik": "GC1010, GC1020, GC4315",
            "ZCC-CT": "YBG102, YBC151, YBC152", "Iscar": "IC903, IC950, IC1008, IC8150",
            "Kennametal": "KC522M, KC525M, KC610M, KC643M, KC715M, KCP10", "Sumitomo": "ACZ10M, ACZ20W, AC8015P",
            "Mitsubishi": "VP10H, UE6105, MC6015", "Kyocera": "PR730, PR1225, PR1525, CA5515",
            "Walter": "WHX15, WHH15, WXM15, WPP10S", "SECO": "F15M, TP1501", "Korloy": "NC3215",
            "INTOOL": "IP4005, IP4015, IP4020", "Deskar": "LF9011, LF9018",
            "Tungaloy": "AH120, GH130, T9115, T9215", "Ingersoll": "IN2004, IN2006"
        }
    },
    {
        "iso_group": "P", "iso_range": "P20", "chipbreakers": ["PM", "PMK", "UC", "M1", "M2", "M4", "M5", "M6", "M8", "M9", "CQ", "QM", "DM", "EM", "TM", "HM", "MP", "MA"],
        "application_type": "semi_finishing", "operation_desc": "Получистовая (P20): универсальная, баланс прочности и остроты, стабильное дробление",
        "analogs": {
            "ZZKLT (Келит)": "KT1252, KT1253, KT1373, KLP25", "КЗТС": "TC20PT, TC33PT",
            "Sandvik": "GC1025, GC2030, GC4325", "ZCC-CT": "YBG202, YBG252, YBC251, YBC252",
            "Iscar": "IC810, IC830, IC900, IC908, IC910, IC950, IC1008, IC8250",
            "Kennametal": "KC522M, KC525M, KC643M, KC715M, KC725M, KCP25",
            "Sumitomo": "ACP200, ACZ330, ACX70, ACW30, AC350, ACZ50M",
            "Mitsubishi": "VP15TF, VP20M, VP20RT, UE6110, MC6025",
            "Kyocera": "PR630, PR830, PR730, PR1225, PR1230, PR1525, CA5525",
            "Walter": "WXM15, WPP20S", "SECO": "F25M, MP3000, TP2501", "Korloy": "PC3500, PC3600, NC3225",
            "INTOOL": "IP4005, IP4015, IP4020, IP4325", "Deskar": "LF9018",
            "Tungaloy": "AH725, AH120, AH130, AH330, GH330, T9125, T9225",
            "Ingersoll": "IN2006, IN1030, IN2004, IN2005, IN2015, IN2030, IN2505, IN2540"
        }
    },
    {
        "iso_group": "P", "iso_range": "P30", "chipbreakers": ["PR", "ZR", "R1", "R2", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R12", "GS", "GR", "HR", "DR", "MR", "QR", "RP"],
        "application_type": "roughing", "operation_desc": "Черновая (P30): прочная кромка, ударные нагрузки, неравномерный припуск, корка",
        "analogs": {
            "ZZKLT (Келит)": "KT1253H, KT1373, KLP35", "КЗТС": "TC33PT, TC40PT, TP35AM",
            "Sandvik": "GC1030, GC2030, GC4335", "ZCC-CT": "YBG302, YBC351",
            "Iscar": "IC300, IC328, IC830, IC900, IC928, IC350, IC808, IC908, IC8350",
            "Kennametal": "KC530M, KC725M, KC735M, KCP40",
            "Sumitomo": "ACP200, ACP300, ACZ50M, ACZ330, ACZ350, ACX70, ACW30, AC350",
            "Mitsubishi": "VP30RT, UE6020, MC6035", "Kyocera": "PR630, PR660, PR830, PR1230, CA5535",
            "Walter": "WXM35, WPP30S", "SECO": "F30M, MP3000, TP3501",
            "Korloy": "PC3500, PC3600, PC5300, PC3545, PC9570T, NC3120",
            "INTOOL": "IP4015, IP4020, IP4325, IP4035", "Deskar": "LF9028",
            "Tungaloy": "AH740, AH130, AH140",
            "Ingersoll": "IN1030, IN2005, IN2015, IN2030, IN2035, IN2040, IN2505, IN2530, IN4035"
        }
    },
    {
        "iso_group": "M", "iso_range": "M10-M30", "chipbreakers": ["MJ", "MM-B", "MP", "MM", "MT", "MF", "EF", "EM", "SM", "QM", "TF", "NF", "HA", "LP", "HQ", "CQ"],
        "application_type": "semi_finishing", "operation_desc": "Нержавеющая сталь (M10-M30): острая и прочная кромка, защита от нароста и выкрашивания",
        "analogs": {
            "ZZKLT (Келит)": "KT8204, KT8206, KT8284, KT8286, KT8256, KLM15, KLM25",
            "КЗТС": "AP10AT, AP10AM, TC20PT, AP30AM",
            "Sandvik": "GC1020, GC1025, GC1030, GC2030, GC2015, GC2025, GC2220, GC1115, GC1125",
            "ZCC-CT": "YBG202, YBG205, YBG252, YBM151, YBM251",
            "Iscar": "IC830, IC907, IC908, IC950, IC1008, IC6015, IC6025, IS7015",
            "Kennametal": "KC522M, KC525M, KC610M, KC715M, KC725M, KCU10, KCU25, KCM15",
            "Sumitomo": "ACZ20W, ACZ350, EH20Z, ACP200, ACZ50M, AC350, AC6020M, AC6030M",
            "Mitsubishi": "VP15TF, VP20RT, MC7015, MC7025, US7020, US735, MP7035",
            "Kyocera": "PR730, PR1025, PR660, PR1125, PR1225, PR1525, PR1535",
            "Walter": "WXM15, WSM10S, WSM20S", "SECO": "F15M, F25M, MP3000, TM2000, TM4000",
            "Korloy": "PC8110, PC5300, PC9530, PC9030, NC9115",
            "Deskar": "LF6011, LF6018, LF6028, LF6118",
            "Tungaloy": "AH330, GH110, GH130, AH725, AH730, AH630, T6120, T6130",
            "TaeguTec": "TT9215, TT9225, TT9235, TT5080, TT8020",
            "Ingersoll": "IN2505, IN2005, IN2015"
        }
    },
    {
        "iso_group": "K", "iso_range": "K10-K25", "chipbreakers": ["MB", "Flat", "F1", "UC", "ZT", "ZD", "KM", "KR", "KF", "DR", "DF", "DM", "GS", "GR", "HK"],
        "application_type": "semi_finishing", "operation_desc": "Чугун (K10-K25): высокая прочность кромки, серый и высокопрочный чугун, снятие корки",
        "analogs": {
            "ZZKLT (Келит)": "KT3122, KT3252, KT3262, KT3263, KLK15", "КЗТС": "BC20HT, BC35HT",
            "Sandvik": "GC1010, GC1020, GC3215, GC3225, GC3015", "ZCC-CT": "YBG102, YBG152, YBD151, YBD152, YBD252",
            "Iscar": "IC810, IC950, IC1008, IC328, IC830, IC350, IC808, IC908, IC5005, IC5010, IS8, IS80",
            "Kennametal": "KC510M, KC520M, KC620M, KC643M, KC725M, KCK15, KCK20",
            "Sumitomo": "EH20Z, ACZ310, ACK300, ACX80, ACW30, AC4015K, AC415K",
            "Mitsubishi": "VP15TF, MC5005, MC5015, UC5115",
            "Kyocera": "PR905, PR1210, PR1510, CA4505, CA4515",
            "Walter": "WXH15, WHH15, WXM15, WKK10S, WKK20S, WKK25",
            "SECO": "F15M, F25M, MK2000, MO3000, TK1501, TK2001",
            "Korloy": "PC6510, PC5300, NC6315, NC6320", "Deskar": "LF3018, LF3028, LF9118, LF9128",
            "Tungaloy": "AH120, AH330, AH725, GH130, T515, T5115",
            "TaeguTec": "TT7005, TT7015, TT7310",
            "Ingersoll": "IN1030, IN2004, IN2010, IN2015, IN2030, IN2505, IN2510"
        }
    },
    {
        "iso_group": "N", "iso_range": "N10-N25", "chipbreakers": ["NF", "NM", "NR", "HA", "AL", "LC", "AK", "FN2", "AX"],
        "application_type": "finishing", "operation_desc": "Цветные металлы и алюминий (N10-N25): позитивная геометрия, острый полированный клин без налипания",
        "analogs": {
            "ZZKLT (Келит)": "KT3150G, KT3150", "КЗТС": "A10, A30",
            "Sandvik": "H10, H13A, GC1020", "ZCC-CT": "YD101, YD201, YBG102",
            "Iscar": "IC20, IC08, IC907", "Kennametal": "KC510M, K10",
            "Sumitomo": "ACZ10M, H1", "Mitsubishi": "HTI10", "Kyocera": "KW10",
            "Walter": "WXN10", "SECO": "HX", "Korloy": "H01", "Deskar": "K10, LF6838"
        }
    },
    {
        "iso_group": "H", "iso_range": "H10-H25", "chipbreakers": ["MF", "CF", "HJ", "TF", "KGF", "PJ-X", "SF", "HM", "NN"],
        "application_type": "finishing", "operation_desc": "Закалённая сталь HRC 45-65 (H10-H25): чистовое точение твёрдых сталей",
        "analogs": {
            "ZZKLT (Келит)": "KT6109, KT6109T, KT6119, KT8296", "КЗТС": "AP10AT, AP10AM, H10, H20",
            "Sandvik": "CB7015, CB7020, GC1025", "ZCC-CT": "YBG202", "Iscar": "IC907, IB10HC",
            "Walter": "WHH15", "Korloy": "PC8110", "Deskar": "LF9218, LF70, LF80, LF90, TF618, TF918",
            "Mitsubishi": "MB8025", "Kennametal": "KB1630", "SECO": "CBN100", "Kyocera": "KBN05M"
        }
    }
]

# Стружколомы КЗТС / общие с их назначением и группой
CHIPBREAKER_GROUPS = {
    "PF": ("P", "finishing", ["PF", "GF", "F1", "HQ", "EF", "HA", "LP", "MF", "QF", "SF"]),
    "GF": ("P", "finishing", ["PF", "GF", "F1", "HQ", "EF", "HA", "LP", "MF", "QF"]),
    "F1": ("P", "finishing", ["F1", "PF", "GF", "HQ", "EF", "HA", "LP", "MF"]),
    "HQ": ("P", "finishing", ["HQ", "PF", "GF", "F1", "EF", "HA", "LP", "MF"]),
    "EF": ("M", "finishing", ["EF", "MF", "MJ", "MM-B", "SF", "PF", "HQ", "NF", "HA"]),
    "PM": ("P", "semi_finishing", ["PM", "PMK", "UC", "M1", "M2", "M4", "M5", "CQ", "QM", "DM", "EM", "TM", "HM", "MP", "MA", "MM"]),
    "PMK": ("P", "semi_finishing", ["PMK", "PM", "UC", "M1", "M2", "CQ", "QM", "DM", "EM", "TM", "HM", "MM"]),
    "CQ": ("P", "semi_finishing", ["CQ", "PM", "PMK", "UC", "M1", "QM", "DM", "EM", "TM", "HM", "MM"]),
    "QM": ("P", "semi_finishing", ["QM", "PM", "PMK", "CQ", "DM", "EM", "TM", "HM", "MM"]),
    "MM": ("M", "semi_finishing", ["MM", "MJ", "MM-B", "MP", "MT", "EM", "GM", "SM", "PM", "TM", "HM", "MA"]),
    "MJ": ("M", "semi_finishing", ["MJ", "MM-B", "MP", "MM", "MT", "EM", "GM", "SM", "MF"]),
    "MP": ("M", "semi_finishing", ["MP", "MJ", "MM-B", "MM", "MT", "EM", "GM", "SM", "PM"]),
    "MT": ("M", "semi_finishing", ["MT", "MM", "MJ", "MP", "EM", "GM", "SM", "PM", "TM"]),
    "GM": ("M", "semi_finishing", ["GM", "MM", "MJ", "MP", "MT", "EM", "SM", "PM", "CQ"]),
    "SM": ("M", "semi_finishing", ["SM", "MM", "MJ", "MP", "MT", "EM", "GM", "TF"]),
    "EM": ("M", "semi_finishing", ["EM", "MM", "MJ", "MP", "MT", "GM", "SM", "PM"]),
    "PR": ("P", "roughing", ["PR", "ZR", "R1", "R2", "R4", "GS", "GR", "HR", "DR", "MR", "QR", "RP", "NR"]),
    "ZR": ("P", "roughing", ["ZR", "PR", "R1", "GS", "GR", "HR", "DR", "MR", "QR"]),
    "GS": ("P", "roughing", ["GS", "PR", "ZR", "GR", "HR", "DR", "MR", "QR", "RP"]),
    "GR": ("P", "roughing", ["GR", "PR", "ZR", "GS", "HR", "DR", "MR", "QR"]),
    "HR": ("P", "roughing", ["HR", "PR", "ZR", "GS", "GR", "DR", "MR", "QR"]),
    "DR": ("K", "roughing", ["DR", "PR", "ZR", "GS", "GR", "HR", "KR", "MR", "UC", "ZT", "ZD"]),
    "MR": ("M", "roughing", ["MR", "PR", "GR", "HR", "DR", "QR", "RM"]),
    "NF": ("N", "finishing", ["NF", "AL", "HA", "LC", "AK", "AX", "FN2"]),
    "AL": ("N", "finishing", ["AL", "NF", "HA", "LC", "AK", "AX", "FN2"]),
    "HA": ("N", "finishing", ["HA", "AL", "NF", "LC", "AK", "EF"]),
    "MB": ("K", "finishing", ["MB", "F1", "KF", "DF", "PF"]),
    "UC": ("K", "semi_finishing", ["UC", "ZT", "ZD", "KM", "KR", "PM", "PMK", "DM"]),
    "KM": ("K", "semi_finishing", ["KM", "UC", "ZT", "ZD", "KR", "KF", "DM", "DR"]),
}


class AnalogsEngine:
    def __init__(
        self,
        cross_codes_path: str = "data/cross_codes.csv",
        grades_path: str = "data/grades.csv",
        chipbreakers_path: str = "data/chipbreakers_cross.csv",
        *args,
        **kwargs,
    ):
        self.cross_codes: List[Dict] = []
        self.grades: Dict[str, Dict] = {}
        self.chipbreakers: List[Dict] = []
        self.catalog_grades: Dict[str, Dict[str, Any]] = {}
        self.excel_matrix: List[Dict[str, Any]] = list(EXCEL_MATRIX)
        self.cb_groups: Dict[str, Tuple[str, str, List[str]]] = dict(CHIPBREAKER_GROUPS)
        self._load_data(cross_codes_path, grades_path, chipbreakers_path)

    def _load_data(self, cross_codes_path: str, grades_path: str, chipbreakers_path: str):
        if os.path.exists(cross_codes_path):
            with open(cross_codes_path, "r", encoding="utf-8-sig") as f:
                self.cross_codes = list(csv.DictReader(f))

        if os.path.exists(grades_path):
            with open(grades_path, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    g_key = (row.get("grade") or "").strip().upper()
                    if g_key:
                        self.grades[g_key] = row

        docs_grades_path = os.path.join("data", "grades_docs.csv")
        if os.path.exists(docs_grades_path):
            with open(docs_grades_path, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    g_key = (row.get("grade") or "").strip().upper()
                    if g_key and g_key not in self.grades:
                        self.grades[g_key] = {
                            "grade": g_key,
                            "brand": row.get("brand", ""),
                            "iso_groups": row.get("iso_groups", ""),
                            "application_type": "medium",
                            "note": f"Классы: {row.get('classes', '')}",
                        }

        if os.path.exists(chipbreakers_path):
            with open(chipbreakers_path, "r", encoding="utf-8-sig") as f:
                self.chipbreakers = list(csv.DictReader(f))

        # Подгружаем все реально существующие марки сплавов из каталогов остатков
        for cat_file in ("data/catalog_both.csv", "data/catalog_qtool.csv", "data/catalog_rinscom.csv"):
            if os.path.exists(cat_file):
                try:
                    with open(cat_file, "r", encoding="utf-8-sig") as f:
                        for r in csv.DictReader(f):
                            g = (r.get("grade") or "").strip().upper()
                            iso = (r.get("iso_group") or "").strip().upper()
                            b = (r.get("brand") or "").strip()
                            if g and len(g) >= 2 and not g.isdigit():
                                entry = self.catalog_grades.setdefault(g, {"brands": set(), "isos": []})
                                if b:
                                    entry["brands"].add(b)
                                for part in iso.split(","):
                                    p = part.strip()
                                    if p in ("P", "M", "K", "N", "S", "H") and p not in entry["isos"]:
                                        entry["isos"].append(p)
                    break
                except Exception:
                    pass

    @staticmethod
    def infer_grade_heuristic(token: str) -> Optional[Dict[str, str]]:
        """
        Распознаёт группу ISO, бренд и тип обработки по отраслевым сериям марок сплавов,
        даже если конкретной марки (например, IS7015) нет на складе!
        """
        t = token.strip().upper()
        if not t or len(t) < 3:
            return None

        # Защита от захвата геометрии пластин и державок
        if re.match(r"^[CWTDSVRLAEOH][NCTBPEFG][MGU][A-Z]", t):
            return None
        if re.match(r"^(PCLN|MCLN|PWLN|MWLN|PTGN|MTGN|PDJN|MDJN|MVJN|PVJN|PSSN|MSSN|SCLC|SDJC|STGC|SVJB|SVJC|SER|SEL|SIR|SIL|MGEHR|MGEHL|MGIVR)", t):
            return None

        # Серия *7015 / *7020 / *7025 / *7035:
        # IS7015, MC7015, MC7025, US7020, MP7035 -> Нержавеющая сталь ISO M (кроме TT7015=K и CB7015=H)
        if re.match(r"^(IS|MC|US|MP|GM|NC|PC|VP|IC|KC|AC)70(15|20|25|35)$", t):
            op = "finishing" if t.endswith("15") else ("roughing" if t.endswith("35") else "semi_finishing")
            brand = {"IS": "Iscar / Инструментальный сплав", "MC": "Mitsubishi", "US": "Mitsubishi", "MP": "Mitsubishi"}.get(t[:2], "Импортный бренд")
            return {"grade": t, "iso_group": "M", "iso_range": "M10-M25", "application_type": op, "brand": brand,
                    "note": f"Сплав {t} предназначен для обработки нержавеющей стали (группа ISO M)"}

        # TaeguTec TT7005 / TT7015 / TT7310 -> Чугун ISO K; TT9215/9225/9235/5080 -> Нержавейка ISO M; TT8115/8125/8135 -> Сталь ISO P
        if t.startswith("TT") and len(t) >= 5 and t[2:].isdigit():
            num = t[2:]
            if num.startswith("7"):
                return {"grade": t, "iso_group": "K", "iso_range": "K10-K25", "application_type": "semi_finishing", "brand": "TaeguTec"}
            if num.startswith(("9", "50", "80")):
                return {"grade": t, "iso_group": "M", "iso_range": "M15-M30", "application_type": "semi_finishing", "brand": "TaeguTec"}
            if num.startswith("81"):
                return {"grade": t, "iso_group": "P", "iso_range": "P15-P30", "application_type": "semi_finishing", "brand": "TaeguTec"}

        # ZZKLT / Kelite: KT82.. -> M (нержавейка), KT11../12../13.. -> P (сталь), KT3150G -> N, KT31../32.. -> K (чугун), KT61../62.. -> H
        if re.match(r"^(KT|КТ)\d{4}[A-Z]?$", t):
            t_lat = "KT" + t[2:]
            d2 = t_lat[2:4]
            if d2 in ("82", "83", "22", "14"):
                return {"grade": t_lat, "iso_group": "M", "iso_range": "M10-M30", "application_type": "semi_finishing", "brand": "ZZKLT (Келит)"}
            if t_lat.startswith("KT3150"):
                return {"grade": t_lat, "iso_group": "N", "iso_range": "N10-N25", "application_type": "finishing", "brand": "ZZKLT (Келит)"}
            if d2 in ("31", "32"):
                return {"grade": t_lat, "iso_group": "K", "iso_range": "K10-K25", "application_type": "semi_finishing", "brand": "ZZKLT (Келит)"}
            if d2 in ("61", "62"):
                return {"grade": t_lat, "iso_group": "H", "iso_range": "H10-H20", "application_type": "finishing", "brand": "ZZKLT (Келит)"}
            if d2 in ("11", "12", "13"):
                return {"grade": t_lat, "iso_group": "P", "iso_range": "P15-P30", "application_type": "semi_finishing", "brand": "ZZKLT (Келит)"}

        # Deskar: LF60../61.. -> M, LF90.. -> P, LF30../91.. -> K, LF92../TF618 -> H
        if re.match(r"^LF\d{2,4}$", t):
            if t.startswith(("LF60", "LF61")):
                return {"grade": t, "iso_group": "M", "iso_range": "M15-M30", "application_type": "semi_finishing", "brand": "Deskar"}
            if t.startswith("LF90"):
                return {"grade": t, "iso_group": "P", "iso_range": "P15-P30", "application_type": "semi_finishing", "brand": "Deskar"}
            if t.startswith(("LF30", "LF91")):
                return {"grade": t, "iso_group": "K", "iso_range": "K10-K25", "application_type": "semi_finishing", "brand": "Deskar"}
            if t.startswith("LF92"):
                return {"grade": t, "iso_group": "H", "iso_range": "H10-H25", "application_type": "finishing", "brand": "Deskar"}

        # ZCC-CT: YBM.. / YBG.. -> M, YBC.. -> P, YBD.. -> K, YD.. -> N
        if re.match(r"^YB[CMGD]\d{3}[A-Z]?$", t):
            ch = t[2]
            iso_map = {"M": "M", "G": "M", "C": "P", "D": "K"}
            return {"grade": t, "iso_group": iso_map.get(ch, "P"), "iso_range": f"{iso_map.get(ch, 'P')}15-30", "application_type": "semi_finishing", "brand": "ZCC-CT"}

        # Iscar: IC6015/6025/907/908/807/830 -> M, IC8150/8250/8350/9150/9250 -> P, IC5005/5010/428 -> K
        if re.match(r"^IC\d{3,4}[A-Z]?$", t):
            if t in ("IC6015", "IC6025", "IC907", "IC908", "IC807", "IC830", "IC3028"):
                return {"grade": t, "iso_group": "M", "iso_range": "M10-M30", "application_type": "semi_finishing", "brand": "Iscar"}
            if t in ("IC5005", "IC5010", "IC428", "IC4028"):
                return {"grade": t, "iso_group": "K", "iso_range": "K10-K25", "application_type": "semi_finishing", "brand": "Iscar"}
            if t.startswith(("IC81", "IC82", "IC83", "IC91", "IC92", "IC93", "IC901", "IC902")):
                return {"grade": t, "iso_group": "P", "iso_range": "P15-P30", "application_type": "semi_finishing", "brand": "Iscar"}

        # Sandvik (с GC или 4 цифры): 2015/2025/2035/2220/1115/1125 -> M; 4215/4225/4235/4315/4325/4335/4415/4425 -> P; 3015/3215/3225 -> K; 7015/7020 -> H
        m_sv = re.match(r"^(?:GC|CB)?(\d{4})$", t)
        if m_sv:
            num = m_sv.group(1)
            if num.startswith(("20", "22", "11")):
                return {"grade": t, "iso_group": "M", "iso_range": "M15-M30", "application_type": "semi_finishing", "brand": "Sandvik"}
            if num.startswith(("40", "42", "43", "44", "10", "15")):
                return {"grade": t, "iso_group": "P", "iso_range": "P15-P30", "application_type": "semi_finishing", "brand": "Sandvik"}
            if num.startswith(("30", "32")):
                return {"grade": t, "iso_group": "K", "iso_range": "K10-K25", "application_type": "semi_finishing", "brand": "Sandvik"}
            if num.startswith("70"):
                return {"grade": t, "iso_group": "H", "iso_range": "H10-H20", "application_type": "finishing", "brand": "Sandvik"}

        # Mitsubishi: MC60../61../UE6.. -> P, MC70../US7../MP7.. -> M, MC50../UC5.. -> K
        if re.match(r"^(MC|UE|US|MP|UC)\d{3,4}[A-Z]?$", t):
            if t.startswith(("MC70", "US7", "MP70")):
                return {"grade": t, "iso_group": "M", "iso_range": "M10-M30", "application_type": "semi_finishing", "brand": "Mitsubishi"}
            if t.startswith(("MC60", "MC61", "UE6")):
                return {"grade": t, "iso_group": "P", "iso_range": "P15-P30", "application_type": "semi_finishing", "brand": "Mitsubishi"}
            if t.startswith(("MC50", "UC5", "UC4")):
                return {"grade": t, "iso_group": "K", "iso_range": "K10-K25", "application_type": "semi_finishing", "brand": "Mitsubishi"}

        # КЗТС: TC20PT/TC33PT/TC40PT/TP20AM/TP35AM -> P, AP10AT/AP10AM/AP30AM -> M, BC20HT/BC35HT -> K, A10/A30 -> N
        if t in ("TC20PT", "TC33PT", "TC40PT", "TP20AM", "TP35AM"):
            return {"grade": t, "iso_group": "P", "iso_range": "P15-P35", "application_type": "semi_finishing", "brand": "КЗТС"}
        if t in ("AP10AT", "AP10AM", "AP30AM", "BC20PT", "BC35PT"):
            return {"grade": t, "iso_group": "M", "iso_range": "M10-M30", "application_type": "semi_finishing", "brand": "КЗТС"}
        if t in ("BC20HT", "BC35HT"):
            return {"grade": t, "iso_group": "K", "iso_range": "K10-K30", "application_type": "semi_finishing", "brand": "КЗТС"}

        return None

    def extract_grade_and_sku(self, text: str) -> Dict[str, Any]:
        """Извлечение марки твердого сплава, стружколома, ISO-группы и артикула из свободного текста запроса."""
        upper = (text or "").upper()
        detected_sku = ""
        m_sku = re.search(r"[CWTDSVRLAEOH][NCTBPEFG][MGU][A-Z]\s*\d{6}(?:-[A-Z0-9]+)*", upper)
        if m_sku:
            detected_sku = m_sku.group(0).replace(" ", "")

        # Убираем сам ISO-код пластины из текста, чтобы не спутать цифры размера (120408) с маркой сплава
        rest_text = upper
        if m_sku:
            rest_text = upper.replace(m_sku.group(0), " ")

        # Собираем все известные марки из grades.csv, cross_codes.csv, Excel-матрицы и каталога
        all_known_grades = set(self.grades.keys()) | set(self.catalog_grades.keys())
        brand_keys = ["sandvik", "iscar", "korloy", "walter", "deskar", "mitsubishi", "zcc_ct", "kennametal", "seco", "kyocera"]
        for row in self.cross_codes:
            for bk in brand_keys:
                val = (row.get(bk) or "").strip().upper()
                if val:
                    all_known_grades.add(val)
        for m_row in self.excel_matrix:
            for grades_str in m_row["analogs"].values():
                for g_item in re.split(r"[,/]+", grades_str):
                    g_clean = re.sub(r"\(.*?\)", "", g_item).strip().upper()
                    if g_clean and len(g_clean) >= 2:
                        all_known_grades.add(g_clean)

        detected_grade = ""
        sorted_grades = sorted((g for g in all_known_grades if len(g) >= 3 and not g.isdigit()), key=len, reverse=True)
        for g in sorted_grades:
            pattern = r"(?<![A-ZА-Я0-9])" + re.escape(g) + r"(?![A-ZА-Я0-9])"
            if re.search(pattern, rest_text):
                detected_grade = g
                break

        # Если точного совпадения в словаре нет — проверяем токены по эвристике серий (например, IS7015)
        heur_info = None
        if not detected_grade:
            for tok in re.findall(r"[A-ZА-Я0-9]{3,10}", rest_text):
                h = self.infer_grade_heuristic(tok)
                if h:
                    detected_grade = h["grade"]
                    heur_info = h
                    break
        else:
            heur_info = self.infer_grade_heuristic(detected_grade)

        # Извлекаем стружколом, если он указан (через дефис или отдельным словом, например -PM, -MM, PF, QM)
        detected_cb = ""
        if "-" in detected_sku:
            _, _, after_dash = detected_sku.partition("-")
            if after_dash and after_dash in self.cb_groups:
                detected_cb = after_dash
        if not detected_cb:
            for tok in re.findall(r"[A-Z0-9-]{2,5}", rest_text):
                if tok != detected_grade and tok in self.cb_groups:
                    detected_cb = tok
                    break

        # Определяем группу ISO и операцию по найденному сплаву или стружколому
        iso_group = ""
        operation = ""
        brand_name = ""
        if heur_info:
            iso_group = heur_info.get("iso_group", "")
            operation = heur_info.get("application_type", "")
            brand_name = heur_info.get("brand", "")
        if detected_grade in self.grades:
            g_row = self.grades[detected_grade]
            iso_raw = (g_row.get("iso_groups") or "").strip().upper()
            if iso_raw and not iso_group:
                iso_group = iso_raw.split(",")[0].strip()
            if not operation and g_row.get("application_type"):
                operation = g_row["application_type"]
            if not brand_name and g_row.get("brand"):
                brand_name = g_row["brand"]
        if not iso_group and detected_grade in self.catalog_grades:
            isos = self.catalog_grades[detected_grade]["isos"]
            if isos:
                # Если сплав специфичен для M, K, N, S, H, выбираем его
                for pref in ("M", "K", "N", "H", "S", "P"):
                    if pref in isos and (len(isos) == 1 or pref != "P"):
                        iso_group = pref
                        break
                if not iso_group:
                    iso_group = isos[0]
            brands = list(self.catalog_grades[detected_grade]["brands"])
            if brands and not brand_name:
                brand_name = brands[0]

        if detected_cb and detected_cb in self.cb_groups:
            cb_iso, cb_op, _ = self.cb_groups[detected_cb]
            if not operation:
                operation = cb_op
            if not iso_group:
                iso_group = cb_iso

        return {
            "grade": detected_grade,
            "sku": detected_sku,
            "chipbreaker": detected_cb,
            "iso_group": iso_group,
            "operation": operation,
            "brand": brand_name,
        }

    def get_chipbreaker_analogs(self, cb: Optional[str], iso_group: Optional[str] = None, operation: Optional[str] = None) -> List[str]:
        """Возвращает список аналогичных стружколомов по кросс-таблице."""
        if cb and cb.upper() in self.cb_groups:
            return list(self.cb_groups[cb.upper()][2])
        for m_row in self.excel_matrix:
            if iso_group and m_row["iso_group"] == iso_group.upper():
                if not operation or m_row["application_type"] == operation or m_row["iso_group"] in ("M", "N", "H"):
                    return list(m_row["chipbreakers"])
        return []

    def find_grade_cross(self, source_grade: str, target_brand: Optional[str] = None, fallback_iso: Optional[str] = None, fallback_op: Optional[str] = None) -> List[Dict]:
        """Поиск аналогов марки твердого сплава по Excel-матрице и таблице кросс-кодов."""
        src = (source_grade or "").strip().upper()
        src_variants = {src}
        if re.match(r"^\d{4}$", src):
            src_variants.add("GC" + src)
        elif src.startswith("GC") and len(src) == 6:
            src_variants.add(src[2:])

        results = []

        # 1. Ищем точное вхождение сплава в матрице Excel
        for m_row in self.excel_matrix:
            found_brand = None
            for b_name, g_str in m_row["analogs"].items():
                tokens = [re.sub(r"\(.*?\)", "", x).strip().upper() for x in re.split(r"[,/]+", g_str)]
                if src in tokens or any(v in tokens for v in src_variants):
                    found_brand = b_name
                    break
            if found_brand:
                analogs = {}
                for b_name, g_str in m_row["analogs"].items():
                    analogs[b_name] = g_str
                results.append({
                    "source_grade": src,
                    "detected_brand": found_brand,
                    "iso_group": m_row["iso_group"],
                    "iso_range": m_row["iso_range"],
                    "application_type": m_row["application_type"],
                    "operation_desc": m_row["operation_desc"],
                    "chipbreakers": m_row["chipbreakers"],
                    "analogs": analogs,
                })

        # 2. Если в матрице точного кода нет (например, IS7015), определяем группу ISO по эвристике/каталогу и берём строку матрицы для этой группы!
        if not results:
            heur = self.infer_grade_heuristic(src)
            iso_g = (heur or {}).get("iso_group") or fallback_iso or ""
            op_g = (heur or {}).get("application_type") or fallback_op or "semi_finishing"
            brand_g = (heur or {}).get("brand") or "Импортный сплав"

            if not iso_g and src in self.grades:
                iso_g = (self.grades[src].get("iso_groups") or "").split(",")[0].strip().upper()
                op_g = self.grades[src].get("application_type") or op_g
                brand_g = self.grades[src].get("brand") or brand_g
            if not iso_g and src in self.catalog_grades:
                isos = self.catalog_grades[src]["isos"]
                if isos:
                    iso_g = "M" if "M" in isos and len(isos) <= 2 else isos[0]

            if iso_g:
                for m_row in self.excel_matrix:
                    if m_row["iso_group"] == iso_g:
                        if iso_g == "P" and m_row["application_type"] != op_g and op_g in ("finishing", "semi_finishing", "roughing"):
                            continue
                        results.append({
                            "source_grade": src,
                            "detected_brand": brand_g,
                            "iso_group": m_row["iso_group"],
                            "iso_range": m_row["iso_range"],
                            "application_type": m_row["application_type"],
                            "operation_desc": m_row["operation_desc"],
                            "chipbreakers": m_row["chipbreakers"],
                            "analogs": dict(m_row["analogs"]),
                        })
                        break

        return results

    def parse_sku_elements(self, sku: str) -> Dict[str, str]:
        ext = self.extract_grade_and_sku(sku)
        return {
            "full_sku": sku.strip(),
            "geometry": ext.get("sku", ""),
            "chipbreaker": ext.get("chipbreaker", ""),
            "grade": ext.get("grade", ""),
        }
